# -*- coding: utf-8 -*-
"""screen_ready 对小原生窗误判的回归（2026-11-16 §4.5.3）。

520×430 自绘窗、10~14 个节点、33~50ms 采集 —— 那本来就是它的完整树，
旧判定③「采集过快而节点极少（外壳特征）」不问窗口类别，把它误判成外壳：
白吃 2 次暖机重试（+800ms）+ 一条假「本屏可能未热」blind_spot。
修复后：③ 只对网页类生效；原生窗口靠 ①（<上次 60%）②（可交互 0 个）兜底。
"""
import agentctl.core as core

_CLIENT = [0, 0, 520, 430]   # 客户区非零（520×430，与实测靶窗同款）


def _nodes(n_btn, n_text):
    """造一棵小树：n_btn 个可交互按钮 + n_text 个有字文本（共 n_btn+n_text+0 个）。"""
    nodes = []
    for i in range(n_btn):
        nodes.append({"type": "ButtonControl", "name": "按钮%d" % (i + 1)})
    for i in range(n_text):
        nodes.append({"type": "TextControl", "name": "说明%d" % (i + 1)})
    return nodes


def test_small_native_tree_fast_scan_is_ready():
    """原生窗（is_web=False）小树 + 快采集 ⇒ ready=True，不进暖机。"""
    ready, why = core._screen_ready(
        _nodes(8, 4), {"视口": _CLIENT},
        elapsed_ms=40.0, prev_nodes=0, is_web=False)
    assert ready is True, why
    assert why == []


def test_web_window_same_shape_still_not_ready():
    """网页窗同条件仍 False：③ 与 ③b（可报对象<40）都该点名。"""
    ready, why = core._screen_ready(
        _nodes(8, 4), {"视口": _CLIENT},
        elapsed_ms=40.0, prev_nodes=0, is_web=True)
    assert ready is False
    assert any("外壳特征" in w for w in why)
    assert any("网页类" in w for w in why)


def test_native_zero_interactive_still_not_ready():
    """② 兜底不许失守：原生窗一屏没有一个能点的，仍要报未热。"""
    ready, why = core._screen_ready(
        _nodes(0, 12), {"视口": _CLIENT},
        elapsed_ms=40.0, prev_nodes=0, is_web=False)
    assert ready is False
    assert any("可交互节点 0 个" in w for w in why)


def test_native_shrink_still_not_ready():
    """① 兜底不许失守：节点数 < 上次 60% 仍判未热。"""
    ready, why = core._screen_ready(
        _nodes(8, 4), {"视口": _CLIENT},
        elapsed_ms=40.0, prev_nodes=100, is_web=False)
    assert ready is False
    assert any("明显少于" in w for w in why)
