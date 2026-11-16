# -*- coding: utf-8 -*-
"""ctl_focus 成功判据回归（2026-11-16 §4.5.1，P0 误报）。

修复前：窗口确实被置前，`_act` 的通用 after-diff 判词却把 ok 翻成 False /
code=8「画面逐像素没变」—— 聚焦不改变目标窗自身内容，像素 diff 本来就不该
是 focus 的判据。修复后：成功判据 = GetForegroundWindow()==hwnd（前台归属），
像素 diff 降级进 data.focus_证据（非致命）；真没置前才保留 code=5，不许假绿。
"""
import agentctl.core as core


def _stub_act(monkeypatch, ret):
    monkeypatch.setattr(core, "_allow_foreground", lambda *a, **k: None)
    monkeypatch.setattr(core, "_deny_sensitive_target", lambda *a, **k: None)
    monkeypatch.setattr(core, "_act", lambda *a, **k: ret)


# _act 通用画面判词翻红后的形状（实测误报信封的骨架）
_FLIPPED = {
    "ok": False, "code": 8,
    "warning": "★ 动作发出去了，但**动作前后画面逐像素比对没变**（阈值 2/255）",
    "data": {"rc": 0,
             "after": {"diff": {"changed": False, "bbox": None}}}}


def test_focus_front_and_unchanged_pixels_is_ok(monkeypatch):
    """置前成功 + 像素没变 ⇒ ok=true/code=0，diff 降级成证据（不再误报 code=8）。"""
    _stub_act(monkeypatch, dict(_FLIPPED))
    monkeypatch.setattr(core, "_is_foreground", lambda hwnd: True)
    r = core.t_focus({"hwnd": 123})
    assert r["ok"] is True
    assert r["code"] == 0
    assert r["data"]["foreground"] is True
    # diff 仍在证据里，且被点名「不参与成败」
    assert r["data"]["after"]["diff"]["changed"] is False
    assert r["data"]["focus_证据"]["画面diff_changed"] is False
    assert "前台归属" in r["data"]["focus_证据"]["说明"]


def test_focus_sent_but_not_foreground_is_code5(monkeypatch):
    """act 报送达但复核不在前台（前台锁/被抢走）⇒ code=5，不许假绿。"""
    _stub_act(monkeypatch, {"ok": True, "code": 0,
                            "data": {"rc": 0, "raw": "ok"}})
    monkeypatch.setattr(core, "_is_foreground", lambda hwnd: False)
    r = core.t_focus({"hwnd": 123})
    assert r["ok"] is False
    assert r["code"] == 5
    assert r["data"]["foreground"] is False


def test_focus_foreground_unknown_fails_closed(monkeypatch):
    """问不出前台归属（None）⇒ fail-closed，不算成功。"""
    _stub_act(monkeypatch, {"ok": True, "code": 0,
                            "data": {"rc": 0, "raw": "ok"}})
    monkeypatch.setattr(core, "_is_foreground", lambda hwnd: None)
    r = core.t_focus({"hwnd": 123})
    assert r["ok"] is False
    assert r["code"] == 5


def test_focus_act_own_failure_kept(monkeypatch):
    """act 自己报失败（rc=5 置前失败）⇒ 原样保留，只补 foreground 证据。"""
    _stub_act(monkeypatch, {"ok": False, "code": 5,
                            "warning": "坐标/前台/窗口稳定性拒绝",
                            "data": {"rc": 5}})
    monkeypatch.setattr(core, "_is_foreground", lambda hwnd: False)
    r = core.t_focus({"hwnd": 123})
    assert r["ok"] is False
    assert r["code"] == 5
    assert r["data"]["foreground"] is False
    assert "稳定性拒绝" in r["warning"]


def test_focus_closed_loop_failure_wins(monkeypatch):
    """verify_expect 的闭环判词没过 ⇒ 保持失败，前台归属不许把它翻绿（T17 闭环优先）。"""
    _stub_act(monkeypatch, {"ok": False, "code": 8, "verdict": "unsatisfied",
                            "warning": "独立验证没通过",
                            "data": {"rc": 0, "verdict": "unsatisfied"}})
    monkeypatch.setattr(core, "_is_foreground", lambda hwnd: True)
    r = core.t_focus({"hwnd": 123})
    assert r["ok"] is False
    assert r["code"] == 8
    assert r["data"]["foreground"] is True   # 证据照报，判词不改


def test_focus_dry_run_untouched(monkeypatch):
    """dry_run 不真置前 ⇒ 原样返回 _act 结果（不做前台改判）。"""
    _stub_act(monkeypatch, {"ok": True, "code": 0, "data": {"rc": 0, "raw": "演练"}})
    monkeypatch.setattr(core, "_is_foreground", lambda hwnd: False)
    r = core.t_focus({"hwnd": 123, "dry_run": True})
    assert r["ok"] is True
    assert r["code"] == 0
    assert "foreground" not in r["data"]
