# 发布推进状态单 · 2026-11-08

> 范围：computer-use-gate 的 90 天发布计划。
> 分工：第 3 阶段（60–90 天）交给 SuperAgent 试运行；0–30 天、30–60 天由本对话推进。

## 一句话

**代码能力不是当前瓶颈，打包和分发才是。**<br>
今天已经确认并修掉了一个“用户根本装不上”的硬阻塞：`pip install -e .` 之前会直接失败。

---

## 1. 今天确认的硬阻塞

### 1.1 `pip install` 直接失败

在干净临时 venv 里执行：

```powershell
python -m pip install -e F:\ZhuanZ\Documents\agent-ctl --no-deps
```

报错：

```text
setuptools.errors.InvalidConfigError:
License classifiers have been superseded by license expressions (see PEP 639).
Please remove:
  License :: OSI Approved :: Apache Software License
```

原因：

- `pyproject.toml` 同时写了 `license = "Apache-2.0"`（PEP 639 表达式）
- 又保留了旧式 `License :: OSI Approved :: Apache Software License` classifier
- 新版 setuptools 直接拒绝构建

这意味着：**任何尝试 `pip install` 的用户都会失败**，只能走 `install.ps1`。

### 1.2 即使装上，也没有 `agentctl` 命令

`pyproject.toml` 没有 `[project.scripts]`，所以轮子/可编辑安装不会生成 `agentctl.exe`。

### 1.3 `python -m agentctl` 不可用

`src/agentctl/` 下没有 `__main__.py`，所以模块方式启动失败。

### 1.4 三个名字不统一

| 位置 | 当前名字 |
|---|---|
| GitHub / Gitee 仓库 | `computer-use-gate` |
| Python 包名 | `agent-ctl` |
| 命令行 | `agentctl.cmd` / `agentctl` |

用户搜到的是一个名字，安装的是另一个名字，运行的是第三个名字。这会直接增加认知成本和安装失败率。

### 1.5 PyPI 上没有包

`https://pypi.org/pypi/computer-use-gate/json` 返回 404。<br>
当前只有 GitHub Release 的 `agentctl.zip`，没有 `pipx install` / `pip install` 入口。

### 1.6 Release 落后于代码

- 最新 Release：`v0.1.1`，2026-10-24
- 代码最后推送：2026-11-07
- 新用户下载到的是两周前的包

### 1.7 `requires-python` 与实际依赖不一致

`pyproject.toml` 写 `>=3.10`，但 `install.ps1` 把 Python 锁在 3.12，因为 vendor 里的 winrt wheel 是 `cp312`。<br>
用户如果在 3.10/3.11 上 `pip install`，可能装得上但运行失败。

---

## 2. 今天已经改了什么

### 2.1 备份

- `pyproject.toml.bak-20261108-before-packaging`
- `src/agentctl/__main__.py` 原本不存在，无覆盖风险

### 2.2 `pyproject.toml`

- 删除旧 License classifier：
  `"License :: OSI Approved :: Apache Software License"`
- 保留 `license = "Apache-2.0"`（PEP 639）
- 新增 console script：

```toml
[project.scripts]
agentctl = "agentctl.cli:main"
```

### 2.3 新增 `src/agentctl/__main__.py`

```python
from __future__ import annotations
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

---

## 3. 验证结果

在临时 venv（`--system-site-packages`）里执行：

```powershell
python -m pip install -e F:\ZhuanZ\Documents\agent-ctl --no-deps
```

结果：

```text
Successfully built agent-ctl
Successfully installed agent-ctl-0.1.1
```

然后验证：

| 检查 | 结果 |
|---|---|
| `Scripts\agentctl.exe` 是否存在 | **YES** |
| `agentctl --help` | 正常输出 CLI 帮助 |
| `python -m agentctl --help` | 正常输出 CLI 帮助 |
| `agentctl status` | 返回 JSON，`ok: true`，退出码 **0** |
| `python -m agentctl status` | 返回 JSON，`ok: true`，退出码 **0** |

结论：**可编辑安装、console script、模块入口这三条路已经打通。**

---

## 4. SuperAgent 第 3 阶段试运行结果

创建了 plan_only run：

- `sa-20261108-101531-f73d7a`
- 任务：第 3 阶段（10 个外部用户、5 条反馈、公开 trace、双社区发布）
- 模式：`plan_only`
- 状态：已停止（`stopped`）

实际生成的计划只有 3 步：

```text
ctl_status
ctl_windows
ctl_screen
```

它把整段运营任务当成“在当前桌面窗口里查一段文字”，**没有 web 调研、没有渠道分析、没有外联能力**。

结论：

> **SuperAgent 目前不能独立执行第 3 阶段。**<br>
> 它适合做“在本机桌面上观察/验证”的任务，不适合做社区调研、内容分发、用户外联。

第 3 阶段要么：

1. 给 SuperAgent 增加 web research / 内容草稿工具（需要开发）；
2. 或者由本对话/OpenCode 生成发布素材，SuperAgent 只做执行清单和复盘。

---

## 5. 90 天分工（当前版本）

### 0–30 天：能被装上、能被看懂（本对话）

| # | 工作 | 状态 |
|---|---|---|
| 1 | 修复 `pip install` / console script / `python -m` | **已完成** |
| 2 | 统一名字：仓库 / PyPI / CLI | 待决策 |
| 3 | 发布 PyPI 包或 wheel + zip | 待做 |
| 4 | 干净 Windows VM 安装测试 | 待做 |
| 5 | README 第一屏重写 | **已应用**（备份 `README.md.bak-20261108-before-first-screen`） |
| 6 | 60–90 秒 demo 视频/GIF | 分镜脚本已出，视频待录 |
| 7 | 20 应用 × 50 任务 benchmark 规格 | **已写**（`docs/benchmark-50-20261108.md`） |

### 30–60 天：能被验证、能被传播（本对话）

| # | 工作 | 状态 |
|---|---|---|
| 1 | 公开 benchmark 结果 | 待做 |
| 2 | Agent skill（Claude Code / Codex / OpenCode） | 待做 |
| 3 | 中文首发内容（掘金/知乎/B站/OSChina） | 待做 |
| 4 | 英文 README + 国际首发内容 | 待做 |
| 5 | 5 个外部试用者 | 待做 |
| 6 | 对比表（agent-desktop / AgentMouse / Open Interpreter） | 待做 |

### 60–90 天：10 个真实用户 + 双社区发布（SuperAgent 辅助，人工执行）

| # | 工作 | 负责 |
|---|---|---|
| 1 | 渠道清单 / 规则风险 | SuperAgent（需 web 工具） |
| 2 | 外联话术 / 发布草稿 | SuperAgent + 人工审 |
| 3 | 发布日历 / 指标跟踪 | SuperAgent |
| 4 | 真实用户邀请 / 发帖 / 回复 | **人工** |
| 5 | 反馈归档 / 复盘 | SuperAgent + 人工 |

---

## 6. 接下来 7 天

1. **统一名字**：建议 `computer-use-gate` 作为产品/仓库/PyPI 名，`agentctl` 作为 CLI，`agentctl` 作为 import 包。需要你拍板。
2. **发布 wheel + zip**：先本地构建，不急着上 PyPI；在干净 VM 上装一遍。
3. **README 第一屏**：把 demo GIF、安装命令、三句价值主张放到最上面。
4. **录 demo**：错误窗口被拦 → 授权 → 动作验证 → 哈希链 → 急停。
5. **写 50 任务 benchmark 规格**：先定应用和任务，不急着跑。
6. **中文首发文章**：先写“为什么 Windows 桌面 Agent 需要一道路闸”，不要先写“我又做了一个 Computer Use”。
7. **国际首发文章**：英文，定位 `Governance layer for computer-use agents`。

---

## 7. 止损条件

- 如果 30 天内还不能在干净 Windows VM 上 5 分钟装好：暂停功能开发，只修安装。
- 如果 demo 视频做出来后 100 个访问 < 10 次安装：修 README/安装，不要加功能。
- 如果 50 个任务 benchmark 的 wrong-target rate 不低于无闸基线：先修 grounding，不要发版。
- 如果中文首发 3 天 < 500 阅读：换标题/渠道，不要怀疑项目价值。
- 如果 SuperAgent 仍然没有 web 工具：第 3 阶段不要交给它，改用本对话生成素材。

---

## 8. 10:25 更新：v0.1.2 wheel 已构建，zip 被一致性闸门拦住

### 8.1 wheel 产物

```text
F:\ZhuanZ\Documents\agent-ctl\dist\v0.1.2\computer_use_gate-0.1.2-py3-none-any.whl
size:   616,726 bytes
sha256: C2EF3F4849EFEB5B1D4575B22845622D1D5364D092B6D4A575C43978670FE470
```

### 8.2 wheel 已修的第二层打包问题

第一次 wheel 装完后 `agentctl --list` 报：

```text
读契约失败: No such file or directory: ...\Lib\contract\tools.json
```

原因：`contract/tools.json` 在仓库根，不在 wheel 里。

修复：

- 契约复制进包：`src/agentctl/contract/tools.json`
- 新增同步脚本：`tools/sync_contract.py`
- `core.tool_list()` 增加 fallback：先找仓库根，找不到再用包内副本
- `pyproject.toml` 增加 `package-data: agentctl = ["contract/*.json"]`

复测：

```text
wheel 内 agentctl/contract/tools.json = 91,618 bytes
agentctl --list = 29 行，无 _error
agentctl status = ok: true，退出码 0
```

### 8.3 安装验证

| 路径 | 结果 |
|---|---|
| 临时 venv + wheel + `--no-deps` | 成功，`computer-use-gate 0.1.2` |
| `agentctl status` | JSON，退出码 0 |
| `python -m agentctl status` | JSON，退出码 0 |
| `pipx install <wheel>`（临时 PIPX_HOME） | 成功，生成 `agentctl.exe` |
| pipx 的 `agentctl status` | JSON，退出码 0 |

### 8.4 zip 为什么没打出来

`tools/pack_dist.py` 在发包前做 live/仓内产物/台账一致性校验，直接中止：

```text
[X] live 与仓内产物不一致 —— 中止发包
```

涉及文件：

- `act.py`
- `auth_popup.py`
- `gate.py`
- `guardian_policy.json`
- `perceive.py`
- `post_compat.json`
- `验动作.py`

脚本的立场是：live 是本机真在跑的那份，仓里看不出来但运行行为已经漂了；必须先把改动同步回真源，重新生成/同步 live 后再发。

**没有绕过这个闸门。** v0.1.2 先按 **wheel-only** 准备；`install.ps1` 的 zip 等 legacy 真源对齐后再发。

### 8.5 还没做

- PyPI 上传（需要账号/token）
- GitHub tag / push / Release（等用户最后确认）
- 干净 Windows VM 安装（当前是临时 venv + pipx，不是完整 VM）
- zip / install.ps1 发行包（被一致性闸门拦住）
- demo 视频录制（脚本已出）
