"""Local BGE embeddings or explicitly configured compatible remote embeddings.

Remote long texts use lossless, code-point-safe UTF-8 chunks and byte-weighted
pooling. The 2048-byte policy is conservative, not a tokenizer-independent proof
of the provider's 8192-token limit; any provider rejection remains an error.
Stored source text is never truncated or rewritten by this embedding transform.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import math
import threading
from urllib.parse import urlsplit, urlunsplit

import numpy as np

from . import config, deadline, llm

_model = None
_lock = threading.Lock()
_client = None
_client_settings = None
_remote_gate = None
_remote_lock = threading.Lock()
REMOTE_CHUNK_BYTES = 2048
REMOTE_DIMENSIONS = frozenset({64, 128, 256, 512, 768, 1024, 1536, 2048})

# bge asks for this prefix on the query side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _backend() -> str:
    if config.EMBED_BACKEND not in {"bge", "openai"}:
        raise ValueError("AMI_EMBED_BACKEND must be bge or openai")
    return config.EMBED_BACKEND


def _base_url() -> str:
    value = config.EMBED_BASE_URL
    if not value or any(char.isspace() for char in value):
        raise ValueError("AMI_EMBED_BASE_URL requires an explicit HTTP(S) endpoint")
    parts = urlsplit(value)
    if (parts.scheme.lower() not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment):
        raise ValueError("AMI_EMBED_BASE_URL must be HTTP(S), without credentials, query or fragment")
    host = parts.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    port = parts.port
    scheme = parts.scheme.lower()
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host += ":" + str(port)
    return urlunsplit((scheme, host, parts.path.rstrip("/"), "", ""))


def _remote_config() -> str:
    """Validate public settings without loading a client or requiring a key."""
    if config.EMBED_MODEL != "text-embedding-v4":
        raise ValueError("The openai embedding backend requires AMI_EMBED_MODEL=text-embedding-v4")
    if config.EMBED_DIMENSIONS not in REMOTE_DIMENSIONS:
        raise ValueError("AMI_EMBED_DIMENSIONS is unsupported by text-embedding-v4")
    if not 1 <= config.EMBED_BATCH <= 10:
        raise ValueError("AMI_EMBED_BATCH must be between 1 and 10 for text-embedding-v4")
    if not math.isfinite(config.EMBED_TIMEOUT) or not 0 < config.EMBED_TIMEOUT <= 120:
        raise ValueError("AMI_EMBED_TIMEOUT must be finite and between 0 and 120 seconds")
    if not 0 <= config.EMBED_RETRIES <= 3:
        raise ValueError("AMI_EMBED_RETRIES must be between 0 and 3")
    if not 1 <= config.EMBED_CONCURRENCY <= 64:
        raise ValueError("AMI_EMBED_CONCURRENCY must be between 1 and 64")
    return _base_url()


def embedding_identity() -> dict:
    """Public embedding-space identity; excludes secrets and makes no calls.

    Custom local model dimension is unknown until loaded. Remote dimensionality
    and preprocessing are explicit, allowing a store to reject mixed spaces.
    """
    backend = _backend()
    remote = backend == "openai"
    return {
        "backend": backend, "model": config.EMBED_MODEL,
        "dimensions": config.EMBED_DIMENSIONS if remote else
                      (384 if config.EMBED_MODEL == "BAAI/bge-small-en-v1.5" else None),
        "base_url": _remote_config() if remote else None,
        "query_preprocess": "identity" if remote else QUERY_PREFIX,
        "chunk_strategy": f"utf8-{REMOTE_CHUNK_BYTES}-bytes-byte-weighted-normalized-mean-v1" if remote
                          else "sentence-transformers-default-v1",
    }


def _get_remote_client():
    global _client, _client_settings, _remote_gate
    base_url = _remote_config()
    if not config.EMBED_API_KEY.strip():
        raise ValueError("Remote embeddings require AMI_EMBED_API_KEY or DASHSCOPE_API_KEY")
    settings = (config.EMBED_API_KEY, base_url, config.EMBED_TIMEOUT,
                config.EMBED_RETRIES, config.EMBED_CONCURRENCY)
    with _remote_lock:
        if _client is None or settings != _client_settings:
            from openai import OpenAI

            # max_retries=0: retries are made by deadline.call, which can see
            # the request's deadline (AMI_EMBED_RETRIES is still the count).
            _client = OpenAI(api_key=config.EMBED_API_KEY, base_url=base_url,
                             timeout=config.EMBED_TIMEOUT, max_retries=0)
            _remote_gate = threading.BoundedSemaphore(config.EMBED_CONCURRENCY)
            _client_settings = settings
        return _client, _remote_gate


def _chunks(text: str) -> list[str]:
    """Split on Unicode code-point boundaries, preserving every byte and space."""
    if not isinstance(text, str) or not text:
        raise ValueError("Remote embedding inputs must be nonempty strings")
    chunks, start, size = [], 0, 0
    for position, char in enumerate(text):
        length = len(char.encode("utf-8"))
        if size + length > REMOTE_CHUNK_BYTES:
            chunks.append(text[start:position])
            start, size = position, 0
        size += length
    chunks.append(text[start:])
    return chunks


def _normalized(vector, dimensions: int) -> np.ndarray:
    """Reject bad provider data rather than persisting invalid placeholders."""
    try:
        values = np.asarray(vector, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid remote embedding vector") from exc
    if values.shape != (dimensions,) or not np.isfinite(values).all():
        raise ValueError("Remote embedding dimension mismatch or nonfinite vector")
    scale = np.max(np.abs(values))
    if scale == 0:
        raise ValueError("Remote embedding vector must be nonzero")
    # Scale first to avoid overflowing the norm of otherwise finite values.
    values = values / scale
    return np.asarray(values / np.linalg.norm(values), dtype=np.float32)


def _remote_batch(client, gate, payload: list[str]) -> list[np.ndarray]:
    def attempt():
        deadline.acquire(gate)
        try:
            return client.embeddings.create(
                model=config.EMBED_MODEL, input=list(payload), dimensions=config.EMBED_DIMENSIONS,
                encoding_format="float", timeout=deadline.clip(config.EMBED_TIMEOUT))
        finally:
            gate.release()

    response = deadline.call(attempt, config.EMBED_RETRIES, llm.retryable, llm.retry_after)
    data = getattr(response, "data", None)
    if not isinstance(data, list) or len(data) != len(payload):
        raise ValueError("Remote embedding response does not cover every input")
    vectors = [None] * len(payload)
    for item in data:
        index = getattr(item, "index", None)
        if type(index) is not int or not 0 <= index < len(payload) or vectors[index] is not None:
            raise ValueError("Remote embedding response indices must be a full bijection")
        vectors[index] = _normalized(getattr(item, "embedding", None), config.EMBED_DIMENSIONS)
    if any(vector is None for vector in vectors):
        raise ValueError("Remote embedding response missing an input index")
    return vectors


# Batches of one call run side by side (each still takes a slot of the shared
# AMI_EMBED_CONCURRENCY gate), so an Add's wall time is its slowest batch, not
# the sum of its batches. Sized so that waiting for a gate slot, never a
# worker thread, is what bounds the fan-out.
_batch_pool: concurrent.futures.ThreadPoolExecutor | None = None
_batch_pool_lock = threading.Lock()


def _pool() -> concurrent.futures.ThreadPoolExecutor:
    global _batch_pool
    with _batch_pool_lock:
        if _batch_pool is None:
            _batch_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(8, 4 * config.EMBED_CONCURRENCY), thread_name_prefix="embed")
        return _batch_pool


def _encode_remote(texts: list[str]) -> np.ndarray:
    _remote_config()
    if not texts:
        return np.zeros((0, config.EMBED_DIMENSIONS), dtype=np.float32)
    chunks = [_chunks(text) for text in texts]  # Validate all before any request.
    client, gate = _get_remote_client()
    batches: list[tuple[list[str], list[int], list[float]]] = []
    payload, owners, weights = [], [], []
    for owner, parts in enumerate(chunks):
        total_bytes = sum(len(part.encode("utf-8")) for part in parts)
        for part in parts:
            payload.append(part)
            owners.append(owner)
            weights.append(len(part.encode("utf-8")) / total_bytes)
            if len(payload) == config.EMBED_BATCH:
                batches.append((payload, owners, weights))
                payload, owners, weights = [], [], []
    if payload:
        batches.append((payload, owners, weights))
    if len(batches) == 1:
        results = [_remote_batch(client, gate, batches[0][0])]
    else:
        futures = [_pool().submit(contextvars.copy_context().run, _remote_batch, client, gate, batch[0])
                   for batch in batches]
        try:
            results = [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()  # batches not yet started; the call has failed
            raise
    pooled = np.zeros((len(texts), config.EMBED_DIMENSIONS), dtype=np.float64)
    for (_, batch_owners, batch_weights), vectors in zip(batches, results):
        for owner, weight, vector in zip(batch_owners, batch_weights, vectors):
            pooled[owner] += weight * vector.astype(np.float64)
    return np.stack([_normalized(vector, config.EMBED_DIMENSIONS) for vector in pooled])


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                import torch
                from sentence_transformers import SentenceTransformer

                # Set before the first forward pass, and only when configured, so
                # a deployment that wants torch's own heuristic can have it.
                if config.EMBED_THREADS > 0:
                    torch.set_num_threads(config.EMBED_THREADS)
                _model = SentenceTransformer(config.EMBED_MODEL, device=config.EMBED_DEVICE)
    return _model


def dim() -> int:
    if _backend() == "openai":
        _remote_config()
        return config.EMBED_DIMENSIONS
    return int(_get_model().get_sentence_embedding_dimension())


def encode(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    """Return L2-normalised float32 embeddings; cosine similarity is a dot product."""
    if _backend() == "openai":
        return _encode_remote(texts)
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
