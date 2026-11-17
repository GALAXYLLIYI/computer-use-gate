"""window_events 离线测试——纯函数 diff，不依赖真实屏幕。

仿 agent-desktop signals_tests 的口径：全部用手搭夹具，
重点测 completeness 门（不完整样本不做差分）、事件排序确定性、
基线合并语义（关掉的窗口不留基线）。
"""
from agentctl.window_events import diff_window_sets, merge_baselines, enumerate_windows


def _base(windows, focused=None):
    return {"complete": True, "windows": windows, "focused": focused}


def _win(pid, title, cls="App"):
    return {"pid": pid, "title": title, "cls": cls}


def test_opened_and_closed():
    base = _base({100: _win(11, "记事本"), 200: _win(22, "计算器")}, focused=100)
    cur = _base({200: _win(22, "计算器"), 300: _win(33, "画图")}, focused=300)
    events = diff_window_sets(base, cur)
    types = [e["type"] for e in events]
    # 排序：closed(0) < opened(1) < focus_changed(2)
    assert types == ["window_closed", "window_opened", "focus_changed"]
    closed = events[0]
    assert closed["hwnd"] == 100 and closed["title"] == "记事本"
    opened = events[1]
    assert opened["hwnd"] == 300 and opened["pid"] == 33


def test_no_diff_when_identical():
    base = _base({100: _win(11, "记事本")}, focused=100)
    cur = _base({100: _win(11, "记事本")}, focused=100)
    assert diff_window_sets(base, cur) == []


def test_focus_changed_only():
    base = _base({100: _win(11, "记事本"), 200: _win(22, "计算器")}, focused=100)
    cur = _base({100: _win(11, "记事本"), 200: _win(22, "计算器")}, focused=200)
    events = diff_window_sets(base, cur)
    assert len(events) == 1
    assert events[0]["type"] == "focus_changed"
    assert events[0]["hwnd"] == 200
    assert events[0]["title"] == "计算器"


def test_focus_lost_to_none():
    base = _base({100: _win(11, "记事本")}, focused=100)
    cur = _base({100: _win(11, "记事本")}, focused=None)
    events = diff_window_sets(base, cur)
    assert len(events) == 1
    assert events[0]["type"] == "focus_changed"
    assert events[0]["hwnd"] is None


def test_incomplete_samples_never_diff():
    """completeness 门：任一侧 None / complete=False → 不做差分。"""
    good = _base({100: _win(11, "记事本")}, focused=100)
    assert diff_window_sets(None, good) == []
    assert diff_window_sets(good, None) == []
    assert diff_window_sets(None, None) == []
    partial = {"complete": False, "windows": {100: _win(11, "记事本")}, "focused": 100}
    assert diff_window_sets(good, partial) == []
    assert diff_window_sets(partial, good) == []


def test_same_hwnd_new_pid_is_new_window():
    """hwnd 回收防护：同 hwnd 不同 pid = 旧的关了、新的开了（不是什么都没发生）。"""
    base = _base({100: _win(11, "旧进程")}, focused=100)
    cur = _base({100: _win(99, "新进程")}, focused=100)
    events = diff_window_sets(base, cur)
    types = [e["type"] for e in events]
    assert types == ["window_closed", "window_opened"]


def test_merge_baselines_semantics():
    """合并只采信完整 current；关掉的窗口不留基线（再开要报 opened）。"""
    base = _base({100: _win(11, "记事本")}, focused=100)
    partial = None
    assert merge_baselines(base, partial) is base  # 不完整：沿用旧基线
    cur = _base({200: _win(22, "画图")}, focused=200)
    merged = merge_baselines(base, cur)
    assert merged is cur  # 完整：直接采信 current（100 已关，不留）


def test_enumerate_windows_returns_dict_or_none():
    """真机冒烟：要么拿到完整清单，要么显式 None——不允许半拉子清单。"""
    sample = enumerate_windows()
    assert sample is None or (
        sample.get("complete") is True and isinstance(sample.get("windows"), dict)
    )
