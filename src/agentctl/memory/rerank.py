# -*- coding: utf-8 -*-
r"""agentctl.memory.rerank —— API 裁判重排（记忆层刀 · 2026-11-15，默认关闭）

来源（观察期实测 memory_judge_v3）：GLM 裁判种子召回@5 = 0.76 vs hash-ngram 0.20；
terse 数字型条目是共同盲区（prompt 已带 one-shot 示例缓解）。

口径：
    开关：环境变量 AGENTCTL_RERANK=cloud 才启用；其他值/未设 = 直接原样返回。
    范围：只重排 source=="episode" 的细粒度命中（segment-summary 不动）。
    分数：API 0..10；拿不到分（429/超时/解析失败）的条目**保持在队尾、维持原序**——
          绝不因裁判缺席而改变召回内容。
    缓存：rerank_cache.json（键=查询+条目id+文本指纹），命中缓存零延迟零费用。
    配置：AGENTCTL_RERANK_MODEL（默认 glm-4v-flash）、AGENTCTL_RERANK_TOP_N（默认 12）、
          AGENTCTL_RERANK_WORKERS（默认 3）、AGENTCTL_RERANK_TIMEOUT（默认 20s）。
    Key：复用 agentctl 视觉 key（_vision_key），记账走 vision_backend_cloud._state_update。
"""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path

__all__ = ["enabled", "maybe_rerank"]

_ENV_FLAG = "AGENTCTL_RERANK"
_ENV_MODEL = "AGENTCTL_RERANK_MODEL"
ENV_TOP_N = "AGENTCTL_RERANK_TOP_N"
ENV_WORKERS = "AGENTCTL_RERANK_WORKERS"
ENV_TIMEOUT = "AGENTCTL_RERANK_TIMEOUT"
DEFAULT_MODEL = "glm-4v-flash"
_TOP_N = 12
_WORKERS = 3
_TIMEOUT = 20.0
_CACHE_MAX = 6000

_PROMPT = (
    "你是记忆检索裁判。判断一条记忆条目对查询的相关性，只输出JSON："
    '{"score": 0到10的整数}。10=正是查询要找的操作/内容，0=完全无关。\n'
    "示例：查询「往记事本填字的演示」，条目「fill 2026-09-01; win=notepad.exe 填字 ok=1」"
    '→ {"score": 9}（流水格式也要读懂动作本身）。\n'
    "查询：%s\n条目：%s"
)


def enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip().lower() == "cloud"


def _cache_path() -> Path:
    env = os.environ.get("AGENTCTL_RERANK_CACHE")
    if env:
        return Path(env)
    base = os.environ.get("AGENTCTL_MEMORY_DB")
    if base:
        return Path(base).parent / "rerank_cache.json"
    return Path(os.path.expandvars(
        r"%LOCALAPPDATA%\AgentCtl\work\memory\rerank_cache.json"))


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    try:
        if len(cache) > _CACHE_MAX:
            for k in sorted(cache, key=lambda k: cache[k].get("ts", 0))[: len(cache) - _CACHE_MAX]:
                cache.pop(k, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 —— 缓存坏了不影响主流程
        pass


def _ckey(query: str, item_id, text: str) -> str:
    h = hashlib.sha1(
        (query + "::" + str(item_id) + "::" + text[:200]).encode("utf-8")
    ).hexdigest()
    return h[:20]


def _score_one(key: str, base_url: str, model: str, query: str, text: str,
               timeout: float) -> int:
    sys_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from agentctl.vision_backend_cloud import read_key, default_key_file
        if not key:
            key = read_key(default_key_file())
    except Exception:  # noqa: BLE001
        pass
    if not key:
        return -1
    payload = {
        "model": model, "temperature": 0,
        "messages": [{"role": "user", "content": _PROMPT % (query, text[:350])}],
    }
    for attempt in (0, 1, 2):
        req = urllib.request.Request(
            base_url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"] or ""
            m = re.search(r'"?score"?\s*[:：]\s*"?(\d+)', content)
            if m:
                return max(0, min(10, int(m.group(1))))
            return -1
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(5 + attempt * 6)
                continue
            return -1
        except Exception:  # noqa: BLE001
            if attempt < 2:
                time.sleep(1.5)
                continue
            return -1
    return -1


def maybe_rerank(query: str, hits: list[dict]) -> list[dict]:
    """开关关闭/异常时原样返回；启用时对 episode 命中做 API 重排。"""
    if not enabled() or len(hits) < 2:
        return hits
    top_n = int(os.environ.get(ENV_TOP_N, _TOP_N))
    workers = max(1, int(os.environ.get(ENV_WORKERS, _WORKERS)))
    timeout = float(os.environ.get(ENV_TIMEOUT, _TIMEOUT))
    model = os.environ.get(_ENV_MODEL, DEFAULT_MODEL)

    head = hits[:top_n]
    tail = hits[top_n:]
    items = [h for h in head if h.get("source") == "episode"]
    others = [h for h in head if h.get("source") != "episode"]
    if len(items) < 2:
        return hits

    cpath = _cache_path()
    cache = _load_cache(cpath)
    base_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    key = ""
    try:
        from agentctl.vision_backend_cloud import read_key, default_key_file
        key = read_key(default_key_file())
    except Exception:  # noqa: BLE001
        return hits
    if not key:
        return hits

    def work(h: dict):
        text = str(h.get("text") or h.get("obs") or h.get("action") or "")
        ck = _ckey(query, h.get("id"), text)
        hit = cache.get(ck)
        if isinstance(hit, dict) and isinstance(hit.get("score"), int):
            return h, hit["score"]
        s = _score_one(key, base_url, model, query, text, timeout)
        if s >= 0:
            cache[ck] = {"score": s, "ts": time.time()}
        return h, s

    out_items: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for h, s in ex.map(work, items):
            h = dict(h)
            if s >= 0:
                h["rerank_score"] = s
            out_items.append((h, s))
    _save_cache(cpath, cache)

    scored = [h for h, s in out_items if s >= 0]
    unscored = [h for h, s in out_items if s < 0]
    scored.sort(key=lambda h: (-float(h["rerank_score"]), int(h.get("id") or 0)))
    # 丢弃旧 score 排序的影响：API 有分的在前，无分的(裁判缺席)按原序殿后
    return others + scored + unscored + tail
