# -*- coding: utf-8 -*-
"""agentctl.memory.strategy —— 检索/反馈策略评测与推荐（2026-11-04）

为什么先做策略层：
  GLM-5.3-Flash 是托管模型，不能微调；Ollama 只做推理。
  7 小时内最稳的“训练”是**调记忆检索策略**：floor / k 的可解释扫参，
  用真实查询集评测，写 strategy_state.json，不碰 episodes 内容。

2026-11-04 GLM-5.3-Flash 审核后修正：
  · tune 与 holdout 拆集，避免“调参/验收同源”导致 hit_rate=1.0 饱和
  · 公式权重显式写进 SCORE_WEIGHTS，并输出到 state
  · holdout 只在晋级评审时跑，不参与扫参

指标：
  hit_rate    有命中的查询比例
  diversity   命中里 (obs前48字, outcome) 去重后的比例
  provenance  带 id/t/session_id 的命中比例
  subject_ok  是否全部落在 agent 仓
  avg_hits    平均命中数
  score       加权总分
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

__all__ = [
    "TUNE_QUERIES",
    "HOLDOUT_QUERIES",
    "SCORE_WEIGHTS",
    "DEFAULT_QUERIES",
    "tune",
]

# 调参集：只用于 floor/k 扫参，不参与晋级验收
TUNE_QUERIES = [
    "重验 复核 突破 Sharpe 稳健带 结论",
    "突破 参数 扫描 稳健带 IS OOS 显著性",
    "板块 动量 分组 白酒 金融 新能源 能源",
    "月度效应 季节 2月 趋势态 多头 空头",
    "动量 轮动 延续 反转 上月最强",
    "训练 数据 拒答 幻觉 门禁",
    "记忆 召回 分仓 subject 污染",
    "备份 恢复 一致性 WAL",
    "Ollama 显存 训练 周期",
    "OpenCode 面板 代理 剪贴板",
]

# 验收集：只在晋级评审时跑，扫参阶段不可见
HOLDOUT_QUERIES = [
    "训练页 Ollama 模型 显存 训练路径 怎么看",
    "ZCode 独立审核 GLM-5.3-Flash 额度 401",
    "知识树 理论图谱 节点 分类 筛选",
    "episodes 去重 合并 recurrences segments 重建",
    "OpenCode 面板 白屏 iframe 代理 剪贴板",
    "训练周期 预检 跳过 新数据 不足",
    "策略 floor k 召回 命中率 多样性 出处",
    "备份 manifest sha256 保留 14 份 恢复",
    "subject 分仓 human agent 污染",
    "夜间循环 STOP 文件 重启 PID 心跳",
]

# 兼容旧调用
DEFAULT_QUERIES = TUNE_QUERIES

SCORE_WEIGHTS = {
    "hit_rate": 0.35,
    "diversity": 0.25,
    "provenance": 0.20,
    "subject_ok": 0.10,
    "avg_hits": 0.10,
}


def _load_queries(path: Optional[str], fallback: list[str]) -> list[str]:
    if not path or not os.path.isfile(path):
        return list(fallback)
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    line = str(obj.get("query") or obj.get("text") or "").strip()
            except json.JSONDecodeError:
                pass
            if line:
                out.append(line)
    return out or list(fallback)


def _evaluate(store: Any, queries: list[str], floor: float, k: int) -> dict:
    from agentctl.memory.recall import recall

    total_hits = 0
    hit_queries = 0
    unique = set()
    provenance = 0
    subject_ok = 0
    total = 0
    latencies = []
    for q in queries:
        import time
        t0 = time.perf_counter()
        res = recall(store, q, k=k, subject="agent", floor=floor)
        latencies.append((time.perf_counter() - t0) * 1000)
        hits = res.get("hits") or []
        if hits:
            hit_queries += 1
        for h in hits:
            total += 1
            total_hits += 1
            obs = str(h.get("obs") or "")[:48]
            unique.add((obs, h.get("outcome")))
            if h.get("id") is not None and h.get("t") and h.get("session_id"):
                provenance += 1
            if (h.get("subject") or "agent") == "agent":
                subject_ok += 1
    n_q = max(1, len(queries))
    hit_rate = hit_queries / n_q
    diversity = (len(unique) / total) if total else 0.0
    prov = (provenance / total) if total else 0.0
    subj = (subject_ok / total) if total else 0.0
    avg_hits = total / n_q
    score = (
        SCORE_WEIGHTS["hit_rate"] * hit_rate
        + SCORE_WEIGHTS["diversity"] * diversity
        + SCORE_WEIGHTS["provenance"] * prov
        + SCORE_WEIGHTS["subject_ok"] * subj
        + SCORE_WEIGHTS["avg_hits"] * min(avg_hits / 5.0, 1.0)
    )
    return {
        "floor": floor,
        "k": k,
        "score": round(score, 4),
        "hit_rate": round(hit_rate, 4),
        "diversity": round(diversity, 4),
        "provenance": round(prov, 4),
        "subject_ok": round(subj, 4),
        "avg_hits": round(avg_hits, 3),
        "queries": len(queries),
        "total_hits": total_hits,
        "avg_latency_ms": round(sum(latencies) / n_q, 1),
    }


def tune(
    store: Any,
    *,
    query_file: Optional[str] = None,
    holdout_file: Optional[str] = None,
) -> dict:
    tune_queries = _load_queries(query_file, TUNE_QUERIES)
    holdout_queries = _load_queries(holdout_file, HOLDOUT_QUERIES)
    configs = []
    for floor in (0.05, 0.10, 0.15, 0.20):
        for k in (3, 5, 8):
            configs.append(_evaluate(store, tune_queries, floor, k))
    best = max(configs, key=lambda x: x["score"])
    holdout = _evaluate(store, holdout_queries, best["floor"], best["k"])
    state = {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "query_file": query_file,
        "holdout_file": holdout_file,
        "tune_queries": tune_queries,
        "holdout_queries": holdout_queries,
        "score_weights": SCORE_WEIGHTS,
        "best": best,
        "holdout": holdout,
        "gate": {
            "holdout_score": holdout["score"],
            "holdout_hit_rate": holdout["hit_rate"],
            "holdout_diversity": holdout["diversity"],
            "note": "晋级只看 holdout；tune 集不参与验收",
        },
        "history": configs,
        "note": "只评测，不改 episodes；apply 由宿主人审后执行",
    }
    out = os.path.join(os.path.dirname(os.path.abspath(store.db_path)), "strategy_state.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    return {"state_path": out, **state}
