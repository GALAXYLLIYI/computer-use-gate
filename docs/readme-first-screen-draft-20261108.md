# README 第一屏草案 · 2026-11-08

> 目标：陌生人打开仓库 10 秒内回答 5 个问题：
> 1. 这是什么？
> 2. 解决什么痛？
> 3. 凭什么信？
> 4. 怎么试？
> 5. 有什么限制？

当前 README 的问题不是内容少，是**第一屏信息密度太高、没有视觉证明、安装入口偏重**。下面是替换草案，先不改正式 README。

---

## 中文第一屏（草案）

```markdown
# computer-use-gate

**Windows 桌面 Agent 的安全闸。**
AI 不点头不动手；点错能拦；动完能验；事后能回放。

<!-- TODO: 60 秒 demo GIF，放在这里 -->
![60 秒演示](assets/demo-60s.gif)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![Platform](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6)
![GPU](https://img.shields.io/badge/GPU-不需要-brightgreen)
![MCP](https://img.shields.io/badge/MCP-stdio%20%7C%20HTTP-8A2BE2)

**给谁用**：在 Windows 上让 AI 操作桌面的开发者、研究者、自动化团队。<br>
**不做什么**：不做无人值守批量点击，不绕过验证码/风控，不支援 Linux/macOS。

### 30 秒看懂

- **默认拒绝**：装完什么都不动；你在屏幕弹窗点“允许”才放行，一张通行证 30 分钟或 60 个动作。
- **五条视觉通道**：先读 Windows UI Automation，再 OCR，再 CDP，再图标反查；视觉模型默认关闭。
- **动作后验证**：截图变了才算成功；画面没变/没测出来都不算成功。
- **证据链**：前后截图 + 哈希链日志 + 可回放视频；`Ctrl+Alt+Home` 一键全停。

### 30 秒试一下

> 当前版本（v0.1.x）需要 Windows 10/11 x64 + Python 3.12 + git：

```powershell
git clone https://gitee.com/GALAXYLIYI/computer-use-gate
cd computer-use-gate
pwsh -File .\install.ps1
agentctl status
```

> PyPI / `pipx` 安装正在准备中；发布后这里会改成一条命令。

### 它到底解决什么

> 别的方案让 Agent **能动手**；computer-use-gate 让 Agent **动手之前先过闸，动完手有证据，出事能一键停**。

[为什么不是又一个 Computer Use →](#为什么不是又一个-computer-use)
```

---

## 英文第一屏（草案）

```markdown
# computer-use-gate

**A safety gate for Windows desktop agents.**
The agent does nothing until you allow it. Wrong-target actions are blocked. Every action is verified and replayable.

<!-- TODO: 60s demo GIF -->
![60s demo](assets/demo-60s.gif)

**For**: developers and teams running AI agents on their own Windows desktops.<br>
**Not for**: unattended bulk clicking, CAPTCHA/risk-control bypass, Linux/macOS.

### What you get

- **Default-deny**: nothing moves until you click Allow. A pass lasts 30 minutes or 60 actions.
- **Layered perception**: UI Automation → Windows OCR → CDP → icon matching; a VLM is a default-off last resort.
- **Post-action verification**: the screen must change; “no change” and “unobservable” are not success.
- **Evidence chain**: before/after screenshots, hash-chained log, replay video, one-key stop (`Ctrl+Alt+Home`).

### Try it in 30 seconds

> v0.1.x requires Windows 10/11 x64 + Python 3.12 + git.

```powershell
git clone https://github.com/GALAXYLLIYI/computer-use-gate
cd computer-use-gate
pwsh -File .\install.ps1
agentctl status
```

> PyPI / `pipx` install is in progress; this section will become one command.

### Why not another Computer Use?

> Others make the agent **able** to act. computer-use-gate makes the action **governed, verified, and replayable**.
```

---

## 30 秒 demo 脚本

按这个顺序录，不要加旁白以外的解释：

1. **错误窗口**：Agent 想点“保存”，但目标窗口不是当前窗口 → 闸门拒绝，屏幕提示“目标窗口不匹配”。
2. **授权**：弹出授权窗口，人手点“允许”。
3. **正确动作**：Agent 点中“保存”，画面变化。
4. **验证**：显示三态判词“生效”，前后截图并排。
5. **回放**：打开时间线，展示哈希链和回放视频。
6. **急停**：按 `Ctrl+Alt+Home`，屏幕边框熄灭，所有动作停止。

目标：**60–90 秒，无剪辑造假，真实窗口，真实拒绝。**

---

## 第一屏验收标准

一个没听过这个项目的人，打开 README 后 10 秒内能回答：

- [ ] 这是 Windows 桌面 Agent 的安全闸，不是又一个通用 Computer Use。
- [ ] 它默认拒绝，需要本人授权。
- [ ] 它会验证动作是否生效，不是“发出去就算成功”。
- [ ] 它有截图、哈希链、回放和急停。
- [ ] 它不需要显卡。
- [ ] 它现在需要 Python 3.12 + git，安装还不是一条命令。
- [ ] 它不适合无人值守批量点击。

如果任何一个答案是“没看到”，第一屏就还没写完。

---

## 需要的素材

| 素材 | 状态 | 说明 |
|---|---|---|
| 60 秒 demo GIF | 待录 | 放第一屏，不超过 5 MB |
| 架构图 | 待做 | 五条视觉通道 + 五道闸，一张图 |
| 前后对比截图 | 待做 | 拒绝 / 放行 / 验证三张 |
| benchmark 表 | 待做 | 50 任务，wrong-target / unobservable / latency |
| 英文 README | 草案已出 | 需要完整版，不是 TL;DR |
| Release 更新 | 待做 | v0.1.2，包含最新代码和校验和 |
| PyPI / pipx | 待做 | 打包修复已完成，发布待做 |

---

## 第一屏不要放什么

- 不要放 26KB 的完整架构解释；放到后面。
- 不要放五条通道的全部实测数字；第一屏只留一句“先问 Windows，再看像素”。
- 不要放完整对比表；第一屏只留一句“别人让 Agent 能动手，我们让动作可控、可验、可回放”。
- 不要放“实验性 0.x”作为第一行；放在安装段之后，用一句“0.x 实验版，接口会变”即可。
- 不要放“点个 Star”作为主要 CTA；先让用户看到 demo 和安装命令。
