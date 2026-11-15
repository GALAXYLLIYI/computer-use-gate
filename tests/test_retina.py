# -*- coding: utf-8 -*-
"""agentctl.retina L0-lite 测试（不依赖真实屏幕 / 不依赖通行证）。"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from agentctl.retina import CaptureResult, Frame, FrameRing, RetinaConfig, RetinaDaemon


def _frame(*, blank: bool = False, box: bool = False) -> Image.Image:
    img = Image.new("RGB", (120, 80), (255, 255, 255) if not blank else (70, 70, 70))
    if not blank:
        d = ImageDraw.Draw(img)
        # 两种非空白布局，用于制造“变化”；纯白会被 is_blank 判为空白。
        rect = (20, 20, 60, 50) if box else (70, 20, 100, 45)
        d.rectangle(rect, fill=(0, 0, 0))
    return img


def _daemon(tmp_path: Path, **kw) -> RetinaDaemon:
    cfg = RetinaConfig(
        hwnd=1,
        fps=5,
        ring_seconds=30,
        max_width=kw.pop("max_width", 120),
        stable_frames=3,
        change_min_interval_ms=0,
        state_dir=str(tmp_path),
        skip_gate=True,
        **kw,
    )
    return RetinaDaemon(cfg, capture_fn=lambda _h: CaptureResult(_frame(), "client", True))


def _feed(d: RetinaDaemon, img: Image.Image):
    return d.process_frame(CaptureResult(img, "client", True))


def test_stable_after_three_frames(tmp_path):
    d = _daemon(tmp_path)
    assert _feed(d, _frame(box=True)) == []
    assert _feed(d, _frame(box=True)) == []
    events = _feed(d, _frame(box=True))
    assert [e["kind"] for e in events] == ["stable"]
    assert events[0]["stable_for_ms"] >= 0
    assert _feed(d, _frame(box=True)) == []


def test_change_resets_then_stable_again(tmp_path):
    d = _daemon(tmp_path)
    for _ in range(3):
        _feed(d, _frame(box=True))
    events = _feed(d, _frame(box=False))
    assert [e["kind"] for e in events] == ["change"]
    assert d._gate.stable_count == 0
    for _ in range(3):
        events = _feed(d, _frame(box=False))
    assert [e["kind"] for e in events] == ["stable"]


def test_blank_event_not_flooded(tmp_path):
    d = _daemon(tmp_path)
    events = _feed(d, _frame(blank=True))
    assert [e["kind"] for e in events] == ["blank"]
    assert _feed(d, _frame(blank=True)) == []
    # 从空白恢复正常画面是一次明确变化
    assert [e["kind"] for e in _feed(d, _frame(box=True))] == ["change"]


def test_ring_eviction_and_latest(tmp_path):
    ring = FrameRing(seconds=2)
    for i in range(4):
        ring.put(Frame(seq=i, ts=float(i), jpeg=b"x" * 10, width=1, height=1,
                       source="client", blank=False, scale=1.0))
    assert len(ring) == 3
    assert ring.latest().seq == 3
    assert ring.get(0) is None
    assert ring.get(3).seq == 3
    assert ring.bytes() == 30


def test_changes_filter(tmp_path):
    d = _daemon(tmp_path)
    _feed(d, _frame(box=True))
    _feed(d, _frame(box=True))
    _feed(d, _frame(box=False))
    out = d.changes(0)
    assert out["events"]
    assert all(e["seq"] > 0 for e in out["events"])
    assert d.changes(999)["events"] == []
    assert d.changes(0)["truncated"] is False


def test_tiny_change_ignored(tmp_path):
    d = _daemon(tmp_path, max_width=200, min_change_ratio=0.001)
    base = Image.new("RGB", (200, 200), (255, 255, 255))
    ImageDraw.Draw(base).rectangle((100, 100, 140, 140), fill=(0, 0, 0))
    assert _feed(d, base) == []
    tiny = base.copy()
    ImageDraw.Draw(tiny).rectangle((10, 10, 13, 17), fill=(0, 0, 0))
    events = _feed(d, tiny)
    assert [e["kind"] for e in events] == []
    assert d._gate.stable_count == 2  # 首帧基线 1 + 本次微小变化按“没变”计 1


def test_snapshot_request_writes_latest_jpeg(tmp_path):
    d = _daemon(tmp_path)
    _feed(d, _frame(box=True))
    req = tmp_path / "snapshot.request"
    req.write_text(json.dumps({"id": "t1"}), encoding="utf-8")
    d._serve_snapshot_request()
    resp = json.loads((tmp_path / "snapshot.response").read_text(encoding="utf-8"))
    assert resp["id"] == "t1"
    assert resp["ok"] is True
    p = Path(resp["path"])
    assert p.exists()
    assert p.read_bytes()[:2] == b"\xff\xd8"  # JPEG SOI
    assert resp["seq"] == 1


def test_size_change_is_change(tmp_path):
    d = _daemon(tmp_path)
    _feed(d, Image.new("RGB", (120, 80), (255, 255, 255)))
    small = Image.new("RGB", (100, 80), (255, 255, 255))
    ImageDraw.Draw(small).rectangle((10, 10, 40, 40), fill=(0, 0, 0))
    events = _feed(d, small)
    assert [e["kind"] for e in events] == ["change"]
    assert d.status()["seq"] == 2
