# -*- coding: utf-8 -*-
"""agentctl.retina —— L0-lite 连续视觉「视网膜」原型（2026-11-04）

定位：独立 daemon + 文件查询，不改 MCP core，不接 VLM/OCR。
只做四件事：
  M1 捕获：默认 5fps，抓指定窗口客户区；
  M2 环形缓冲：最近 N 秒，内存里只存降采样后的 JPEG 字节；
  M4 稳定性门：复用 framecache.diff_images，输出 change / stable / blank；
  M5 事件流：JSONL 追加，只存结构化字段，不存图。

隐私边界：
  · 启动要求 A 级通行证（测试可 skip_gate）；
  · 只抓 hwnd 指定窗口，不默认全屏；
  · 敏感标题窗口跳过；
  · 全帧不落盘；snapshot 只在显式请求时写临时 JPEG。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from PIL import Image

from agentctl import framecache

EVENT_VERSION = "0.1.0"
DEFAULT_STATE_DIR = Path(
    os.environ.get("AGENTCTL_RETINA_DIR")
    or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgentCtl" / "retina")
)
DEFAULT_SENSITIVE_TITLES = (
    "AgentCtl 授权",
    "AgentCtl 急停",
    "用户账户控制",
    "Windows 安全",
    "凭据",
)

# ── 采集期授权（P1：把「采集」和「每次读取都重新授权」解耦）────────────
# 动机：daemon 启动时校验一次 A 级通行证；此后通行证过期，采集还在跑，
#   但 MCP 读取（ctl_retina_*）会被闸门拒 ⇒ 连续视觉变成「只写不读」。
# 口径：一次授权 = 一段**采集期**。
#   · 采集期凭据落 session.json（受控目录，只记元数据，不含图像）；
#   · 采集期有效 ⇒ daemon 继续采集，且**允许读取已采集的数据**（含取帧）；
#   · 采集期到期 ⇒ daemon **自停**（不越权继续录屏），凭据同时失效；
#   · 采集期凭据**不含新感知**：ctl_shot / ctl_screen / ctl_tree 仍要通行证。
SESSION_FILE_NAME = "session.json"
DEFAULT_SESSION_MINUTES = 120


def session_path(state_dir) -> Path:
    return Path(state_dir) / SESSION_FILE_NAME


def issue_session(state_dir, *, hwnd: int, fps: float, minutes: int,
                  scopes=("A",), source: str = "通行证") -> dict:
    """签发采集期授权凭据（只记元数据）。"""
    now = time.time()
    minutes = max(1, min(int(minutes or DEFAULT_SESSION_MINUTES), 24 * 60))
    data = {
        "issued_at": now,
        "expires_at": now + minutes * 60,
        "minutes": minutes,
        "scopes": list(scopes),
        "hwnd": int(hwnd),
        "fps": float(fps),
        "pid": os.getpid(),
        "source": source,
        "note": "采集期授权：只覆盖**已采集**的数据，不含新感知（截图/控件树仍要通行证）",
        "version": "0.1.0",
    }
    p = session_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return data


def revoke_session(state_dir, reason: str = "") -> bool:
    """撤销采集期凭据（显式停止时调用）。

    ★ Windows 上 unlink 可能撞上「另一个进程正打开该文件读」而被拒
      （PermissionError）⇒ 退避重试几次；读侧只是读，不该把撤销卡死。
    """
    p = session_path(state_dir)
    for attempt in range(5):
        try:
            if p.exists():
                p.unlink()
                return True
            return False
        except Exception:
            if attempt == 4:
                return False
            time.sleep(0.05 * (attempt + 1))
    return False


def session_info(state_dir) -> dict:
    """读采集期凭据并判定是否仍有效（离线可判，不碰屏幕）。"""
    p = session_path(state_dir)
    if not p.exists():
        return {"exists": False, "valid": False, "reason": "没有采集期凭据（daemon 未在采集，或已撤销）"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"exists": True, "valid": False, "reason": "采集期凭据读不出来：%s" % e}
    now = time.time()
    exp = float(data.get("expires_at") or 0)
    pid = int(data.get("pid") or 0)
    alive = bool(pid and _pid_alive(pid))
    valid = bool(exp > now and alive)
    why = "采集期有效" if valid else (
        "采集期已到期" if exp <= now else "daemon 已不在（凭据失效）")
    return {
        "exists": True, "valid": valid, "reason": why,
        "issued_at": data.get("issued_at"), "expires_at": exp,
        "expires": datetime.fromtimestamp(exp).astimezone().isoformat(timespec="seconds") if exp else "",
        "minutes": data.get("minutes"), "scopes": data.get("scopes"),
        "hwnd": data.get("hwnd"), "fps": data.get("fps"), "pid": pid,
        "pid_alive": alive, "source": data.get("source"), "note": data.get("note"),
    }


@dataclass(frozen=True)
class RetinaConfig:
    hwnd: int
    fps: float = 5.0
    ring_seconds: float = 30.0
    max_width: int = 1280
    jpeg_quality: int = 60
    stable_frames: int = 3
    blank_frames: int = 2
    change_min_interval_ms: int = 300
    min_change_ratio: float = 0.001
    max_events: int = 10_000
    max_event_file_bytes: int = 10 * 1024 * 1024
    state_dir: str = str(DEFAULT_STATE_DIR)
    sensitive_titles: tuple[str, ...] = DEFAULT_SENSITIVE_TITLES
    skip_gate: bool = False
    session_minutes: int = DEFAULT_SESSION_MINUTES


@dataclass
class CaptureResult:
    image: Any
    source: str
    ok: bool
    error: str | None = None


@dataclass
class Frame:
    seq: int
    ts: float
    jpeg: bytes
    width: int
    height: int
    source: str
    blank: bool
    scale: float

    def meta(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "width": self.width,
            "height": self.height,
            "source": self.source,
            "blank": self.blank,
            "scale": self.scale,
            "jpeg_bytes": len(self.jpeg),
        }


class FrameRing:
    """按时间淘汰的环形帧缓冲；只存 JPEG 字节，不存 PIL 原图。"""

    def __init__(self, seconds: float = 30.0):
        self.seconds = max(1.0, float(seconds))
        self._items: deque[Frame] = deque()
        self._lock = threading.RLock()

    def put(self, frame: Frame) -> None:
        with self._lock:
            self._items.append(frame)
            cutoff = frame.ts - self.seconds
            while len(self._items) > 1 and self._items[0].ts < cutoff:
                self._items.popleft()

    def latest(self) -> Frame | None:
        with self._lock:
            return self._items[-1] if self._items else None

    def get(self, seq: int) -> Frame | None:
        with self._lock:
            for item in reversed(self._items):
                if item.seq == seq:
                    return item
                if item.seq < seq:
                    break
        return None

    def evict(self, now: float | None = None) -> int:
        with self._lock:
            cutoff = (now if now is not None else time.time()) - self.seconds
            removed = 0
            while len(self._items) > 1 and self._items[0].ts < cutoff:
                self._items.popleft()
                removed += 1
            return removed

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def bytes(self) -> int:
        with self._lock:
            return sum(len(x.jpeg) for x in self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class StabilityGate:
    """把逐帧 diff 变成 change / stable / blank 事件。"""

    def __init__(self, stable_frames: int = 3, change_min_interval_ms: int = 300):
        self.stable_frames = max(1, int(stable_frames))
        self.change_min_interval_ms = max(0, int(change_min_interval_ms))
        self.stable_count = 0
        self.stable_since: float | None = None
        self.stable_emitted = False
        self.last_change_ts = 0.0
        self.blank_streak = 0

    def reset(self) -> None:
        self.stable_count = 0
        self.stable_since = None
        self.stable_emitted = False
        self.blank_streak = 0

    def update(
        self,
        seq: int,
        ts: float,
        changed: bool | None,
        blank: bool,
        bbox: list[int] | None = None,
        ratio: float = 0.0,
        source: str = "client",
    ) -> list[dict]:
        events: list[dict] = []

        def emit(kind: str, stable_for_ms: int = 0) -> None:
            events.append({
                "seq": seq,
                "ts": round(ts, 3),
                "kind": kind,
                "bbox": bbox,
                "ratio": round(float(ratio), 6),
                "stable_for_ms": int(stable_for_ms),
                "version": EVENT_VERSION,
                "source": source,
            })

        if blank:
            self.blank_streak += 1
            self.stable_count = 0
            self.stable_since = None
            self.stable_emitted = False
            # 连续 blank 只报一次，避免事件洪水
            if self.blank_streak == 1:
                emit("blank")
            return events

        self.blank_streak = 0

        if changed is None:
            # 没测出来 ≠ 没变；不发 change，也不把稳定计数清零
            return events

        if changed:
            self.stable_count = 0
            self.stable_since = None
            self.stable_emitted = False
            if (ts - self.last_change_ts) * 1000 >= self.change_min_interval_ms:
                self.last_change_ts = ts
                emit("change")
            return events

        if self.stable_since is None:
            self.stable_since = ts
        self.stable_count += 1
        if self.stable_count >= self.stable_frames and not self.stable_emitted:
            self.stable_emitted = True
            emit("stable", int((ts - self.stable_since) * 1000))
        return events


class RetinaDaemon:
    def __init__(
        self,
        config: RetinaConfig,
        capture_fn: Optional[Callable[[int], CaptureResult]] = None,
        diff_fn: Callable[[Any, Any], dict] = framecache.diff_images,
        blank_fn: Callable[[Any], bool] = framecache.is_blank,
    ):
        self.config = config
        self.capture_fn = capture_fn
        self.diff_fn = diff_fn
        self.blank_fn = blank_fn
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._watch_thread: threading.Thread | None = None
        self._ring = FrameRing(config.ring_seconds)
        self._gate = StabilityGate(config.stable_frames, config.change_min_interval_ms)
        self._events: deque[dict] = deque(maxlen=max(100, int(config.max_events)))
        self._events_dropped = 0
        self._seq = 0
        self._prev_img = None
        self._last_error = ""
        self._fail_streak = 0
        self._degraded = False
        self._last_state_write = 0.0
        self._events_path = Path(config.state_dir) / "events.jsonl"
        self._state_path = Path(config.state_dir) / "state.json"
        self._pid_path = Path(config.state_dir) / "retina.pid"
        self._stop_path = Path(config.state_dir) / "stop.request"
        self._snapshot_req = Path(config.state_dir) / "snapshot.request"
        self._snapshot_resp = Path(config.state_dir) / "snapshot.response"
        self._session: dict = {}
        self._fh = None

    # ── 生命周期 ────────────────────────────────────────────────
    def start(self) -> None:
        if not self.config.skip_gate:
            from agentctl import gate

            try:
                gate.require_any(gate.PERCEIVE, "retina capture", count=False)
            except Exception as e:
                raise RuntimeError("retina 启动需要 A 级通行证：%s" % e) from e
        Path(self.config.state_dir).mkdir(parents=True, exist_ok=True)
        # ★ P1：采集期授权——启动即签发，采集期内允许读取已采集数据；
        #   到期 daemon 自停（不越权继续录屏）。
        self._session = issue_session(
            self.config.state_dir, hwnd=self.config.hwnd, fps=self.config.fps,
            minutes=self.config.session_minutes,
            source="通行证（启动时校验 A 级）" if not self.config.skip_gate else "skip-gate",
        )
        self._stop_path.unlink(missing_ok=True)
        self._snapshot_req.unlink(missing_ok=True)
        self._snapshot_resp.unlink(missing_ok=True)
        self._fh = open(self._events_path, "a", encoding="utf-8")
        self._pid_path.write_text(str(os.getpid()), encoding="utf-8")
        self._watch_thread = threading.Thread(target=self._watch_stop, name="retina-stop", daemon=True)
        self._watch_thread.start()
        self._thread = threading.Thread(target=self.run_loop, name="retina-capture", daemon=True)
        self._thread.start()

    def _watch_stop(self) -> None:
        while not self._stop.is_set():
            if self._stop_path.exists():
                self._stop.set()
                break
            time.sleep(0.2)

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._stop_path.unlink(missing_ok=True)
        # 采集结束 ⇒ 采集期凭据同时失效（读取权随之收回）
        revoke_session(self.config.state_dir, "daemon stopped")
        for t in (self._watch_thread, self._thread):
            if t and t.is_alive():
                t.join(timeout=timeout)
        try:
            if self._fh:
                self._fh.flush()
                self._fh.close()
        finally:
            self._fh = None
        try:
            self._pid_path.unlink(missing_ok=True)
        except Exception:
            pass

    # ── 采集 ────────────────────────────────────────────────────
    def _capture(self) -> CaptureResult:
        if self.capture_fn:
            try:
                return self.capture_fn(self.config.hwnd)
            except Exception as e:
                return CaptureResult(None, "client", False, "%s: %s" % (type(e).__name__, e))
        try:
            import win32gui

            if win32gui.IsIconic(int(self.config.hwnd)):
                return CaptureResult(None, "client", False, "window minimized")
        except Exception:
            pass
        try:
            img = framecache.capture_client(self.config.hwnd)
            if img is None:
                return CaptureResult(None, "client", False, "capture_client returned None")
            return CaptureResult(img, "client", True)
        except Exception as e:
            return CaptureResult(None, "client", False, "%s: %s" % (type(e).__name__, e))

    def _sensitive(self) -> bool:
        try:
            import win32gui

            title = win32gui.GetWindowText(int(self.config.hwnd)) or ""
        except Exception:
            # 无法确认标题时 fail-closed：跳过这一帧，不抓不确定的窗口
            return True
        return any(x and x in title for x in self.config.sensitive_titles)

    def _downscale(self, img: Image.Image) -> tuple[Image.Image, float]:
        max_w = max(320, int(self.config.max_width))
        if img.width <= max_w:
            return img, 1.0
        scale = max_w / float(img.width)
        h = max(1, int(round(img.height * scale)))
        return img.resize((max_w, h), Image.LANCZOS), scale

    def _encode(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=max(20, min(90, int(self.config.jpeg_quality))), optimize=False)
        return buf.getvalue()

    def process_frame(self, result: CaptureResult) -> list[dict]:
        """处理一帧；测试可直接调用，无需启动线程。"""
        if not result.ok or result.image is None:
            with self._lock:
                self._fail_streak += 1
                self._last_error = result.error or "capture failed"
                # 失败期间不沿用旧基线，也不让稳定计数跨失败继续累加
                self._prev_img = None
                self._gate.reset()
                if self._fail_streak >= 10:
                    self._degraded = True
                self._write_state_locked()
            return []

        img = result.image
        with self._lock:
            self._seq += 1
            seq = self._seq
            ts = time.time()
            self._fail_streak = 0
            self._degraded = False
            self._last_error = ""

            blank = bool(self.blank_fn(img))
            diff = self.diff_fn(self._prev_img, img) if self._prev_img is not None else {
                "changed": False, "ratio": 0.0, "bbox": None,
                "说明": "首帧作为稳定基线",
            }
            changed = diff.get("changed")
            ratio = float(diff.get("ratio") or 0.0)
            # 微小动画/光标/抗锯齿不单独触发事件，也不打断稳定态
            if changed is True and ratio < float(self.config.min_change_ratio):
                changed = False
            bbox_raw = diff.get("bbox")
            bbox = None
            if bbox_raw:
                x0, y0, x1, y1 = bbox_raw
                bbox = [int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)]
            small, scale = self._downscale(img)
            events = self._gate.update(
                seq, ts, changed, blank, bbox, ratio,
                source=result.source,
            )
            for event in events:
                event["scale"] = round(scale, 4)
                if len(self._events) >= self._events.maxlen:
                    self._events_dropped += 1
                self._events.append(event)
                self._append_event(event)
            frame = Frame(
                seq=seq, ts=ts, jpeg=self._encode(small),
                width=small.width, height=small.height,
                source=result.source, blank=blank, scale=scale,
            )
            self._ring.put(frame)
            self._prev_img = img
            self._write_state_locked()
            return events

    def _serve_snapshot_request(self) -> None:
        """文件式 IPC：MCP 写 snapshot.request，daemon 把最新/指定帧写到受控目录。"""
        if not self._snapshot_req.exists():
            return
        try:
            req = json.loads(self._snapshot_req.read_text(encoding="utf-8"))
        except Exception:
            try:
                self._snapshot_req.unlink(missing_ok=True)
            except Exception:
                pass
            return
        rid = str(req.get("id") or "")
        seq = req.get("seq")
        with self._lock:
            frame = self._ring.get(int(seq)) if seq not in (None, "") else self._ring.latest()
            if frame is None:
                resp = {"id": rid, "ok": False, "error": "没有匹配的帧"}
            else:
                outdir = Path(self.config.state_dir) / "snapshots"
                outdir.mkdir(parents=True, exist_ok=True)
                path = outdir / ("retina-%06d.jpg" % frame.seq)
                try:
                    path.write_bytes(frame.jpeg)
                    resp = {"id": rid, "ok": True, "seq": frame.seq,
                            "path": str(path), "width": frame.width,
                            "height": frame.height, "ts": frame.ts,
                            "scale": frame.scale}
                    # 只保留最近 20 张显式 snapshot
                    files = sorted(outdir.glob("retina-*.jpg"))
                    for old in files[:-20]:
                        old.unlink(missing_ok=True)
                except Exception as e:
                    resp = {"id": rid, "ok": False, "error": "写 snapshot 失败：%s" % e}
        try:
            tmp = self._snapshot_resp.with_suffix(".response.tmp")
            tmp.write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._snapshot_resp)
        except Exception:
            pass
        try:
            self._snapshot_req.unlink(missing_ok=True)
        except Exception:
            pass

    def _append_event(self, event: dict) -> None:
        if not self._fh:
            return
        try:
            limit = int(self.config.max_event_file_bytes or 0)
            if limit > 0 and self._fh.tell() >= limit:
                self._fh.flush()
                self._fh.close()
                old = self._events_path.with_name("events.1.jsonl")
                try:
                    os.replace(self._events_path, old)
                except Exception:
                    pass
                self._fh = open(self._events_path, "a", encoding="utf-8")
            self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception as e:
            self._last_error = "events.jsonl 写入失败：%s" % e

    def _session_state(self) -> dict:
        """state.json 里的采集期快照（**不读文件**，热路径无 I/O）。"""
        s = dict(self._session or {})
        exp = float(s.get("expires_at") or 0)
        s["valid"] = bool(exp and time.time() < exp and _pid_alive(int(s.get("pid") or 0)))
        s["expires"] = (datetime.fromtimestamp(exp).astimezone().isoformat(timespec="seconds")
                        if exp else "")
        return s

    def _write_state_locked(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_state_write < 1.0:
            return
        self._last_state_write = now
        latest = self._ring.latest()
        state = {
            "updated": round(now, 3),
            "pid": os.getpid(),
            "hwnd": self.config.hwnd,
            "fps": self.config.fps,
            "seq": self._seq,
            "degraded": self._degraded,
            "last_error": self._last_error,
            "ring": {
                "frames": len(self._ring),
                "seconds": self.config.ring_seconds,
                "jpeg_bytes": self._ring.bytes(),
            },
            "latest": latest.meta() if latest else None,
            "stable": {
                "count": self._gate.stable_count,
                "since": self._gate.stable_since,
                "emitted": self._gate.stable_emitted,
            },
            "events": len(self._events),
            "session": self._session_state(),
        }
        tmp_path = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix="state.", suffix=".tmp", dir=str(self._state_path.parent))
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(state, ensure_ascii=False, indent=1))
            os.replace(tmp_path, self._state_path)
            tmp_path = None
        except Exception as e:
            self._last_error = "state.json 写入失败：%s" % e
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def run_loop(self) -> None:
        interval = 1.0 / max(0.2, float(self.config.fps))
        last_session_check = 0.0
        while not self._stop.is_set():
            if self._stop_path.exists():
                self._stop.set()
                break
            now = time.time()
            # ★ P1：采集期到期 ⇒ 自停（不越权继续录屏），并留一条事件
            #   用**内存里的**到期时间判定（热路径不读文件 ⇒ 不会与读侧
            #   抢文件句柄）；另外每 30 帧查一次凭据是否被外部撤销。
            if now - last_session_check >= 1.0:
                last_session_check = now
                exp = float((self._session or {}).get("expires_at") or 0)
                revoked = (self._seq % 30 == 0) and not session_path(self.config.state_dir).exists()
                expired = bool(exp and now > exp)
                if expired or revoked:
                    reason = "采集期已到期" if expired else "采集期凭据已被撤销"
                    with self._lock:
                        self._last_error = "采集期授权失效，daemon 自停：%s" % reason
                        ev = {
                            "seq": self._seq + 1, "ts": round(now, 3),
                            "kind": "session_expired", "bbox": None, "ratio": 0.0,
                            "stable_for_ms": 0, "version": EVENT_VERSION, "source": "client",
                            "reason": reason,
                            "session_expires": (self._session or {}).get("expires_at"),
                        }
                        self._events.append(ev)
                        self._append_event(ev)
                        self._write_state_locked(force=True)
                    self._stop.set()
                    break
            t0 = time.time()
            if self._sensitive():
                time.sleep(interval)
                continue
            result = self._capture()
            self.process_frame(result)
            self._serve_snapshot_request()
            elapsed = time.time() - t0
            self._stop.wait(max(0.01, interval - elapsed))

    # ── 查询 ────────────────────────────────────────────────────
    def snapshot(self, jpeg_path: str | None = None) -> dict:
        with self._lock:
            latest = self._ring.latest()
            if latest is None:
                return {"ok": False, "error": "还没有帧"}
            meta = latest.meta()
            if jpeg_path:
                Path(jpeg_path).parent.mkdir(parents=True, exist_ok=True)
                Path(jpeg_path).write_bytes(latest.jpeg)
                meta["jpeg_path"] = jpeg_path
            return meta

    def changes(self, since_seq: int = 0) -> dict:
        with self._lock:
            events = [e for e in self._events if int(e.get("seq") or 0) > int(since_seq)]
            oldest = int(self._events[0]["seq"]) if self._events else 0
            return {
                "since_seq": int(since_seq),
                "oldest_seq": oldest,
                "truncated": bool(self._events_dropped and int(since_seq) < oldest - 1),
                "events": events,
            }

    def status(self) -> dict:
        with self._lock:
            latest = self._ring.latest()
            return {
                "ok": True,
                "pid": os.getpid(),
                "hwnd": self.config.hwnd,
                "fps": self.config.fps,
                "seq": self._seq,
                "degraded": self._degraded,
                "last_error": self._last_error,
                "ring": {
                    "frames": len(self._ring),
                    "seconds": self.config.ring_seconds,
                    "jpeg_bytes": self._ring.bytes(),
                },
                "latest": latest.meta() if latest else None,
                "events": len(self._events),
                "session": session_info(self.config.state_dir),
            }


# ── CLI ────────────────────────────────────────────────────────
def _state_dir(value: str | None) -> Path:
    return Path(value) if value else DEFAULT_STATE_DIR


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes

            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _clean_stale_pid(state_dir: Path) -> bool:
    pid_path = state_dir / "retina.pid"
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        pid_path.unlink(missing_ok=True)
        return True
    if _pid_alive(pid):
        return False
    pid_path.unlink(missing_ok=True)
    return True


def _read_status(state_dir: Path) -> dict:
    p = state_dir / "state.json"
    if not p.exists():
        return {"ok": False, "error": "state.json 不存在；daemon 没启动？"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _cmd_start(args) -> int:
    state_dir = _state_dir(args.state_dir)
    _clean_stale_pid(state_dir)
    cfg = RetinaConfig(
        hwnd=int(args.hwnd), fps=float(args.fps), ring_seconds=float(args.seconds),
        max_width=int(args.max_width), jpeg_quality=int(args.quality),
        stable_frames=int(args.stable_frames), min_change_ratio=float(args.min_ratio),
        state_dir=str(_state_dir(args.state_dir)), skip_gate=bool(args.skip_gate),
        session_minutes=int(getattr(args, "session_minutes", DEFAULT_SESSION_MINUTES)),
    )
    if getattr(args, "daemon", False):
        state_dir = _state_dir(args.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        pid_path = state_dir / "retina.pid"
        if pid_path.exists():
            try:
                old_pid = int(pid_path.read_text(encoding="utf-8").strip())
            except Exception:
                old_pid = 0
            if old_pid and _pid_alive(old_pid):
                print(json.dumps({"ok": False, "error": "retina daemon 已在运行", "pid": old_pid}, ensure_ascii=False))
                return 1
        log = state_dir / "daemon.log"
        cmd = [sys.executable, "-m", "agentctl.retina", "_run",
               "--hwnd", str(cfg.hwnd), "--fps", str(cfg.fps),
               "--seconds", str(cfg.ring_seconds), "--max-width", str(cfg.max_width),
               "--quality", str(cfg.jpeg_quality), "--stable-frames", str(cfg.stable_frames),
               "--min-ratio", str(cfg.min_change_ratio), "--state-dir", str(state_dir),
               "--session-minutes", str(cfg.session_minutes)]
        if cfg.skip_gate:
            cmd.append("--skip-gate")
        fh = open(log, "a", encoding="utf-8")
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=fh, stdin=subprocess.DEVNULL, creationflags=flags)
        except Exception as e:
            fh.close()
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return 1
        time.sleep(1.0)
        fh.close()
        if proc.poll() is not None:
            try:
                tail = log.read_text(encoding="utf-8", errors="replace")[-1200:]
            except Exception:
                tail = ""
            print(json.dumps({"ok": False, "error": "daemon 启动后立即退出", "log": str(log), "tail": tail}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "daemon": True, "pid": proc.pid, "state_dir": str(state_dir), "log": str(log)}, ensure_ascii=False))
        return 0
    d = RetinaDaemon(cfg)
    d.start()
    try:
        # 不只看 KeyboardInterrupt：stop.request 由 watchdog 置 _stop，
        # run_loop 会退出；主线程也必须跟着退出，否则进程会挂住。
        while not d._stop.is_set() and d._thread and d._thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        d.stop()
    return 0


def _cmd_status(args) -> int:
    state_dir = _state_dir(args.state_dir)
    state = _read_status(state_dir)
    pid_path = state_dir / "retina.pid"
    alive = False
    if pid_path.exists():
        try:
            alive = _pid_alive(int(pid_path.read_text(encoding="utf-8").strip()))
        except Exception:
            alive = False
    if state.get("ok") is not False and not alive:
        state = {
            "ok": False,
            "stale": True,
            "error": "retina.pid 不存在或进程已退出；这是上次留下的 state.json",
            "last_state": state,
        }
    print(json.dumps(state, ensure_ascii=False, indent=1))
    return 0


def _cmd_changes(args) -> int:
    state_dir = _state_dir(args.state_dir)
    path = state_dir / "events.jsonl"
    events = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(event.get("seq") or 0) > int(args.since):
                events.append(event)
    print(json.dumps({"since_seq": int(args.since), "events": events}, ensure_ascii=False, indent=1))
    return 0


def _cmd_stop(args) -> int:
    state_dir = _state_dir(args.state_dir)
    pid_path = state_dir / "retina.pid"
    if not pid_path.exists():
        print(json.dumps({"ok": False, "error": "retina.pid 不存在"}, ensure_ascii=False))
        return 1
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        if not _pid_alive(pid):
            pid_path.unlink(missing_ok=True)
            print(json.dumps({"ok": False, "error": "进程已退出，已清理 stale pid"}, ensure_ascii=False))
            return 1
        # 先请求优雅退出：daemon 在采集循环里检查 stop.request
        (state_dir / "stop.request").write_text("stop", encoding="utf-8")
        for _ in range(30):
            time.sleep(0.1)
            if not _pid_alive(pid):
                pid_path.unlink(missing_ok=True)
                print(json.dumps({"ok": True, "stopped": pid, "graceful": True}, ensure_ascii=False))
                return 0
        # 最后手段：Windows taskkill / 其它平台 SIGTERM
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        time.sleep(0.5)
        alive = _pid_alive(pid)
        if not alive:
            pid_path.unlink(missing_ok=True)
        try:
            (state_dir / "stop.request").unlink(missing_ok=True)
        except Exception:
            pass
        print(json.dumps({"ok": not alive, "stopped": pid, "graceful": False}, ensure_ascii=False))
        return 0 if not alive else 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


def _cmd_snapshot(args) -> int:
    # 单次抓取：不依赖 daemon，适合临时取证；仍需调用方自行确认窗口可读。
    try:
        img = framecache.capture_client(int(args.hwnd))
        if img is None:
            print(json.dumps({"ok": False, "error": "capture_client returned None"}, ensure_ascii=False))
            return 1
        path = Path(args.jpeg)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "JPEG", quality=int(args.quality))
        print(json.dumps({"ok": True, "jpeg": str(path), "width": img.width, "height": img.height}, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentctl.retina", description="L0-lite 连续视觉视网膜")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", help="启动采集")
    p.add_argument("--hwnd", type=int, required=True)
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--max-width", type=int, default=1280)
    p.add_argument("--quality", type=int, default=60)
    p.add_argument("--stable-frames", type=int, default=3)
    p.add_argument("--min-ratio", type=float, default=0.001)
    p.add_argument("--state-dir", default=None)
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--skip-gate", action="store_true")
    p.add_argument("--session-minutes", type=int, default=DEFAULT_SESSION_MINUTES,
                   help="采集期授权分钟数（到期 daemon 自停；上限 1440）")
    p.set_defaults(func=_cmd_start)

    p = sub.add_parser("_run", help=argparse.SUPPRESS)
    p.add_argument("--hwnd", type=int, required=True)
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--max-width", type=int, default=1280)
    p.add_argument("--quality", type=int, default=60)
    p.add_argument("--stable-frames", type=int, default=3)
    p.add_argument("--min-ratio", type=float, default=0.001)
    p.add_argument("--state-dir", default=None)
    p.add_argument("--skip-gate", action="store_true")
    p.add_argument("--session-minutes", type=int, default=DEFAULT_SESSION_MINUTES)
    p.set_defaults(func=_cmd_start)

    p = sub.add_parser("status", help="读 state.json")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("changes", help="读 events.jsonl")
    p.add_argument("--since", type=int, default=0)
    p.add_argument("--state-dir", default=None)
    p.set_defaults(func=_cmd_changes)

    p = sub.add_parser("stop", help="按 retina.pid 停止")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(func=_cmd_stop)

    p = sub.add_parser("snapshot", help="单次抓取并写临时 JPEG")
    p.add_argument("--hwnd", type=int, required=True)
    p.add_argument("--jpeg", required=True)
    p.add_argument("--quality", type=int, default=80)
    p.set_defaults(func=_cmd_snapshot)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
