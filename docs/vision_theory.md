# 连续视觉的理论依据与评测口径

> 适用范围：`src/agentctl/retina.py`、`tools/vision_lab.py`、`tools/vision_cues.py`、`tools/vision_compare.py`
> 版本：2026-11-07 v1
> 目的：把「为什么这么判」写死，避免后续调参时凭感觉改阈值。

---

## 1. 一句话骨架

> **预测误差（变化检测）→ 事件边界（时间分割）→ 版面先验（空间分割）→ affordance（语义）→ 情境意识（决策）**

当前实现覆盖前两层和第三层的一半；第四层只有 OCR 的尝试（失败后改用版面统计），第五层未做。

---

## 2. 三层理论

### 2.1 感知层：预测误差与变化检测

**预测编码（predictive coding）**：Rao & Ballard (1999) 提出，视觉皮层不断用上层预测下层的输入，真正向上传递的是**预测误差**，不是原始像素。

工程对应：

```
ratio = 变化像素数 / 总像素数        # 单帧预测误差
bbox  = 变化像素的外接矩形            # 误差发生在哪
burst = 最近 1 秒内 ratio ≥ 0.002 的帧数   # 误差的持续性
```

这个映射不是修辞。`framecache.diff_images` 做的就是「上一帧作为预测，当前帧作为输入，算残差」，和预测编码的形式完全一致。

**推论**：阈值不该是常数。预测误差的基线随画面纹理、压缩噪声、DPI 变化，固定阈值换一台机器就会漂。理论上应该用在线估计（见 2.2 的 BOCPD，或简单的滑动分位数）。

### 2.2 时间层：事件分割与变化点检测

**事件分割理论（Event Segmentation Theory, EST）**：Zacks et al. (2007) 认为人把连续经验切成事件，切点出现在**预测误差突增**的地方；事件内部则维持一个稳定的情境模型。

这解释了我们为什么要区分「持续变化」和「孤立大跳」：

| 现象 | EST 解释 | 我们的标签 |
|---|---|---|
| 连续多帧在变 | 同一事件内的运动 | `video_playing` |
| 孤立一次大跳后静止 | 事件边界 | `slide_flip` |
| 长时间无变化 | 事件内状态维持 | `slide_static` / `video_paused` |

**贝叶斯在线变点检测（BOCPD）**：Adams & MacKay (2007)。它维护「当前段的长度」后验，观测到突变时后验迅速偏向「新段开始」。这是固定阈值的原则性替代：

```
P(变点 | 观测序列) ∝ P(观测 | 新段) · P(变点先验)
```

落地方式：把 `ratio` 序列喂给一个简化版 BOCPD（高斯似然 + 常数风险率），输出的变点概率替代 `ratio >= 0.10 and burst <= 2` 这条手写规则。

**镜头边界检测**：Zhang et al. (1993) 的 twin comparison、Lefèvre et al. (2003) 的综述，处理的是同一个问题——把「镜头切换」和「画面内运动」分开。经典结论是**单帧阈值不可靠，必须用时间窗**。我们在 2026-11-07 的实测里重新踩了一遍这个坑（单帧 0.15 阈值把视频镜头切换误判成翻页），然后被 `burst` 修正——与文献结论一致。

### 2.3 空间层：显著性与版面先验

**显著性模型**：Itti, Koch & Niebur (1998)；综述见 Borji & Itti (2013)。人眼不是均匀处理全屏，而是被颜色对比、边缘密度、运动区域吸引。

我们的两个空间设计对应它：

- **变化热区（hot region）**：变化 bbox 的中位数，等价于「这个窗口里哪个区域承载运动」。实测在课程页上稳定落在播放器矩形 `(134,221,894,666)`。
- **内容画布（CANVAS）**：人为排除左侧图标栏与右侧目录，避免侧栏动画污染统计。这是**版面先验**，不是显著性——但它解决的是同一个问题：把注意力预算花在信息区。

**双流假设（two-stream）**：Simonyan & Zisserman (2014) 指出外观（appearance）和运动（motion）是两条独立通路。我们的「版面统计（白底占比）+ 时间窗（burst）」正是这个划分的轻量版：白底是外观，burst 是运动，两者互补而非互斥。

这也是为什么「视频里放 PPT」不会误判：外观说「像课件」，运动说「在播」，最终按运动优先。

### 2.4 语义层：affordance 与 GUI grounding

**affordance**：Gibson (1979)。人看到的不是颜色块，而是「能做什么」——播放器上的暂停键、进度条、页码、缩略图条，都是可供性，不是像素。

**GUI grounding**：近年的 GUI Agent 研究（Screen2Vec, Li et al. 2021；Ferret-UI, You et al. 2024；UGround, Gou et al. 2024；OS-Atlas, Wu et al. 2024）有一个共同结论：

> 纯像素不够（语义弱），纯 DOM 也不够（用户看到的和 DOM 不一致，且 Canvas/视频不可见），要做**混合感知**。

我们的三通道（retina 像素 / CDP DOM / Windows OCR）就是这个结论的工程版。2026-11-07 的 OCR 实测（1276px 宽窗口上认不出时间码、页码只认出 `7 /`）说明：**混合不是简单叠加，要按可靠性分级**。当前分级：

| 通道 | 可靠性 | 用途 |
|---|---|---|
| CDP DOM | 高（页面结构明确时） | 精确定位、状态查询 |
| 版面统计 | 中高（同版式内稳定） | 区分课件/视频 |
| OCR | 低（小字号深色底） | 只做抽样记录 |

### 2.5 决策层：情境意识

**Endsley (1995) 的三级模型**：

| 级别 | 内容 | 我们的现状 |
|---|---|---|
| Level 1 Perception | 屏幕上有什么 | 有（像素、DOM、OCR） |
| Level 2 Comprehension | 这些意味着什么 | 部分（语义标签） |
| Level 3 Projection | 接下来会怎样 | 无 |

Level 3 才是 Agent 真正需要的：视频还剩多久、翻页后进入哪一节、当前状态是否异常。它要求把「当前帧」升级成「状态机 + 时间预算」，这是下一阶段的目标。

**感知—行动循环**：OODA（观察—判断—决策—行动）在这里的具体含义是：retina 负责 Observe，vision_lab 负责 Orient，策略层负责 Decide，act/click 负责 Act。当前四段是断开的（采样完才出报告），要变成闭环必须支持流式输出。

---

## 3. 判据的数学形式

设第 `i` 帧的变化率为 `r_i`，变化区为 `B_i`，窗口 `W = 5`（5fps 下 1 秒）：

```
burst_i = |{ j ∈ [i-W+1, i] : r_j ≥ 0.002 }|

video_playing  ⇔ burst_i ≥ 3 ∧ r_i ≥ 0.002
slide_flip     ⇔ r_i ≥ 0.10 ∧ burst_i ≤ 2
ui_change      ⇔ r_i ≥ 0.002 ∧ ¬video_playing ∧ ¬slide_flip
static         ⇔ r_i < 0.002
```

静止时的版面分支，设内容区白底占比 `w`、边缘密度 `e`：

```
slide_static ⇔ static ∧ w > 0.32 ∧ e ≥ 0.012
blank_page   ⇔ static ∧ w > 0.32 ∧ e < 0.012
video_paused ⇔ static ∧ w ≤ 0.32 ∧ 连续静止帧 ≥ 10
video_idle   ⇔ static ∧ w ≤ 0.32 ∧ 连续静止帧 < 10
```

**阈值来源**（2026-11-07 实测，单课程单窗口）：

| 参数 | 取值 | 依据 |
|---|---:|---|
| 单帧有变化 | 0.002 | 视频播放时 ratio 的 p1 附近；低于此多为压缩噪声 |
| 大跳 | 0.10 | 视频镜头切换下界 0.15，翻页上界 0.43；取中间偏下 |
| 白底阈值 | 0.32 | 课件 p1 0.391、p50 0.443；视频 p99 0.21；取 0.32 使两侧余量约 0.07 / 0.11 |
| 边缘空白 | 0.012 | 待校准（当前样本未触发） |
| 静止判定 | 10 帧 | 2 秒，覆盖翻页动画与缓冲 |

> ⚠ 这些数字只在一个课程、一种窗口尺寸上验证过。换环境必须重标，不能直接复制。

---

## 4. 评测口径

没有评测的阈值只是经验值。固定四个指标：

### 4.1 事件边界 F1

- 正类：真实翻页/切换点（人工标注，精确到 0.2s）
- 匹配规则：预测点与真实点距离 ≤ 1 帧（200ms）算命中
- 报 Precision / Recall / F1

### 4.2 逐帧状态准确率 + 混淆矩阵

- 标签集合见第 3 节
- 必须报**每类**的 P/R，不能只报总体准确率（`slide_static` 占比 90% 时，全判课件也有 90% 准确率，毫无意义）

### 4.3 误报率/小时

长时间挂机场景的核心指标。定义：单位时间内 `slide_flip` 或 `ui_change` 的误触发次数。

### 4.4 端到端延迟

画面变化 → 标签输出。报 P50 / P95，不报均值。

### 4.5 阈值选择：信号检测论

Green & Swets (1966)。把「翻页」当正类，扫阈值画 ROC，用 **d′** 衡量可分性，用 **EER** 或业务代价选工作点。当前样本量（9 个翻页点）不足以画曲线，先记录方法，样本够了再补。

### 4.6 分层抽样要求

至少覆盖四层，否则阈值必然过拟合：

1. 不同课程（视频为主 / 课件为主 / 混合）
2. 不同分辨率与缩放（100% / 125% / 150% DPI）
3. 浅色 / 深色主题
4. 不同浏览器（Edge / Chrome）与不同页面实现

---

## 5. 采样参数的理论依据

**Nyquist 采样定理**：要无失真还原一个事件，采样率必须高于其最高频率分量的两倍。

翻页动画约 200–400ms → 主要频率 2.5–5Hz → 采样率至少要 5–10fps。当前 5fps 处在下限：

- 对翻页、切换够用（一次动画覆盖 1–2 帧）
- 对 hover、tooltip、光标级变化不够（<100ms 的事件会整段丢失）

这也是为什么 `ui_change` 会混入光标移动——5fps 下光标是「闪烁的稀疏采样」，看起来像局部变化。

若要做精细交互感知，按理论应升到 10–15fps，代价是 JPEG 编码与内存翻倍（5fps/30s 环约 15MB，10fps 约 30MB）。

---

## 6. 已知局限与理论解释

| 现象 | 理论解释 | 处理 |
|---|---|---|
| 窗口被完全遮挡时画面冻结 | 浏览器合成器在不可见时停止重绘（不是我们的 bug） | 结合窗口可见性判断，不能把冻结当静止 |
| `video_paused` 误包含「讲师不动」 | 像素层面「暂停」与「静止画面」不可分；需要 affordance（按钮状态） | 读播放器控件或 DOM |
| 翻页动画被切成多帧 | 事件边界本身是渐变的，EST 也承认边界有宽度 | 允许 ±1 帧容差 |
| OCR 认不出小字号 | 字形高度低于 OCR 引擎的下限（约 12–14px @96DPI） | 降级为抽样通道，不作为判据 |
| 单课程阈值 | 分层抽样缺失 | 见 4.6 |

**变化盲视（change blindness）**：Simons & Rensink (2005)。人眼对未被注意的变化几乎无感。这反过来支持「机器连续视觉」的价值：Agent 不应该只在被问到时截一张图，而应该持续维护状态。这也是 retina 存在的理论理由。

---

## 7. 路线图

| 阶段 | 内容 | 理论依据 |
|---|---|---|
| v5（当前） | 时间窗 + 版面统计，批量采样出标签 | EST + 双流 |
| v6 | 阈值自适应（滑动分位数或 BOCPD） | 预测编码 + 变点检测 |
| v7 | 流式输出（每秒一行状态），接决策循环 | OODA / 情境意识 |
| v8 | affordance 识别（播放器控件、页码、目录） | Gibson + GUI grounding |
| v9 | Level 3 预测（剩余时长、下一节） | Endsley 三级模型 |

每一阶段都必须先补评测（第 4 节），否则无法判断升级是否真的变好。

### 2026-11-07 实测记录

- **白底阈值 0.40 → 0.32**：某课件页实测 white=0.391（版面比通常更暗），按 0.40 会误判成视频；视频上界仍是 0.21，0.32 两侧余量约 0.07 / 0.11。
- **UIA 通道不可用**：`ctl_find` 在该网页上扫到 1188 个节点，但名字全为空；查「播放」「暂停」「目录」「高清」全部 0 命中。原因是 Chromium 的惰性无障碍树没有激活。⇒ affordance 识别（v8）只能走 CDP 或像素模板，在没有开调试端口的浏览器上做不了。
- **状态去抖**：新状态需连续 5 帧（1 秒）才生效，消除了阈值边缘的来回跳（实测把 30 秒内的抖动从十余次压到 2 次）。
- **v5.1 合并静止类**：5 分钟样本（1153 帧）里发现两类反例——
  彩色课件（大块黄/蓝/橙）白底占比只有 0.39，会被白底判据判成视频；
  视频里播放课件时，版面特征和真课件几乎一样，只有运动能区分。
  ⇒ 像素层无法可靠区分「视频暂停」和「课件停留」，两者合并为 `static_content`，
  白底占比降级为 `hint`（`slide_like` / `video_like` / `blank_like`），不再当标签。
  要恢复细分，必须拿到播放器状态（CDP 或控件识别），这正是 v8 的任务。
- **v8 已打通（CDP）**：`tools/vision_cdp.py` 直接读 `video.paused`。
  实测：播放中 `paused=false`、`currentTime` 从 53.3 推进到 73.7（时长 854.5s），
  输出 `video_playing`；手动暂停后 `paused=true`、`currentTime` 停在 93.3，
  输出 `video_paused`（conf 0.99）。同一时刻像素层给的是 `static_content` ——
  正好证明「CDP 覆盖像素」这一步是必要的，而不是可选优化。
  同一通道还读出了当前小节（`li.activeNode` → `1.1.6 内部控制目标及其设定`）
  和播放进度；课件页码（`19/54`）走叶子节点正则，仅在课件模式下出现。
- **v9 规则可测（2026-11-07 深夜）**：判定逻辑从脚本里抽到 `tools/vision_rules.py`，
  `pixel_label` / `apply_cdp` / `Stabilizer` 三个纯函数；`tests/test_vision_rules.py`
  14 条判据全绿（含阈值边界、CDP 覆盖、去抖计数）。`vision_stream.py` 已改为调用该模块，
  不再保留第二份 if-else。新增 `tools/vision_eval_live.py`：用 `cdp.paused` 当真值，
  直接给出「纯像素 vs CDP 覆盖」两条准确率，不需要人工标注。
- **环境阻塞（同一晚实测）**：会话内的 AgentCtl MCP 进程在 23:36 起报
  `PermissionError: gate.lock` / `unable to open database file`，同一台机器上
  `AgentCtl.exe status` 正常 ⇒ 是该 MCP 进程的令牌/ACL 问题（`_auth` 目录 ACL 里有
  `CodexSandboxUsers`），不是数据库损坏。SuperAgent 的独立子进程不受影响：
  run `sa-20261107-233812-26c17d` 的 `ctl_status` 步骤为绿，第二步因 A 级通行证
  15:52 到期而按设计停止（`on_fail=stop`）。

---

## 8. 参考文献

1. Adams, R. P., & MacKay, D. J. C. (2007). Bayesian online changepoint detection. *arXiv:0710.3742*.
2. Borji, A., & Itti, L. (2013). State-of-the-art in visual attention modeling. *IEEE TPAMI*, 35(1), 185–207.
3. Deng, X., et al. (2023). Mind2Web: Towards a generalist agent for the web. *NeurIPS*.
4. Endsley, M. R. (1995). Toward a theory of situation awareness in dynamic systems. *Human Factors*, 37(1), 32–64.
5. Gibson, J. J. (1979). *The Ecological Approach to Visual Perception*. Houghton Mifflin.
6. Gou, Z., et al. (2024). Navigating the digital world as humans do: Universal visual grounding for GUI agents (UGround). *arXiv:2410.05243*.
7. Green, D. M., & Swets, J. A. (1966). *Signal Detection Theory and Psychophysics*. Wiley.
8. Itti, L., Koch, C., & Niebur, E. (1998). A model of saliency-based visual attention for rapid scene analysis. *IEEE TPAMI*, 20(11), 1254–1259.
9. Lefèvre, S., Holler, J., & Vincent, N. (2003). A review of real-time segmentation of uncompressed video sequences for content-based search and retrieval. *Real-Time Imaging*, 9(1), 73–98.
10. Li, T. J.-J., et al. (2021). Screen2Vec: Semantic embedding of GUI screens and GUI components. *CHI 2021*.
11. Nyquist, H. (1928). Certain topics in telegraph transmission theory. *Transactions of the AIEE*, 47(2), 617–644.
12. Rao, R. P. N., & Ballard, D. H. (1999). Predictive coding in the visual cortex: a functional interpretation of some extra-classical receptive-field effects. *Nature Neuroscience*, 2(1), 79–87.
13. Simons, D. J., & Rensink, R. A. (2005). Change blindness: Past, present, and future. *Trends in Cognitive Sciences*, 9(1), 16–20.
14. Simonyan, K., & Zisserman, A. (2014). Two-stream convolutional networks for action recognition in videos. *NeurIPS*.
15. Wu, Z., et al. (2024). OS-Atlas: A foundation action model for generalist GUI agents. *arXiv:2410.23090*.
16. You, K., et al. (2024). Ferret-UI: Grounded mobile UI understanding with multimodal LLMs. *arXiv:2404.05719*.
17. Zacks, J. M., Speer, N. K., Swallow, K. M., Braver, T. S., & Reynolds, J. R. (2007). Event perception: A mind–brain perspective. *Psychological Bulletin*, 133(2), 273–293.
18. Zhang, H., Kankanhalli, A., & Smoliar, S. W. (1993). Automatic partitioning of full-motion video. *Multimedia Systems*, 1(1), 10–28.

---

## 9. 术语表

| 术语 | 含义 |
|---|---|
| 预测误差 | 当前帧与上一帧的差异比例（ratio） |
| 事件边界 | 画面发生结构性变化的时刻（翻页、切章节、弹窗） |
| 热区 | 窗口内持续承载变化的矩形区域 |
| 版面先验 | 对「信息区在哪、侧栏在哪」的先验假设 |
| affordance | 界面上可执行的动作入口（按钮、链接、播放器控件） |
| 双流 | 外观通道 + 运动通道，分别判断后融合 |
| BOCPD | 贝叶斯在线变点检测，自适应的事件边界算法 |
| d′ | 信号检测论中的可分性指标 |
