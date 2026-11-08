# -*- coding: utf-8 -*-
"""Sync the public tool contract into the Python package.

``contract/tools.json`` is the source of truth.  A wheel install does not have
the repository root, so the package carries a copy under
``src/agentctl/contract/tools.json``.  Run this after editing the contract and
before building a release.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "contract" / "tools.json"
DST = ROOT / "src" / "agentctl" / "contract" / "tools.json"


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"missing contract: {SRC}")
    data = json.loads(SRC.read_text(encoding="utf-8"))
    tools = data.get("tools") or []
    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, DST)
    print(f"synced {SRC} -> {DST}")
    print(f"tools={len(tools)} bytes={DST.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
