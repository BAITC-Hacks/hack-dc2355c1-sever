"""Сужение 40 сценариев до top-K кандидатов через эмбеддинги.

Это НЕ выбор сценария: финальное решение всегда принимает LLM (llm_router.py).
При любой ошибке возвращаем весь каталог — LLM справится и с 40.
"""

import hashlib
import json

import numpy as np

from ..catalog import catalog
from ..config import settings
from ..providers import llm

_index: tuple[str, list[str], np.ndarray] | None = None


async def _build_index() -> tuple[list[str], np.ndarray]:
    global _index
    ids = list(catalog.scenarios)
    texts = [catalog.embed_text(sid) for sid in ids]
    digest = hashlib.sha256(json.dumps([settings.openai_embed_model, texts], ensure_ascii=False).encode()).hexdigest()[:16]
    if _index and _index[0] == digest:
        return _index[1], _index[2]

    path = settings.cache_dir / f"emb_{digest}.npy"
    if path.exists():
        matrix = np.load(path)
    else:
        matrix = np.array(await llm.embed(texts), dtype=np.float32)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        np.save(path, matrix)
    _index = (digest, ids, matrix)
    return ids, matrix


async def top_k(query: str, k: int | None = None, must_include: list[str] | None = None) -> list[str]:
    k = k or settings.top_k_candidates
    ids = list(catalog.scenarios)
    if len(ids) <= k or not llm.available("openai"):
        return ids
    try:
        ids, matrix = await _build_index()
        q = np.array((await llm.embed([query]))[0], dtype=np.float32)
        scores = matrix @ (q / np.linalg.norm(q))
        picked = [ids[i] for i in np.argsort(-scores)[:k]]
    except Exception:
        return ids
    for sid in must_include or []:
        if sid and sid in catalog.scenarios and sid not in picked:
            picked.append(sid)
    return picked


async def warmup() -> None:
    if llm.available("openai") and len(catalog.scenarios) > settings.top_k_candidates:
        try:
            await _build_index()
        except Exception:
            pass
