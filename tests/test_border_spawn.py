# -*- coding: utf-8 -*-
"""_ensure_border 的接线回归：必须走 ctrl_border.start_follow（父死自收），不再裸 Popen。"""
import agentctl.core as core
from agentctl import ctrl_border


def test_existing_border_is_idempotent(monkeypatch):
    monkeypatch.setattr(core, "_border_running", lambda: 777)
    r = core._ensure_border()
    assert r["spawned"] is False
    assert r["已有边框窗"] == 777


def test_ensure_border_delegates_to_start_follow(monkeypatch):
    monkeypatch.setattr(core, "_border_running", lambda: 0)
    monkeypatch.delattr(core.sys, "frozen", raising=False)
    seen = {}

    def fake_start(reason=""):
        seen["reason"] = reason
        return 4321

    monkeypatch.setattr(ctrl_border, "start_follow", fake_start)
    r = core._ensure_border()
    assert r["spawned"] is True and r["pid"] == 4321
    assert seen["reason"] == "core.t_authorize"


def test_frozen_does_not_spawn(monkeypatch):
    monkeypatch.setattr(core, "_border_running", lambda: 0)
    monkeypatch.setattr(core.sys, "frozen", True, raising=False)
    called = []
    monkeypatch.setattr(ctrl_border, "start_follow", lambda reason="": called.append(reason) or 1)
    r = core._ensure_border()
    assert r["spawned"] is False
    assert called == []
