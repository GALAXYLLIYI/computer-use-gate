# -*- coding: utf-8 -*-
r"""元素语义增强 · 采集侧最小心跳（2026-10-31 晚 · 用户批准项③）

目标：点击/填充命中的 timeline payload 附带 UIA 元素语义（name/role），供
    ①记忆引擎（obs 带语义，正样本质量解锁——数据源升级三条件之一）
    ②下一轮训练（目标-观测关系从抄写升级为语义）

设计铁律：
    1. **只加字段不改旧字段**——旧消费者按旧键读，新键多余不伤人（向后兼容铁律）。
    2. **最小心跳**：命中点一次轻量 UIA 探测（uiautomation COM ControlFromPoint，
       进程内已有 DPI 声明），异常静默吞掉——增益不是依赖，serving 延迟红线不得触碰。
    3. 不改 gate_action、不改 eval 判据、不写 episodes（harvest 自动拾取新字段）。

实现：`element_at_point(hwnd, x, y)` 复用 agentctl.uia_tree._lib() 的 COM 单例
    （uiautomation 库的 ControlFromPoint 是点查询原生接口）。
    `enrich_timeline_payload(payload, hwnd, xy)` 是 timeline 回执合并入口。
"""
from __future__ import annotations

from typing import Any, Optional

_MAX_NAME = 80
_MAX_ROLE = 40


def element_at_point(x: int, y: int) -> Optional[dict]:
    """物理像素点 → {"name","role"} 或 None。异常静默（增益非依赖）。"""
    try:
        from agentctl import uia_tree
        auto = uia_tree._lib()          # 进程单例 + DPI 感知（与既有采集同源）
        ctrl = auto.ControlFromPoint(int(x), int(y))
        if ctrl is None:
            return None
        name = (ctrl.Name or "")
        role = (ctrl.LocalizedControlType or "")
        if not name and not role:
            return None
        return {"name": str(name)[:_MAX_NAME], "role": str(role)[:_MAX_ROLE]}
    except Exception:  # noqa: BLE001
        return None


def enrich_timeline_payload(payload: dict, xy: Optional[list]) -> dict:
    """timeline 回执合并：element 键不存在时新增（先到先得，旧值不覆盖）。
    只加不改——旧消费者按旧键读不受影响。坐标从 payload['xy'] 取。"""
    out = dict(payload or {})
    if "element" in out:
        return out
    if not xy or len(xy) < 2:
        return out
    sem = element_at_point(int(xy[0]), int(xy[1]))
    if sem:
        out["element"] = sem
    return out
