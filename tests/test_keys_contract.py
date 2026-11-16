# -*- coding: utf-8 -*-
"""ctl_keys 契约字段回归：失败信封的 data 可能是 null，不能因此崩成内部错误。

2026-11-15 冻结版实测：`ctl_keys --keys 9 --dry_run` 早期失败返回 code=15 时
`data=None`，旧实现 `r.setdefault("data", {})` 拿到 None ⇒
`'NoneType' object has no attribute 'setdefault'`，把一次正常拒绝变成内部错误。
"""
import agentctl.core as core


def _stub(monkeypatch, ret):
    monkeypatch.setattr(core, "_allow_foreground", lambda *a, **k: None)
    monkeypatch.setattr(core, "_deny_sensitive_target", lambda *a, **k: None)
    monkeypatch.setattr(core, "_act", lambda *a, **k: ret)


def test_keys_fields_when_data_is_none(monkeypatch):
    ret = {"ok": False, "code": 9, "data": None, "warning": "未获授权"}
    _stub(monkeypatch, ret)
    r = core.t_keys({"keys": "9", "hwnd": 1, "allow_foreground": True})
    assert isinstance(r["data"], dict)
    assert r["data"]["vk"] == "9"
    assert r["data"]["键名"] == "9"
    assert r["data"]["解析"]
    assert r["data"]["ctrl"] is False
    assert r["data"]["次数"] == 1


def test_keys_fields_merge_into_existing_data(monkeypatch):
    ret = {"ok": True, "code": 0, "data": {"rc": 0, "raw": "ok"}}
    _stub(monkeypatch, ret)
    r = core.t_keys({"keys": "9", "hwnd": 1, "allow_foreground": True})
    assert r["data"]["rc"] == 0          # 原有字段不被覆盖
    assert r["data"]["raw"] == "ok"
    assert r["data"]["键名"] == "9"
