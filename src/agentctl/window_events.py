"""窗口级事件 diff——retina 事件流的信号源之一。

★ 设计来源：vercel-labs/agent-desktop 的 `wait/signals.rs`（Apache-2.0，
  2026-11-17 精读后按仓库口径重写）：
  - 纯函数基线差分：`diff_window_sets(baseline, current) -> events`，
    不碰任何平台 API，全部逻辑可用离线夹具测试。
  - **completeness 门**：枚举失败（返回 None / 不完整）的样本**不参与 diff**——
    不完整的采样做差分会产生假事件（漏看到的窗口被误判成「关闭」）。
  - 事件排序确定性：closed < opened < focus_changed，同 rank 内按 hwnd。

★ 与像素事件流的分工：retina.process_frame 的 diff 只看得见「像素变了」，
  看不见「窗口消失了」。窗口级 diff 把「结构变化」显式化，两者互补。

★ 身份口径：(hwnd, pid) 二元组。hwnd 单独不可靠（OS 会回收复用），pid 会把
  同进程的多窗口混在一起；二元组下，同进程重建窗口会正确报出
  closed(旧 hwnd) + opened(新 hwnd)，而不是什么都没发生。
  已知局限（第一版）：同 hwnd + 同 pid 的标题变化不报（留给后续 title_changed）。
"""
from __future__ import annotations

from typing import Any

# 事件 rank：与 agent-desktop 同语义——消失类先报，出现类后报，焦点最后。
_RANK = {"window_closed": 0, "window_opened": 1, "focus_changed": 2}


def enumerate_windows() -> dict | None:
    """枚举可见顶层窗口 → 基线样本；枚举失败返回 None（completeness=False）。

    只问窗口管理器要 hwnd/pid/title，不看内容、不消耗感知额度。
    跳过：不可见 / 最小化 / 桌面容器（Progman/WorkerW/Shell_TrayWnd）/
    无标题且无类的系统壳。任何一步抛异常 → 整体视为不完整（返回 None），
    因为「枚举到一半」的清单做差分必然产生假事件。
    """
    try:
        import win32gui
        import win32process
    except ImportError:  # 非 Windows / 缺依赖：显式不完整
        return None
    out: dict[int, dict] = {}
    try:
        def _cb(hwnd: int, _acc: Any) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if win32gui.IsIconic(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            if cls in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return True
            if not title and not cls:
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            out[int(hwnd)] = {"pid": int(pid), "title": title or "", "cls": cls or ""}
            return True

        win32gui.EnumWindows(_cb, None)
    except Exception:
        return None
    return {"complete": True, "windows": out, "focused": _focused_hwnd(out)}


def _focused_hwnd(windows: dict[int, dict]) -> int | None:
    """前台窗口：用 GetForegroundWindow 取，且必须在清单内才算数。"""
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        return int(hwnd) if int(hwnd) in windows else None
    except Exception:
        return None


def snapshot_baseline() -> dict | None:
    """enumerate_windows 的别名——语义上它是「一次基线采样」。"""
    return enumerate_windows()


def diff_window_sets(baseline: dict | None, current: dict | None) -> list[dict]:
    """两组基线做差分 → 窗口级事件（已按 rank 稳定排序）。

    completeness 门：任一侧不完整（None / complete=False）→ 返回 []，
    并交由调用方沿用旧基线（不要拿不完整样本刷新基线）。
    """
    if not baseline or not baseline.get("complete") or not current or not current.get("complete"):
        return []
    base_wins: dict = baseline.get("windows") or {}
    cur_wins: dict = current.get("windows") or {}
    events: list[dict] = []

    # 身份 = (hwnd, pid) 二元组：裸 hwnd 会被 OS 回收复用，pid 会把同进程
    # 多窗口混在一起；二元组下同 hwnd 换 pid 正确报出 closed+opened。
    def _wid(hwnd: int, info: dict) -> tuple:
        return (hwnd, info.get("pid"))

    base_ids = {_wid(h, i): (h, i) for h, i in base_wins.items()}
    cur_ids = {_wid(h, i): (h, i) for h, i in cur_wins.items()}

    for wid, (hwnd, info) in cur_ids.items():
        if wid not in base_ids:
            events.append({"type": "window_opened", "hwnd": hwnd, **info})
    for wid, (hwnd, info) in base_ids.items():
        if wid not in cur_ids:
            events.append({"type": "window_closed", "hwnd": hwnd, **info})

    base_focus = baseline.get("focused")
    cur_focus = current.get("focused")
    if cur_focus != base_focus and (cur_focus in cur_wins or cur_focus is None):
        ev: dict = {"type": "focus_changed", "hwnd": cur_focus}
        if cur_focus in cur_wins:
            ev.update({"title": cur_wins[cur_focus]["title"], "pid": cur_wins[cur_focus]["pid"]})
        events.append(ev)

    events.sort(key=lambda e: (_RANK.get(e["type"], 9), e.get("hwnd") or 0))
    return events


def merge_baselines(seen: dict | None, current: dict | None) -> dict | None:
    """基线合并：只增不减（agent-desktop merge_signal_baseline 同语义）。

    窗口集合用 current 直接覆盖（关掉的窗口不该留在基线里——它再打开要报 opened），
    completeness 直接采信 current。seen 只用于「两侧都完整」时的整体替换。
    """
    if not current or not current.get("complete"):
        return seen
    return current
