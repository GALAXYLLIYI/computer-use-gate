# -*- coding: utf-8 -*-
"""sync.LockedDict 的最小回归：clear() 必须存在且真的清空。"""
from agentctl.sync import LockedDict


def test_clear_empties_dict():
    d = LockedDict({"a": 1, "b": 2})
    d.clear()
    assert len(d) == 0
    assert "a" not in d and "b" not in d


def test_clear_keeps_dict_usable():
    d = LockedDict()
    d["x"] = 1
    d.clear()
    d["y"] = 2
    assert d.get("y") == 2
    assert d.pop("y") == 2
