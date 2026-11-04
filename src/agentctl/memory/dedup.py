# -*- coding: utf-8 -*-
"""agentctl.memory.dedup —— 历史重复 episode 合并（2026-11-03）

背景：
  v5 去重上线前，循环把同一条观测写成了成百上千行；真库 10,679 行里
  9,973 行落在 361 个 dedup_key 重复组里（最大一组 1,807 行）。
  v5 之后新写入已合并，但历史行仍在污染检索与统计。

合并口径（与 intake._merge_into 一致）：
  · 保留最早一行的 id / t / subject / source / actor / session
  · recurrences 累加
  · obs / action / result / outcome / verify / text / embed 取最新一行（结论演进）
  · 删除其余行及 vec_episodes 影子行
  · 同步更新 segments.ep_ids / n_ep / first_ep / last_ep

安全边界（2026-11-04，GLM-5.3-Flash 审核后补）：
  · 同一 dedup_key 组内 subject / outcome 出现多值 ⇒ 拒绝合并，写
    dedup_conflicts.jsonl，保留原行，交人审
  · actor 多值（常见于历史行缺 actor 被写成 unknown）不拒绝合并：
    取最新非空 actor，并写 dedup_conflicts.jsonl 留痕
  · dry-run 也报告冲突数，不只看重复组数
  · 合并后 outcome 与 result 同源（都取最新），避免“结果新、结论旧”
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

__all__ = ["dedup_memory"]


def _chunks(items: list[int], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def dedup_memory(store: Any, *, dry_run: bool = False) -> dict:
    conn = store.conn
    groups = conn.execute(
        "SELECT dedup_key, COUNT(*) AS c FROM episodes "
        "WHERE COALESCE(dedup_key,'') <> '' "
        "GROUP BY dedup_key HAVING c > 1 ORDER BY c DESC"
    ).fetchall()
    total_groups = len(groups)
    total_rows = sum(int(g["c"]) for g in groups)
    conflict_rows = conn.execute(
        "SELECT dedup_key, COUNT(*) AS c, "
        "COUNT(DISTINCT subject) AS subjects, COUNT(DISTINCT outcome) AS outcomes "
        "FROM episodes WHERE COALESCE(dedup_key,'') <> '' "
        "GROUP BY dedup_key HAVING c > 1 "
        "AND (subjects > 1 OR outcomes > 1)"
    ).fetchall()
    actor_rows = conn.execute(
        "SELECT dedup_key, COUNT(DISTINCT actor) AS actors "
        "FROM episodes WHERE COALESCE(dedup_key,'') <> '' "
        "GROUP BY dedup_key HAVING actors > 1"
    ).fetchall()
    if dry_run:
        return {
            "dry_run": True,
            "groups": total_groups,
            "rows": total_rows,
            "would_remove": total_rows - total_groups,
            "conflict_groups": len(conflict_rows),
            "conflict_keys": [str(r["dedup_key"]) for r in conflict_rows[:20]],
            "actor_conflict_groups": len(actor_rows),
            "actor_conflict_keys": [str(r["dedup_key"]) for r in actor_rows[:20]],
        }

    conflict_path = os.path.join(
        os.path.dirname(os.path.abspath(store.db_path)), "dedup_conflicts.jsonl"
    )
    removed = 0
    merged = 0
    conflicts = 0
    actor_conflicts = 0
    mapping: dict[int, int] = {}
    try:
        for g in groups:
            key = str(g["dedup_key"])
            rows = conn.execute(
                "SELECT id, t, kind, subject, source, actor, session_id, screen_version, "
                "obs, action, result, outcome, verify, text, embed, recurrences "
                "FROM episodes WHERE dedup_key = ? ORDER BY id",
                (key,),
            ).fetchall()
            if len(rows) < 2:
                continue
            subjects = {str(r["subject"]) for r in rows if str(r["subject"] or "")}
            outcomes = [str(r["outcome"]) for r in rows if str(r["outcome"] or "")]
            raw_actors = [str(r["actor"]) for r in rows if str(r["actor"] or "")]
            known_actors = [a for a in raw_actors if a.lower() != "unknown"]
            if len(subjects) > 1 or len(set(outcomes)) > 1:
                conflicts += 1
                with open(conflict_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "dedup_key": key,
                        "rows": len(rows),
                        "subjects": sorted(subjects),
                        "outcomes": sorted(set(outcomes)),
                        "actors": sorted(set(raw_actors)),
                        "ids": [int(r["id"]) for r in rows],
                        "action": "kept_all_for_human_review",
                    }, ensure_ascii=False) + "\n")
                continue
            keep = rows[0]
            latest = rows[-1]
            keep_id = int(keep["id"])
            # actor：优先最新“已知 actor”，unknown 只在没有已知值时兜底
            actor = (
                known_actors[-1]
                if known_actors
                else (raw_actors[-1] if raw_actors else (keep["actor"] or ""))
            )
            if len(set(raw_actors)) > 1:
                actor_conflicts += 1
                with open(conflict_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "dedup_key": key,
                        "rows": len(rows),
                        "actors": sorted(set(raw_actors)),
                        "chosen_actor": actor,
                        "action": "merged_with_latest_known_actor",
                    }, ensure_ascii=False) + "\n")
            recurrences = sum(int(r["recurrences"] or 1) for r in rows)
            # outcome：优先最新非空，避免“结果新、结论空”
            outcome = outcomes[-1] if outcomes else latest["outcome"]
            conn.execute(
                "UPDATE episodes SET recurrences = ?, actor = ?, obs = ?, action = ?, "
                "result = ?, outcome = ?, verify = ?, text = ?, embed = ? WHERE id = ?",
                (recurrences, actor, latest["obs"], latest["action"], latest["result"],
                 outcome, latest["verify"], latest["text"], latest["embed"],
                 keep_id),
            )
            if getattr(store, "use_sqlite_vec", False) and latest["embed"]:
                try:
                    conn.execute("DELETE FROM vec_episodes WHERE rowid = ?", (keep_id,))
                    conn.execute(
                        "INSERT INTO vec_episodes(rowid, a) VALUES(?, ?)",
                        (keep_id, latest["embed"]),
                    )
                except Exception:
                    # 影子表缺失不阻断主表合并
                    pass
            ids = [int(r["id"]) for r in rows[1:]]
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM episodes WHERE id IN ({marks})", chunk)
                if getattr(store, "use_sqlite_vec", False):
                    try:
                        conn.execute(f"DELETE FROM vec_episodes WHERE rowid IN ({marks})", chunk)
                    except Exception:
                        pass
            for old_id in ids:
                mapping[old_id] = keep_id
            removed += len(ids)
            merged += 1

        segments_updated = 0
        for seg in conn.execute(
            "SELECT id, ep_ids, n_ep, first_ep, last_ep FROM segments"
        ).fetchall():
            try:
                old_ids = [int(x) for x in json.loads(seg["ep_ids"] or "[]")]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            new_ids: list[int] = []
            seen: set[int] = set()
            for old_id in old_ids:
                new_id = mapping.get(old_id, old_id)
                if new_id not in seen:
                    seen.add(new_id)
                    new_ids.append(new_id)
            if new_ids != old_ids:
                conn.execute(
                    "UPDATE segments SET ep_ids = ?, n_ep = ?, first_ep = ?, last_ep = ? "
                    "WHERE id = ?",
                    (json.dumps(new_ids), len(new_ids),
                     min(new_ids) if new_ids else seg["first_ep"],
                     max(new_ids) if new_ids else seg["last_ep"],
                     int(seg["id"])),
                )
                segments_updated += 1
        # 合并后不变量：剩下的多值组必须只来自“拒绝合并”的冲突组
        bad = conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            "SELECT dedup_key FROM episodes WHERE COALESCE(dedup_key,'') <> '' "
            "GROUP BY dedup_key HAVING COUNT(*) > 1 "
            "AND (COUNT(DISTINCT subject) > 1 OR COUNT(DISTINCT outcome) > 1))"
        ).fetchone()
        bad_n = int(bad["n"] if bad else 0)
        if bad_n != conflicts:
            raise RuntimeError(
                f"dedup 不变量失败：剩余冲突组 {bad_n} != 拒绝合并 {conflicts}"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        store._invalidate_matrix()
    except Exception:
        pass
    return {
        "dry_run": False,
        "groups": total_groups,
        "rows": total_rows,
        "merged_groups": merged,
        "removed_rows": removed,
        "segments_updated": segments_updated,
        "conflict_groups": conflicts,
        "actor_conflicts": actor_conflicts,
        "conflict_log": conflict_path if (conflicts or actor_conflicts) else None,
    }
