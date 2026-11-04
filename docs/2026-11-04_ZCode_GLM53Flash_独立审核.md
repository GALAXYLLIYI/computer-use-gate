# ZCode 独立审核（GLM-5.3-Flash）

> 时间：2026-11-04T01:27:14.732Z
> 通道：Magpie 网关 http://127.0.0.1:3425 → trae-cn/glm-5.3-flash（GLM-5.3-Flash 免费额度路由）
> 说明：ZCode 自带 provider 的 API key 返回 401，未走 ZCode UI；本审核为同模型独立通道。

# 独立审核意见（2026-11-04，GLM-5.3-Flash）

## 一、结论摘要

1. 数据层体检结论可信（integrity ok / 重复 0），但 **dedup 合并口径有污染面**：outcome、subject、provenance 未列入合并字段。
2. `sft_success.jsonl` 403 行若生成于 dedup 前，文本/标签可能错配，属训练污染，须重生成。
3. 材料无法证明存在 **dedup 前备份**；14 份滚动保留还会把它淘汰掉——回滚链有断点。
4. 策略评测**调参与验收共用同一 10 条查询集**，hit_rate=1.0 已饱和，策略晋级验收失效。
5. 217 段“够用”未被证明：仅 10 条固定查询，段向量是否随 dedup 重建未提及。
6. 最小闭环缺三件：晋级审批落地、candidate 空转演练、循环存活检测。
7. QLoRA 缺口：无 GPU 互斥锁、无中途 OOM 处置、训练后不恢复 Ollama。
8. ZCode UI 审核最大风险：会话若带工作区工具权限，“只读纪律”只是提示词，不是约束。

## 二、逐条回答

**Q1 dedup 合并口径是否有遗漏**
- 结论：有。列出的合并字段（result/verify/text/embed/recurrences）不含 outcome、subject、actor、provenance。
- 证据：审核请求 §2-Q1 字段清单；引擎发展计划 §3.1 要求事件带 outcome/provenance/actor，但合并规则未提；验收 §3 显示 `sft_success.jsonl` 403 行，未标注生成于 dedup 前还是后；同一节 `episodes_count` 曾 8571→1067 人工修正，训练侧与库不同步已发生过。
- 建议：① 合并规则固定：outcome 取最新一次；组内出现多 subject → 拒绝合并，落 `dedup_conflicts/`。② dedup 后必跑两条检查：`GROUP BY dedup_key HAVING COUNT(DISTINCT subject)>1` 须为 0；`COUNT(DISTINCT outcome)>1` 逐组人工复核。③ dedup 后重跑样本生成，文件头写入源快照 manifest hash。
- 风险：**P0**。

**Q2 217 段是否够用 / subject 一致性**
- 结论：现有证据不能证明够用；subject 当前无错位，但合并后段向量/摘要是否重建未提及。
- 证据：引擎发展计划 §3.2 查询集仅“10 条固定”；验收 §3 hit_rate 1.0、diversity 0.86——10 条对 217 段极易满分；层级 L0 192 / L1 13 / L2 11 / L3 1，compact 晋升几乎不发生；“embed 取最新”是 episode 层，段层未提。
- 建议：① 跑一次全量段重嵌入，抽 5 段比对摘要与源 episodes。② 立即启用每周 10 条真实查询，0 命中的落 `recall_misses.jsonl` 看长尾，不看均值。③ 够不够用由真实查询 hit 分布回答，不由固定集回答。
- 风险：P1。

**Q3 指标设计是否高分低质**
- 结论：会，三个机制叠加：调参与验收同源；hit_rate 饱和失去区分度；floor=0.05 把弱相关计入命中。
- 证据：引擎发展计划 §3.2 同一查询集既扫参又晋级；验收 §3 score 0.909 / hit_rate 1.0；晋级门禁“不低于现役 −3 分”在 10 条查询上，1 条翻转即 ±10 个百分点量级，−3 分在噪声内；score 权重未公开，0.909 不可复现。
- 建议：① 拆集：10 条固定 = tune-only；真实查询 = holdout，只在晋级评审时跑，写 `eval_report.json`。② 命中加裁判：top-k 过 Qwen 相关性判定（升级计划 §2.1 已有），hit_rate 与 judge_precision 双门禁。③ score 公式写进 `strategy.py` 常量并输出到报告。
- 风险：**P0**（策略晋级验收失效）。

**Q4 是否足以支撑“正式投入”**
- 结论：不足以。差三件：晋级/回滚从未演练（验收 §4：candidate/shadow 为空）；审批机制只有原则没有动作（“不做无人审批晋级”，但谁写 `training_model.json`、审批记录在哪未定义）；单进程 PID 16508 挂掉无人知。
- 证据：验收 §2 备份仅列 episodes db；`strategy_state.json`/`training_model.json`/`cycle_state.json` 不在备份内，而验收 §5 回滚恰恰依赖 strategy_state.json 的 history。
- 建议：① `promote` 子命令强制 `--approved-by`，追加 `promotions.jsonl`（time/adapter/eval_id/approver/sha256）。② 循环写 heartbeat，训练页规则：`cycle_state.json` mtime >26h → 红。③ backup manifest 增加上述三个配置文件与 sft 样本文件。④ 先拿现役 adapter 复制成 candidate 空转一遍完整晋级/回滚，链路通了再谈正式。
- 风险：P1。

**Q5 QLoRA 未覆盖的故障模式**
- 结论：预检只防“启动时显存不足”，防不了中途 OOM、抢卡、训练后状态残留。
- 证据：升级计划 §5 要求训练前 `ollama stop`，但训练页与 judge 共用同一 GPU（验收 §2 数据源含 `/api/ps`），无互斥；22:48 与 06:00 两轮并存，进程无锁；`episodes_count` 已错一次靠人工修。
- 建议：① `state/gpu.lock` 文件锁，训练与 judge 互斥，拿不到就写原因跳过。② 放行条件改为：`/api/ps` 为空 + nvidia-smi 快照写进 cycle log，不信瞬时预检数字。③ checkpoint + OOM 即中止本轮、候选标 OOM，不降质量强训。④ 训练结束钩子校验 `/api/ps`，judge 可用性预热一次。⑤ 每轮 `SELECT COUNT(*) FROM episodes` 重算，与 cycle_state 差 >1% 覆盖并告警。⑥ adapter 落盘即算 sha256 写 `candidates_manifest.jsonl`，回滚以 hash 为准。
- 风险：互斥与计数 P1，manifest P2。

**Q6 ZCode UI 操作风险**
- 结论：可控，前提是会话不带工具权限；否则只读纪律无法执行。
- 证据：审核请求纪律“只读”，但 ZCode 是 agent 型 UI，信任工作区即可执行命令，纪律只是提示词；验收 §4 弹窗 180 秒超时已发生、headless 401，说明自动化不稳，人工在环是必须。
- 建议：① 全新会话、不信任工作区、禁工具执行，只粘贴材料文本。② 额度弹窗保持人工点击，不做 UI 自动化点击。③ 通行证 A/B/C 显式只读 + 到期撤销，留授权记录。④ 审核产出落盘 `docs/2026-11-04_ZCode审核意见.md` + sha256，防复制截断。⑤ 提示词声明“审核方无磁盘访问权，仅依据材料”，防模型幻觉文件内容。
- 风险：会话权限 P1，其余 P2。

## 三、必须修复项（P0）

1. **dedup 合并口径补 outcome/subject 规则 + 两条不变量检查 + 重生成 `sft_success.jsonl`**（训练污染路径）。
2. **确认存在 dedup 前备份并移出 14 份滚动保留**；恢复演练必须含该备份。若已不存在，立即冻结一切破坏性库操作（不可回滚）。
3. **拆分 tune / holdout 查询集**，晋级只看 holdout（否则策略晋级验收失效）。

## 四、可选优化项（P1/P2）

- P1：GPU 文件锁；heartbeat；promote 审批落盘；段重嵌入与抽查；judge_precision 双门禁；ZCode 干净会话；episodes_count 每轮重推导。
- P2：三个配置文件入备份 manifest；adapter sha256 manifest；`recall_misses.jsonl` 长尾跟踪；sft 样本补时间戳/快照 id。

## 五、明确不同意的点

1. **“k=5/floor=0.05 评测最优”不成立**。指标饱和 + 调参验收同源，只能证明“能跑”，不能证明“最优”；且 dedup 后语料剧变（9,973 行合并、段 323→217），旧评测需在新语料重跑。
2. **“重复 0 = 无污染”不等价**。0 组只说明该 dedup_key 口径下无残留，不能证明口径本身无遗漏——这正是 Q1 的核心。
3. **"heldout 70%"存疑**。403 行 SFT 留 70% 验证，训练仅剩约 120 行，撑不起 −3 分门禁；若另有所指，须在训练页写明定义，否则该数字无意义。
4. **恢复演练验收“召回 10 条有出处”不充分**。出处 ≠ 正确；补抽样文本 hash 比对，计数守恒材料已有，hash 没有。
