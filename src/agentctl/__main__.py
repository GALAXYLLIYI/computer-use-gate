# -*- coding: utf-8 -*-
"""Allow `python -m agentctl` to behave like the `agentctl` console script."""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
