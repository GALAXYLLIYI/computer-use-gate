# 连续视觉 L0-lite 原型（2026-11-04）

> 状态：可运行的独立 daemon + 文件查询原型，**未接 MCP core、未接 VLM/OCR**。
> 架构评审：Magpie 网关 → `minimax-code/MiniMax-M3`（2026-11-04）。

## 1. 做了什么

| 模块 | 实现 |
|---|---|
| M1 捕获 | 默认 5fps，指定 hwnd 客户区；抓不到记 `last_error`，不伪造帧 |
| M2 环形缓冲 | 最近 30 秒，内存中只存降采样 JPEG；不落盘全帧 |
| M4 稳定性门 | 复用 `framecache.diff_images`；输出 `change` / `stable` / `blank` |
| M5 事件流 | `events.jsonl` 追加，只存结构化字段，不存图 |
| 查询 | `ctl_retina_status` / `ctl_retina_changes` / `ctl_retina_snapshot`（MCP）+ CLI |
| 隐私 | 启动要求 A 级通行证；敏感标题 fail-closed；单窗口；无全屏默认 |
| 运维 | 单实例 pid 检查；`stop.request` 优雅停止；事件文件 10MB 轮转；state 原子写 |

## 2. 文件

```text
src/agentctl/retina.py       # 配置、环形缓冲、稳定门、daemon、CLI
tests/test_retina.py         # 7 个离线测试，不依赖真实屏幕
docs/retina-l0-lite.md       # 本文件
```

## 3. CLI

```powershell
# 启动（前台）
python -m agentctl.retina start --hwnd <HWND> --fps 5 --seconds 30

# 启动（后台）
python -m agentctl.retina start --hwnd <HWND> --fps 5 --seconds 30 --daemon

# 状态
python -m agentctl.retina status

# 事件（从 seq 0 开始）
python -m agentctl.retina changes --since 0

# 单次抓取（显式临时 JPEG）
python -m agentctl.retina snapshot --hwnd <HWND> --jpeg <TEMP>\retina.jpg

# 停止
python -m agentctl.retina stop
```

状态目录默认：

```text
%LOCALAPPDATA%\AgentCtl\retina\
  state.json      # 最新帧元数据、ring 大小、稳定计数
  events.jsonl    # 结构化事件
  retina.pid      # daemon PID
  daemon.log      # 后台启动日志
```

## 3.1 MCP 工具（已接）

```text
ctl_retina_status    A 级只读，读 state.json；返回 pid/pid_alive/stale/state
ctl_retina_changes   A 级只读，读 events.jsonl；since / limit / truncated
ctl_retina_snapshot  A 级只读，向 daemon 请求最新帧/指定 seq，落一张显式 JPEG
```

示例：

```json
{"name":"ctl_retina_status","arguments":{}}
{"name":"ctl_retina_changes","arguments":{"since":0,"limit":200}}
{"name":"ctl_retina_snapshot","arguments":{}}
```

两者都只读文件，不启动/停止 daemon，不返回图像。  
`state_dir` 可选，默认 `%LOCALAPPDATA%\AgentCtl\retina`。

源码头 MCP 实测：

```text
python -m agentctl.mcp → tools/list = 29
ctl_retina_status
ctl_retina_changes
ctl_retina_snapshot
```

注意：当前安装版 `AgentCtl.exe` 仍是旧编译产物（26 工具），新工具要重新打包安装后才在桌面 MCP 里出现；源码/测试路径已生效。

## 4. 事件 Schema

```json
{
  "seq": 42,
  "ts": 1730000000.123,
  "kind": "change",
  "bbox": [120, 80, 640, 360],
  "ratio": 0.084,
  "stable_for_ms": 0,
  "version": "0.1.0",
  "source": "client",
  "scale": 0.5
}
```

- `kind`: `change` / `stable` / `blank`
- `bbox`: 降采样前客户区像素的 `[x, y, w, h]`；无定位时 `null`
- `scale`: 事件坐标到 ring 图像的缩放比例
- `stable_for_ms`: 只在 `stable` 事件里有意义

## 5. 关键参数

```text
fps                 5
ring_seconds        30
max_width           1280
jpeg_quality        60
stable_frames       3
change_min_interval 300ms
min_change_ratio    0.001（低于此比例视为噪声，不触发 change）
```

内存估算：

```text
实测 1280×764 JPEG 约 105KB/帧（窗口内容复杂时）
5fps × 30s = 150 帧 ≈ 15MB
147 帧实测 ring = 15.7MB
```

## 6. 实测

离线测试：

```text
7 passed
覆盖：stable 只发一次、change 重置稳定、blank 不洪水、
      ring 按时间淘汰、changes 过滤、尺寸变化、微小变化过滤
```

真机抓帧（VS Code 窗口 hwnd 197856，5fps）：

```text
MCP ctl_retina_status:
  ok=true, pid_alive=true, stale=false
  seq=213
  ring.frames=147
  ring.jpeg_bytes≈15.7MB
  latest=1280×764，约 105KB
  stable.count=24, stable.emitted=true
  events=25

MCP ctl_retina_changes(since=0, limit=5):
  count=5, truncated=true
  返回 change/stable 事件，bbox/ratio/scale 字段完整

停止 daemon 后再查 status:
  ok=false, code=5, pid_alive=false, stale=true

ctl_retina_snapshot:
  seq=129
  path=.../retina-000129.jpg
  width=1280, height=764
  文件 106,542 bytes，JPEG 可解码

stop:
  {"ok":true,"stopped":10456,"graceful":true}
```

> 测试发现并修复：旧版 `_cmd_start` 主线程只 `sleep(1)`，watchdog 置 `_stop` 后
> 采集线程退出但主线程不退出，`stop` 只能 taskkill。现在主线程检测
> `d._stop` / `d._thread.is_alive()`，`stop.request` 能干净退出。

> 事件洪水修复：旧数据里 0.01% 级别的动画/抗锯齿也会触发 `change`。
> 已加 `min_change_ratio=0.001`，低于阈值按“没变”处理，并补了对应单测。

## 7. 架构/代码评审（Magpie → MiniMax-M3）

评审后已修：

- `state.json` 临时文件改为唯一名字 + `finally` 清理，避免残留。
- `--daemon` 检查已有 pid；子进程 1 秒内退出则返回失败和日志尾部。
- 增加单实例检查，避免两个 daemon 同时写 events/state/pid。
- 采集失败时重置 diff 基线/稳定计数，不把失败当成“没变”。
- 敏感窗口标题读不到时 **fail-closed**，跳过该帧。
- `stop` 改为 `stop.request` 优雅退出，3 秒不退才 `taskkill /F`。
- `events.jsonl` 超过 10MB 轮转为 `events.1.jsonl`。
- `min_change_ratio=0.001`，过滤微小动画/抗锯齿引起的事件洪水。

仍保留的取舍：

- 首帧作为稳定基线计入 `stable_frames`；若要“首帧不算”，需改 `StabilityGate` 契约。
- `changes` 仍全量读 `events.jsonl`；10MB 轮转后单次查询有界。
- Windows 下 `taskkill` 是最后手段，优先走 `stop.request`。

## 8. 明确没做

1. **只接了只读查询/取帧。** `ctl_retina_status` / `ctl_retina_changes` / `ctl_retina_snapshot` 已进 MCP；启动/停止 daemon 仍走 CLI，没有 `ctl_retina_start/stop`。
2. **没有 VLM / OCR / bbox 实体对齐。** 语义理解仍留给后续。
3. **没有 `rewatch` 历史帧理解。** ring 里的 JPEG 只能按 seq 取，未做理解接口。
4. **没有多窗口 / 多客户端 / TCP RPC。** 单 daemon、单窗口、文件查询。
5. **没有持久化全帧。** 只保留结构化事件和显式 `snapshot` JPEG。

## 9. 安装记录（2026-11-04）

构建：

```text
PyInstaller 6.22.2
spec 修正：
  · hiddenimports += agentctl.retina（否则懒 import 不会被打包）
  · a.binaries 兼容 PyInstaller 6 的 3 元组
输出：
  dist_retina/AgentCtl/AgentCtl.exe     99.8MB
  dist_retina/AgentCtl/_internal        ~761MB
```

安装：

```text
目标：%LOCALAPPDATA%\Programs\AgentCtl-fixed
备份：%LOCALAPPDATA%\Programs\AgentCtl-fixed.bak_20261104_retina
保留：legacy_tools（含 perceive/act 的 2026-11-04 补丁）、work、agentctl-mcp.cmd
清理：临时 _internal.old_retina 已删除；安装后约 769MB
```

验证：

```text
AgentCtl.exe status                         正常
AgentCtl.exe mcp → tools/list               29
ctl_retina_status / changes / snapshot      已注册
ctl_retina_status（无有效 A 证）             code=9（不是未知工具）
```

回滚：

```text
停掉 AgentCtl.exe
删除 AgentCtl-fixed\_internal 和 AgentCtl.exe
从 AgentCtl-fixed.bak_20261104_retina 复制回来
```

注意：安装时停掉了旧 AgentCtl MCP 进程；当前 OpenCode 会话的 agentctl 工具连接需要重启/重载窗口后恢复。

> 2026-11-04 19:40 追加：授权弹窗的 `legacy` 导入 bug 已修，并按同一路径重装。
> 当前安装含 `agentctl_main.py` sys.path 修复和 29 个 MCP 工具，记录见
> `docs/agentctl-authfix-20261104.md`。回滚备份：
> `%LOCALAPPDATA%\Programs\AgentCtl-fixed.bak_20261104_authfix`。

## 10.1 组件接线现状（2026-11-05）

| 项 | 状态 | 证据 |
|---|---|---|
| DSH（vscode profile）指向新装 | ✅ 已改 `~/.dsh/profiles/vscode/cordis.patch.yml` → `cmd /c ...\AgentCtl-fixed\agentctl-mcp.cmd` | `dsh --profile vscode --dump-config` exit=0，stderr 空 |
| 新装 MCP 工具数 | ✅ **29**（含 `ctl_retina_status` / `ctl_retina_changes` / `ctl_retina_snapshot`） | stdio 握手实测 `tools/list` |
| 事件链统一 | ✅ 启动器钉死 `AGENTCTL_TIMELINE=%LOCALAPPDATA%\AgentCtl\work\timeline`（真源 706 events） | `deploy/agentctl-mcp.cmd`（本仓新增，ASCII，已过扫引号） |
| 影子库 | ⚠ 两个影子库已**复制**归档到 `%LOCALAPPDATA%\AgentCtl\work\timeline\_archive\`，原件未删 | 旧装 303 events / 新装影子 51 events |
| 生效条件 | ⚠ **需重载窗口**（`Developer: Reload Window`）或新开 DSH 会话——cordis 配置在启动时合成 | 运行中的会话仍连旧实例 |
| retina daemon | ❌ 未常驻（`daemon.log`：11-04 14:34 通行证过期导致启动 RuntimeError）；启动仍走 CLI，无 `ctl_retina_start/stop` | `docs/retina-l0-lite.md` §9 |

> 旧装 `AgentCtl\`（2026-10-04 build，26 工具、无 retina）自 DSH 改线后即无调用方，
> 建议下线（先确认 `AgentCtlPanel.exe` 面板是否还要留）。

## 10.2 四路消费者接线（2026-11-05 复核后）

| 消费者 | 入口 | 工具数 | timeline 落点 |
|---|---|---|---|
| DSH（vscode profile） | `cmd /c …\AgentCtl-fixed\agentctl-mcp.cmd` | 29 | 活链 `%LOCALAPPDATA%\AgentCtl\work\timeline` |
| OpenCode | 同上 | 29 | 活链 |
| Codex | `.codex\mcp\run_agentctl.cmd`（源码直跑，**已加 `AGENTCTL_TIMELINE`**） | 29 | 活链 |
| ZCode | `cmd /c …\AgentCtl-fixed\agentctl-mcp.cmd`（原为旧装裸 exe） | 29 | 活链 |
| SuperAgent | `superagent/agentctl_client.py` **优先 .cmd 启动器**（已同步 runtime 副本） | 29 | 活链 |

规则一句话：**任何 MCP 入口都必须经过会钉死 `AGENTCTL_TIMELINE` 的启动器**；
裸跑 `AgentCtl.exe mcp` 会写进安装目录下的影子库，证据链当场分叉。

> ✅ **已裁决 A（2026-11-05）：记切换点、留归档。**
> 活链上写了 seq 709（`witness`/`chain-cutover`）标记切换点；历史链 10-02→11-02（17,900 条）
> 原样归档到 `%LOCALAPPDATA%\AgentCtl\work\timeline\_archive\repo-chain-20261002-20261102\`，
> **原件保留、不删、不重算哈希**（md5 对账相等）。两链创世哈希不同、无法拼接，故不合并。
> 另修一处历史红：`ctl_verify` 曾因 2026-11-01 双写（同一天文件被两个写入方各写一批 seq 8/9/10）
> 判链断 → 隔离 3 行冲突（原件逐字节归档 `_archive\live-jsonl-conflict\`），链上记 seq 710，
> **现双 scope 全绿（events=710，last_hash=48b8625a…）**。详见
> `%LOCALAPPDATA%\AgentCtl\work\timeline\_archive\README_归档与切换点.md`。

## 10.3 P1：采集期授权（把「采集」与「每次读取都重新授权」解耦）

**问题**：daemon 启动时校验一次 A 级通行证；此后通行证过期，采集还在跑，
但 MCP 读取（`ctl_retina_*`）被闸门拒（code=9）⇒ 连续视觉变成「只写不读」。

**口径（一次授权 = 一段采集期）**：

| | 行为 |
|---|---|
| 签发 | daemon 启动即写 `session.json`（受控目录，**只记元数据，不含图像**）：issued_at / expires_at / scopes=["A"] / hwnd / fps / pid |
| 采集 | 采集期内正常跑；到期 ⇒ **daemon 自停**（`kind=session_expired` 事件留痕，`last_error` 落盘）⇒ 不越权继续录屏 |
| 读取 | `ctl_retina_status` / `changes` / `snapshot` 在通行证不可用时，**回退到采集期授权**（读**已采集**的数据），并在返回里自报 `auth.source`（"通行证" / "采集期授权"） |
| 边界 | 采集期凭据**不含新感知**：`ctl_shot` / `ctl_screen` / `ctl_tree` 仍必须当下的通行证 |
| 撤销 | daemon 停止 ⇒ 凭据立即失效（Windows 上 unlink 会与读侧撞句柄，故带退避重试） |

代码：`src/agentctl/retina.py`（`issue_session` / `revoke_session` / `session_info` / `run_loop` 到期自停）、
`src/agentctl/core.py`（`_retina_read_gate` 回退闸门）；测试 `tests/test_retina_session.py`（7 条离线）。

**实测（2026-11-05）**：`--session-minutes 1` 起 daemon → 到期自动退出 ✅、凭据撤销 ✅、
events.jsonl 留下 `{"kind":"session_expired","reason":"采集期已到期"}` ✅；
全量测试 27 passed。

## 11. 下一步

- P0：daemon 启动/停止接入 Windows 计划任务或 `agentctl serve` 生命周期。
- P1：加 `ctl_retina_snapshot` MCP 封装，复用 `screen_version` / capture_id 口径。
- P1：加 `rewatch(t1,t2)`，按 seq 取 ring JPEG，按需交给 OCR/VLM。
- P2：多窗口、敏感窗口白名单配置化、事件压缩。
