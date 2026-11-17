# -*- coding: utf-8 -*-
"""ctl_browser goto/open 目标 URL 出口回归（2026-11-17 夜跑实测缺口）。

旧行为：契约没有 target 参数、t_browser 的 argv 也拼不出 URL ⇒
cdp.py cmd_goto 拿 a.target=None，`location.href=''` 直接 SyntaxError
（rc=1 掉进「未知返回码」）。当晚只能用 eval JS 导航绕过。
修复：goto → --target、open → 位置参数；goto 的 url_contains 改映射
--url2（cmd_goto 只认 url2 挑标签页），其余命令照旧 --url。
"""
import agentctl.core as core


def _capture_argv(monkeypatch):
    seen = []
    monkeypatch.setattr(core.gate, "check", lambda scope: (True, "", 0))

    def fake_legacy(name, argv, timeout=60):
        seen.append(list(argv))
        return 0, "{}", ""

    monkeypatch.setattr(core, "_legacy", fake_legacy)
    return seen


def test_goto_passes_target_url(monkeypatch):
    seen = _capture_argv(monkeypatch)
    r = core.t_browser({"action": "goto", "target": "https://example.com"})
    assert r["ok"] is True, r.get("warning")
    argv = seen[-1]
    assert argv[0] == "goto"
    assert "--target" in argv
    assert argv[argv.index("--target") + 1] == "https://example.com"


def test_goto_url_contains_maps_to_url2(monkeypatch):
    seen = _capture_argv(monkeypatch)
    core.t_browser({"action": "goto", "target": "https://example.com",
                    "url_contains": "lab"})
    argv = seen[-1]
    assert "--url2" in argv and "lab" in argv
    assert "--url" not in argv          # cmd_goto 不认 --url，别传一份没人读的


def test_open_passes_url_positional(monkeypatch):
    seen = _capture_argv(monkeypatch)
    r = core.t_browser({"action": "open", "target": "https://example.com"})
    assert r["ok"] is True
    argv = seen[-1]
    assert argv[0] == "open"
    assert argv[1] == "https://example.com"   # 位置参数紧跟动作名
    assert "--target" not in argv


def test_pages_untouched(monkeypatch):
    seen = _capture_argv(monkeypatch)
    core.t_browser({"action": "pages"})
    argv = seen[-1]
    assert argv[0] == "pages"
    assert "--target" not in argv and "--url" not in argv and "--url2" not in argv


def test_text_url_contains_still_url(monkeypatch):
    seen = _capture_argv(monkeypatch)
    core.t_browser({"action": "text", "url_contains": "news"})
    argv = seen[-1]
    assert "--url" in argv and "news" in argv
    assert "--url2" not in argv
