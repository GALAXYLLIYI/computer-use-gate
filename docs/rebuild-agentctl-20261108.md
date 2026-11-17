# 重建 AgentCtl.exe（verify 修复）· 2026-11-08

## 为什么

冻结版 `AgentCtl.exe` 里 `sys.executable` 不是 `python.exe`，旧 `_cl_run` 把
`verify_expect` 的独立验证跑成了 `AgentCtl.exe -X utf8 验动作.py check ...`，
动作已经 `met` 却返回 `unknown`。源码已在 `e3bab1a` 修复：

- 冻结时走 `AgentCtl.exe legacy <script>`
- 非冻结时继续走 `python.exe -X utf8 <script>`
- 回归：`tests/检验_verify_frozen_cmd.py`

## 构建

```powershell
cd <仓根>
python -X utf8 -m PyInstaller build\AgentCtl.spec `
  --noconfirm --clean `
  --distpath dist\v0.1.2-exe `
  --workpath build\pyi-v0.1.2b
```

`build/AgentCtl.spec` 已显式排除非控制链路的重依赖：
`torch / torchvision / torchaudio / sentence_transformers / transformers /
datasets / accelerate / pytest / IPython / jupyter / notebook / tensorboard`。
不排除时 PyInstaller 会把 torch 全家收进来，构建时间和体积都会失控。

产物：

```text
dist\v0.1.2-exe\AgentCtl\AgentCtl.exe     33.7 MB
dist\v0.1.2-exe\AgentCtl\_internal\       约 237 MB（整个目录）
```

## ⚠ 关键坑：Low 完整性标签

`F:` 上的构建目录带有 **Low Mandatory Level** 完整性标签（`icacls` 可见）。
从该目录直接运行 `AgentCtl.exe` 会以 Low 完整性启动，表现为：

- `tempfile.gettempdir()` 报 `No usable temporary directory`
- `uiautomation` / `comtypes.client` 导入失败
- 写 `%TEMP%`、`%LOCALAPPDATA%`、工作目录全部 `PermissionError`

**不是构建坏了，是运行路径的完整性标签问题。**
把产物复制到 `C:` 的普通目录（安装目录）后，文件继承目标目录的 Medium
完整性，一切正常。

验证：

```powershell
icacls <exe> | Select-String 'Mandatory'
# 不应出现 Low Mandatory Level
```

## 安装前预演（不要直接覆盖）

先把新产物复制到 `C:` 的临时目录或 staging 目录，再跑一遍：

```powershell
$stage = "$env:LOCALAPPDATA\Programs\AgentCtl-fixed.new-20261108"
$src   = "<仓根>\dist\v0.1.2-exe\AgentCtl"
robocopy $src $stage /E /COPY:DAT /R:1 /W:1
robocopy "$env:LOCALAPPDATA\Programs\AgentCtl-fixed\_internal\legacy_tools" `
         "$stage\_internal\legacy_tools" /E /COPY:DAT /R:1 /W:1
Copy-Item "$env:LOCALAPPDATA\Programs\AgentCtl-fixed\agentctl-mcp.cmd" $stage -Force
Copy-Item "$env:LOCALAPPDATA\Programs\AgentCtl-fixed\mcp_hidden.exe" $stage -Force
```

测试：

```powershell
& "$stage\AgentCtl.exe" status
& "$stage\AgentCtl.exe" legacy "$stage\_internal\legacy_tools\验动作.py" check --help
& "$stage\AgentCtl.exe" selftest
```

期望：`status` 的 `ok=true`；`legacy` 打印 `验动作.py` 的 usage 且退出码 0；
`selftest` 通过。

## 原子换位（本次实际用法）

旧安装里有两处 `work`，**都必须保留**：

- `_internal\work\`：timeline / verify 快照 / `_actions`（实际运行数据）
- `work\`：memory（episodes.db）

另外保留：

- `_internal\legacy_tools\`（41 个老脚本；新 PyInstaller 产物默认不带）
- `agentctl-mcp.cmd`、`mcp_hidden.exe`

步骤：

1. 停掉安装目录下的 `AgentCtl.exe mcp` 和 `mcp_hidden.exe`；
2. 把旧目录整体改名为
   `%LOCALAPPDATA%\Programs\AgentCtl-fixed.bak-20261108-before-verify-fix`；
3. 把 staging 目录改名为 `AgentCtl-fixed`；
4. 从备份目录把 `_internal\work` 和 `work` 复制回新目录；
5. 立即跑 `status` / `legacy` / `selftest`，失败则把备份目录换回来。

换位脚本模板见本次临时脚本 `swap_agentctl.ps1`（未入库）；核心是
`Move-Item` 两次 + `robocopy` 恢复 work。

## 验收（本次全部通过）

```text
F1 冻结 CLI             通过   status ok=true
F2 冻结 HTTP            通过   /v1/health 200
F3 冻结 MCP stdio       通过   tools/list 29 个，tools/call 带 structuredContent
F4 冻结后三态同源        通过   HTTP / MCP / CLI 逐字段一致
F5 exe 当解释器          通过   legacy perceive.py rc=9（未授权，正确行为）
F6 冻结自检三项          通过
```

另外单独验证：

- `AgentCtl.exe status` 显示
  `legacy_home=...\_internal\legacy_tools`、`legacy_layer=meipass`、
  `service.frozen=true`、`integrity=Medium`
- 在冻结 exe 内跑 `core._cl_cmd("x.py", ["check"])` 返回
  `[..., "legacy", "x.py", "check"]`，确认 verify 修复已进包
- `uiautomation / comtypes.client / win32gui / winrt OCR / windows_capture`
  全部可 import
- timeline `head_event_id` 保留（换位前 61）

## 体积与可选依赖说明

旧安装约 847 MB，包含 torch / transformers / tokenizers / sklearn / openai /
fastapi 等；新构建约 237 MB，只保留控制链路依赖。

当前记忆库 `work\memory\episodes.db` 的
`meta['embedder'] = 'hash-ngram-zh-v1'`，不依赖 BGE，所以本次排除 torch
不影响现有记忆检索。若以后要在这份冻结 exe 里用
`BgeEmbedder`，需要把 `sentence_transformers / transformers / torch`
重新收进包，或改用 wheel / 系统 Python 跑记忆 CLI。

## 回滚

```powershell
$inst = "$env:LOCALAPPDATA\Programs\AgentCtl-fixed"
$bak  = "$inst.bak-20261108-before-verify-fix"

# 停新进程
Get-CimInstance Win32_Process |
  Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($inst + '\') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Move-Item $inst "$inst.failed-20261108"
Move-Item $bak $inst
```

## 注意

- 不要在替换期间运行 `tools/pack_dist.py`；它仍会被 live/仓内一致性闸门拦住。
- 不要让 `install.ps1` 覆盖当前安装；这次是替换冻结 exe，不是重装。
- 替换后 OpenCode / ZCode / DeepSeek Harness 的 MCP 会短暂重连；
  必要时 Reload Window。
- `AgentCtl.exe` 带 Low 完整性标签时不要直接在 `F:` 上跑验收；
  先复制到 `C:`。
