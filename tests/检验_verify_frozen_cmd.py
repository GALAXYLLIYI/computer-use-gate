# -*- coding: utf-8 -*-
"""回归：冻结版独立验证必须走 `AgentCtl.exe legacy <script>`。

背景（2026-11-08 真机）：
    冻结版里 sys.executable 是 AgentCtl.exe，不是 python.exe。
    旧 _cl_run 拼出 `AgentCtl.exe -X utf8 验动作.py check ...`，
    实际跑成了 CLI 子命令，打印 cli.py 帮助并返回 4 —— 动作已经 met，
    独立验证却永远 unknown。这个脚本只测命令拼装，不跑真 GUI。
"""
from __future__ import annotations

import sys

from agentctl import core


def main() -> int:
    old = getattr(sys, "frozen", None)
    try:
        if hasattr(sys, "frozen"):
            del sys.frozen
        dev = core._cl_cmd("x.py", ["check"])
        assert dev[1:3] == ["-X", "utf8"], dev
        assert dev[3:] == ["x.py", "check"], dev

        sys.frozen = True
        frozen = core._cl_cmd("x.py", ["check"])
        assert frozen[1:4] == ["legacy", "x.py", "check"], frozen
        assert frozen[-1] == "check", frozen

        print("OK")
        print("dev   :", dev)
        print("frozen:", frozen)
        return 0
    finally:
        if old is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = old


if __name__ == "__main__":
    raise SystemExit(main())
