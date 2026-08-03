"""BGE-small sentence embeddings, loaded once and shared across requests."""
from __future__ import annotations

import threading

import numpy as np

from . import config

_model = None
_lock = threading.Lock()

# bge asks for this prefix on the query side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(config.EMBED_MODEL, device=config.EMBED_DEVICE)
    return _model


def dim() -> int:
    return int(_get_model().get_sentence_embedding_dimension())


def encode(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    """Return L2-normalised float32 embeddings; cosine similarity is a dot product."""
    if not texts:
        return np.zeros((0, dim()), dtype=np.float32)
    payload = [QUERY_PREFIX + t for t in texts] if is_query else texts
    vectors = _get_model().encode(
        payload,
        batch_size=config.EMBED_BATCH,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)


def warm_up() -> None:
    encode(["warm up"])
