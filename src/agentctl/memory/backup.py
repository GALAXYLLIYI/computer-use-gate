# -*- coding: utf-8 -*-
"""agentctl.memory.backup —— episode 库在线备份（2026-11-03）

为什么单独一层：
  · 记忆库是 SQLite WAL 模式，直接 copy 文件可能拿到半截 WAL；
    用 sqlite3 的在线 backup API 才能拿到一致快照。
  · 备份必须带 manifest（sha256/条数/schema/完整性），否则“备份了”无法对账。
  · 保留策略只清理自动备份，不碰手工 baseline。

CLI:
    python -m agentctl.memory backup [--keep 14] [--out DIR]
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
from typing import Optional

DEFAULT_KEEP = 14


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(path: str) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = {
            "episodes": int(con.execute("select count(*) from episodes").fetchone()[0]),
            "segments": int(con.execute("select count(*) from segments").fetchone()[0]),
            "workflows": int(con.execute("select count(*) from workflows").fetchone()[0]),
            "integrity": str(con.execute("pragma integrity_check").fetchone()[0]),
        }
        try:
            out["schema_version"] = str(
                con.execute("select v from meta where k='schema_version'").fetchone()[0]
            )
        except Exception:
            out["schema_version"] = ""
        return out
    finally:
        con.close()


def backup_memory(db_path: str, *, keep: int = DEFAULT_KEEP,
                  out_dir: Optional[str] = None) -> dict:
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"记忆库不存在：{db_path}")
    backup_dir = os.path.abspath(
        out_dir or os.path.join(os.path.dirname(db_path), "backups")
    )
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"episodes-{ts}.db")

    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    info = _counts(dest)
    if info["integrity"] != "ok":
        # 坏备份不留在正式目录，避免以后误恢复
        bad = dest + ".bad"
        os.replace(dest, bad)
        raise RuntimeError(f"备份完整性校验失败：{info['integrity']}（已移至 {bad}）")

    record = {
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": db_path,
        "file": os.path.basename(dest),
        "bytes": os.path.getsize(dest),
        "sha256": _sha256(dest),
        **info,
    }
    manifest = os.path.join(backup_dir, "manifest.jsonl")
    with open(manifest, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    removed = []
    autos = sorted(
        [os.path.join(backup_dir, n) for n in os.listdir(backup_dir)
         if n.startswith("episodes-") and n.endswith(".db")
         and not n.startswith("episodes-baseline-")],
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for old in autos[max(0, int(keep)):]:
        try:
            os.remove(old)
            removed.append(os.path.basename(old))
        except OSError:
            pass

    return {"backup": record, "backup_dir": backup_dir,
            "keep": int(keep), "removed": removed}
