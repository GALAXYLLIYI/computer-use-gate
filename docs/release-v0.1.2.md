# v0.1.2 发布准备单 · 2026-11-08

> 状态：**wheel 已构建并验证；本 Release 只发 wheel；zip 待 legacy 对齐后补。**
> 原因：zip 打包被 legacy 一致性闸门拦住；仓库工作区还有未提交的 build/deploy 改动。

## 1. 产物

```text
F:\ZhuanZ\Documents\agent-ctl\dist\v0.1.2\computer_use_gate-0.1.2-py3-none-any.whl
size:   616,726 bytes
sha256: C2EF3F4849EFEB5B1D4575B22845622D1D5364D092B6D4A575C43978670FE470
```

zip（`agentctl.zip`）**未生成**：`tools/pack_dist.py` 因 live 与仓内产物不一致而中止。

## 2. 本版改了什么

### 打包 / 安装

- 修复 PEP 639 License classifier 冲突：`pip install -e .` 不再失败。
- 新增 console script：`agentctl = "agentctl.cli:main"`。
- 新增 `src/agentctl/__main__.py`：`python -m agentctl` 可用。
- 包名统一为 `computer-use-gate`；CLI 保持 `agentctl`；import 包保持 `agentctl`。
- `requires-python` 收紧为 `>=3.12,<3.13`，与 `install.ps1` 的 cp312 vendor wheel 一致。
- 契约随包：`src/agentctl/contract/tools.json` + `tools/sync_contract.py`；
  `core.tool_list()` 在仓库根缺失时回退到包内副本。

### 文档

- README 第一屏改为“30 秒看懂 + 30 秒试一下”，增加英文入口和 demo 占位。
- 新增 `docs/demo-60s-script.md`：60 秒 demo 分镜。
- 新增 `docs/benchmark-50-20261108.md`：20 应用 / 50 任务 benchmark 规格。
- 新增 `docs/launch-status-20261108.md`：发布状态单与问题清单。

## 3. 已验证

| 路径 | 结果 |
|---|---|
| 临时 venv + wheel + `--no-deps` | 成功 |
| `agentctl status` | JSON，`ok: true`，退出码 0 |
| `python -m agentctl status` | JSON，`ok: true`，退出码 0 |
| `agentctl --list` | 29 行，无 `_error` |
| `pipx install <wheel>`（临时 PIPX_HOME） | 成功 |
| pipx 的 `agentctl status` | JSON，退出码 0 |
| wheel 内契约 | `agentctl/contract/tools.json`，91,618 bytes |

## 4. 未完成 / 阻塞

### 4.1 zip 被 legacy 一致性闸门拦住

`tools/pack_dist.py` 报：

```text
[X] live 与仓内产物不一致 —— 中止发包
```

涉及：

- `act.py`
- `auth_popup.py`
- `gate.py`
- `guardian_policy.json`
- `perceive.py`
- `post_compat.json`
- `验动作.py`

需要先把 live 改动同步回真源（`legacy_tools/_src/`）并重生/重同步 live，再打 zip。
**没有绕过闸门。**

### 4.2 仓库工作区未提交

当前还有用户侧未提交改动：

- `build/AgentCtl.spec`
- `contract/tools.json`
- `src/agentctl_main.py`

以及未跟踪的 `build_retina/`、`deploy/`、`dist_retina/` 等。发布 commit 需要确认是否纳入这些改动。

### 4.3 未做

- PyPI 上传（需要账号/token）
- 干净 Windows VM 安装（当前是临时 venv + pipx，不是完整 VM）
- demo 视频录制（脚本已出）
- `install.ps1` 的 zip 路径（等 legacy 对齐）

## 5. 下一步

1. 决定 v0.1.2 是 **wheel-only**，还是等 legacy 对齐后同时发 zip。
2. 确认 release commit 是否包含 `contract/tools.json`、`src/agentctl_main.py`、`build/AgentCtl.spec`。
3. 在干净 Windows VM 上跑 wheel + pipx + `agentctl status` + `--list`。
4. 上传 PyPI（需要账号/token）。
5. 录 demo，替换 README 占位。
