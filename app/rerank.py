"""Cross-encoder rescoring of the top candidates, loaded once like the embedder.

The bi-encoder ranks every memory a user has; this re-reads only the top
RERANK_CANDIDATES of them with query and passage in one forward pass, and
select() then draws from that pool in the cross-encoder's order. Nothing outside
the pool is discarded — it keeps its bi-encoder order beneath the pool — so a
pool smaller than what select() needs still fills the return set.
"""
from __future__ import annotations

import threading

import numpy as np

from . import config, store

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import CrossEncoder

                _model = CrossEncoder(config.RERANK_MODEL, device=config.EMBED_DEVICE,
                                      max_length=config.RERANK_MAX_LENGTH)
    return _model


def score_pairs(query: str, passages: list[str]) -> np.ndarray:
    if not passages:
        return np.zeros(0, dtype=np.float32)
    raw = _get_model().predict([(query, p) for p in passages], batch_size=config.RERANK_BATCH,
                               show_progress_bar=False, convert_to_numpy=True)
    return np.asarray(raw, dtype=np.float32).reshape(-1)


def rescore(index: store.UserIndex, query: str, scores: np.ndarray) -> np.ndarray:
    """The top RERANK_CANDIDATES by *scores*, re-ordered by the cross-encoder and
    lifted above everything else; the rest keep their relative order beneath."""
    n = min(config.RERANK_CANDIDATES, len(scores))
    if n <= 0:
        return scores
    pool = np.argpartition(-scores, n - 1)[:n] if n < len(scores) else np.arange(len(scores))
    ce = score_pairs(query, [index.items[int(i)].content for i in pool])
    # Rest strictly below zero, pool strictly above: the two never interleave.
    out = scores.astype(np.float32) - float(scores.max()) - 1.0
    out[pool] = ce - float(ce.min()) + 1.0
    return out


def warm_up() -> None:
    score_pairs("warm up", ["warm up"])
