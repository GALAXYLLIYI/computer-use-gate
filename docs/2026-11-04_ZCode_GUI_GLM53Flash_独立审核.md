# ZCode GUI 独立审核（GLM-5.3-Flash）

> 时间：2026-11-04 10:49–11:00
> 通道：ZCode 桌面 GUI（任务 sess_<redacted>）
> 模型：GLM-5.3-Flash
> 说明：用户授权 agentctl 后，ZCode 窗口恢复并完成 GUI 内对话；本文件从 ZCode tasks-index.sqlite 的 searchable_text 原样导出。

# 独立审核意见（只读，含事件流实查）

**实查补充证据**（本次审核新取，非复述）：
- 训练闭环在事件流中的留痕止于 10-31（事件 2396/2400/2401）；**11-04 的 dedup 冻结、565 行重生成、smoke 拒收、晋级/回滚演练零留痕**（检索 dedup/smoke/sft_success/rollback 均无 11-04 命中）。
- 事件 2396：403 旧集血缘审计仅 229 可追溯；含 37 合成观测、32 非法答案、**17 条 subject=agent（研究日志冒充桌面动作）**；旧集建于 32.5MB 旧快照，库已涨至 87.8MB；源库无 task/project 列只能按 session 切；**target 100% 落在 obs 内 ⇒ 正样本只能测抄写**。
- 事件 2400：干净拒答素材实测仅 4 条；脏正样本确实拖累安全学习（脏集幻觉 28.6% vs 干净集 14.3%）。
- 事件 2401：DPO 审计曾抓出 3 条 prompt 与 heldout 重叠——prompt 泄漏检查有先例。

---

## 1. dedup 口径遗漏

有洞，五处：
- **时序键未定义**。“最新非空”按墙钟还是事件 id 排？墙钟可乱序。检查项：抽 20 组人工核对 outcome 是“终态”而非仅时间最大。
- **“非空”≠“有效”**。最新一条若是“待定/进行中”占位 outcome，会覆盖更早的确定结论。检查项：outcome 增加终态/进行中分级，进行中不参与竞选。
- **归一化口径未证实**。10,679→1,076 量级的合并 + 重复组 0 + 冲突 0，过于干净：要么键太严（近重复漏网），要么归一化静默合并。检查项：NFKC+trim+小写后重扫 222 段；embedding 相似 ≥0.92 二扫。
- **narrative/detail 不在合并策略与不变量里**。outcome 取新、narrative 来源不明 ⇒ “结果新、结论旧”仍可发生，且 subject/outcome/actor 不变量查不到它。检查项：20 组人工核对 narrative↔outcome 一致性。
- **provenance 继承未定义**。合并行若只留最新 evidence/raw_ref，被合并 episode 溯源断链。holdout provenance 0.88 的 12% 失败若集中在被合并段，即实锤。检查项：失败案例按“是否合并段”分组统计。

另两件便宜强校验：**dedup 复跑应 0 变更（幂等）**；**构造双 subject 样本组回放，验证拒绝逻辑真的会触发**（冲突文件行数也要人工看一眼，0 可能是没触发而非没冲突）。

## 2. 222 段够不够

**够运行，不够证明覆盖。** tune10+holdout10 下 hit_rate 1.0 的 Wilson 95% CI 是 [0.72, 1.0]，无统计意义。缺的检查：
- 死段普查：222 中多少从未进过任何评测/生产 top-5。
- floor 影响量化：recall@10 vs @5 差值；floor=0.05 近乎不设防，看分数分布确认它是否曾生效。
- 分套件检索召回（copy/decision/refusal/divert/safety 五套，2396 已建），不聚总。
- 索引新鲜度：consolidation 之后的新事件入没入索引（快照时间 vs 最新 episode id）。
- provenance 0.88 的 12% 逐条列名单（同第 1 条末项）。

## 3. 拆集不足，且有结构性问题

- n=10 单题翻转 ≈ ±0.1；tune 0.909 vs holdout 0.931 是噪声，holdout 反而更高已提示 tune 过拟合。
- 更深的洞（2396 实锤）：**只能按 session 切，且正样本 target 全在 obs 内 ⇒ 现在的 heldout 主要测抄写**。扩到 50 也只是把抄写测得更准。
- 扩法（直接给落点）：
  1. 复用 10-31 已建的 232 条五套集做检索评测底座，分层抽 tune50/holdout50，不要从零攒。
  2. holdout 按时间后切（最新 session），测漂移。
  3. 指标改 bootstrap 1000 次 95% CI 下界，不看点估计。
  4. 增设“必须不召回”负集，对接第 4 条的 negative 门。
  5. 565 行重生成集必须跑与 DPO 审计同款的 prompt-重叠检查（2401 先例）。

## 4. 门禁：这次没误杀，但机制双向不可信

- **本次拒收正确**：smoke 用的是已判死的 403 脏集（仅 229 可追溯+旧快照），44.4% 幻觉与脏数据假设一致（2400 交叉证据）。不是门禁的错，是数据的错。
- **但阈值在小样本上两头都会错**：
  - negative<5%：若负集是 refusal21，允许错误数=0（1/21=4.8% 即贴线）；若是 safety59，允许 2 条。真模型一条错就死。
  - divert<20%（66 条）：95% CI 半宽 ≈ ±9pp，真值 15% 的模型可测出 24%。
  - 阈值从未在“已知好模型”上标定。行动：先在现役 v4-1029 上跑全九指标，门禁改“不差于现役 − margin”，比绝对阈值抗误杀。
- 防误杀靠机制不靠放水：rejected/ 已存全指标（好）；补 run manifest 记 gate_config sha（拒收可复现）+ 数据修复后同 seed 同数据 sha 的复跑通道。

## 5. 残余 P0（逐条）

1. **留痕断链（已实锤）**：11-04 全链无事件流记录。行动：freeze sha、smoke 拒收、晋级、回滚各补一条 append-only 事件，半小时工作量。
2. **565 行血缘复核（最高优先）**：dedup 后重读库，17 条 subject=agent 冒充、37 合成、32 非法答案是否借重生成还魂？行动：对 565 行重跑 2396 的七项审计，diff 排除单。
3. **旧集防晋级是名字级还是 sha 级**：若只改目录名/标记文件，promote 脚本不认。行动：promote 加数据集 sha denylist；验证 `promote_candidate.py --dry-run` 指向归档 403 集必须拒绝。
4. **run manifest 缺失**：11-04 smoke 有没有 dataset sha / snapshot sha / seed？没有则一切指标不可复现。模板：{dataset_sha, snapshot_sha, seed, base_model, gate_config_sha, code_commit}，训前落盘。
5. **GPU 锁窗口**：卸载→复查→训练→评测是否同一锁作用域；Ollama keep_alive 是否置 0（否则任意 API 命中即重载回显存）。行动：训练窗内 `nvidia-smi --query-gpu=memory.used --format=csv -l 5` 落盘并记 peak。
6. **晋级并发防呆**：换装瞬间校验 candidate eval sha 与现役 adapter sha 一致 + 原子改名；现役在评测后被改动 ⇒ 拒绝晋级。
7. **回滚健康检查**：演练通的是文件换装；回滚后是否自动跑 mini-holdout + 索引重载？没有则回滚成功 ≠ 服务健康。

## 6. 下一步优先级

**P0**：
1. 565 行血缘复核（5-2）——它决定下一次训练的一切结论是否可信。
2. 11-04 补留痕（5-1）。
3. promote 加 sha denylist + run manifest（5-3/5-4）。

**P1**：
4. negative/divert 扩到 n≥100、门禁改 CI 下界、先跑现役基线定 margin。
5. 检索评测换到 232 条五套集底座 + 死段普查 + recall@10 对比。
6. dedup 幂等复跑 + 归一化近重复二扫 + provenance 失败归因。

**P2**：
7. 用 565 行干净集重训 smoke，验证 44.4% 确为脏数据所致——**必须在 P1-4 之后跑**，否则结果在小样本门禁下仍不可解释。
8. heldout 定义重构：降 copy 权重、升 decision/refusal/divert 权重（现在测的主要是抄写，2396 实锤）。

**一句话总结**：闭环的机械链路（锁、门禁、晋级/回滚）是通的；真正悬着的是三件事——11-04 没留痕、565 行没复核血缘、评测集太小导致所有数字（包括 holdout 0.931）都解释不了。先修证据链，再谈训练。
