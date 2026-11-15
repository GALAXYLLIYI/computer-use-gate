# -*- coding: utf-8 -*-
"""P1：采集期授权（capture session）测试 —— 不依赖真实屏幕 / 不依赖通行证。

被测口径：
  · daemon 启动即签发采集期凭据（session.json），到期自停；
  · 读侧（ctl_retina_*）在通行证不可用时，可用采集期授权读**已采集数据**；
  · 采集期凭据不含新感知（ctl_shot 等仍要通行证）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from agentctl import gate, retina
from agentctl.core import t_retina_changes, t_retina_status
from agentctl.retina import CaptureResult, RetinaConfig, RetinaDaemon

from PIL import Image


def _daemon(tmp_path: Path, **kw) -> RetinaDaemon:
    cfg = RetinaConfig(
        hwnd=1, fps=5, ring_seconds=30, max_width=120, stable_frames=3,
        change_min_interval_ms=0, state_dir=str(tmp_path), skip_gate=True, **kw,
    )
    d = RetinaDaemon(cfg, capture_fn=lambda _h: CaptureResult(None, "client", False, "no screen"))
    d.start()
    return d


def test_start_issues_session(tmp_path):
    d = _daemon(tmp_path, session_minutes=30)
    try:
        info = retina.session_info(tmp_path)
        assert info["exists"] is True
        assert info["valid"] is True
        assert info["pid_alive"] is True
        assert info["minutes"] == 30
        # 凭据只记元数据，不含图像
        raw = (tmp_path / "session.json").read_text(encoding="utf-8")
        assert "jpeg" not in raw.lower()
    finally:
        d.stop()


def test_stop_revokes_session(tmp_path):
    d = _daemon(tmp_path)
    d.stop()
    info = retina.session_info(tmp_path)
    assert info["exists"] is False
    assert info["valid"] is False


def test_expired_session_is_invalid(tmp_path):
    _daemon(tmp_path)
    p = tmp_path / "session.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["expires_at"] = time.time() - 1
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    info = retina.session_info(tmp_path)
    assert info["valid"] is False
    assert "到期" in info["reason"]


def test_daemon_selfstops_when_session_expires(tmp_path):
    d = _daemon(tmp_path)
    # 用内存里的到期时间触发（热路径不读文件，避免与读侧抢句柄）
    d._session["expires_at"] = time.time() - 1
    d.run_loop()          # 应当在一轮检查内自停
    assert d._stop.is_set()
    kinds = [e["kind"] for e in d.changes(0)["events"]]
    assert "session_expired" in kinds


def test_read_falls_back_to_capture_session(tmp_path, monkeypatch):
    """通行证不可用 + 采集期有效 ⇒ 读侧放行，且自报来源。"""
    d = _daemon(tmp_path)
    d.process_frame(CaptureResult(Image.new("RGB", (120, 80), (255, 255, 255)), "client", True))

    def _denied(*a, **k):
        raise gate.GateDenied("通行证已过期（测试）", gate.CODE_UNAUTH)

    monkeypatch.setattr(gate, "require_any", _denied)
    res = t_retina_status({"state_dir": str(tmp_path)})
    assert res.get("code") != gate.CODE_UNAUTH, res.get("warning")
    auth = res["data"]["auth"]
    assert auth["source"] == "采集期授权"
    assert auth["session"]["valid"] is True

    res2 = t_retina_changes({"state_dir": str(tmp_path)})
    assert res2.get("code") != gate.CODE_UNAUTH
    assert res2["data"]["auth"]["source"] == "采集期授权"


def test_read_denied_without_session(tmp_path, monkeypatch):
    """通行证不可用 + 没有采集期 ⇒ 仍然拒（不能因为改了就放行）。"""
    def _denied(*a, **k):
        raise gate.GateDenied("通行证已过期（测试）", gate.CODE_UNAUTH)

    monkeypatch.setattr(gate, "require_any", _denied)
    res = t_retina_status({"state_dir": str(tmp_path)})
    assert res.get("ok") is not True
    assert res.get("code") == gate.CODE_UNAUTH
    assert "未获授权" in (res.get("warning") or "")


def test_read_denied_when_session_expired(tmp_path, monkeypatch):
    _daemon(tmp_path)
    p = tmp_path / "session.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["expires_at"] = time.time() - 1
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _denied(*a, **k):
        raise gate.GateDenied("通行证已过期（测试）", gate.CODE_UNAUTH)

    monkeypatch.setattr(gate, "require_any", _denied)
    res = t_retina_status({"state_dir": str(tmp_path)})
    assert res.get("ok") is not True
    assert res.get("code") == gate.CODE_UNAUTH
