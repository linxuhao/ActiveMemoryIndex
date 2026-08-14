"""SQLite-backed memory store with a per-user in-process vector cache.

Add is synchronous: a record is committed and inserted into the cache before the
HTTP response is written, so it is immediately searchable (contract requirement).
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_cache: "OrderedDict[str, UserIndex]" = OrderedDict()
_cached_items = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    session_id TEXT,
    request_id TEXT,
    kind       TEXT NOT NULL,
    parent_id  TEXT,
    content    TEXT NOT NULL,
    created_at TEXT,
    seq        INTEGER,
    vec        BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id);
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    PRIMARY KEY (request_id, user_id)
);
"""


@dataclass
class Item:
    id: str
    kind: str
    parent_id: str | None
    content: str
    created_at: str | None


class UserIndex:
    def __init__(self) -> None:
        self.items: list[Item] = []
        self.matrix: np.ndarray | None = None
        # id -> row, so the neighbours of a selected turn can be found without
        # scanning the user's whole history on every search.
        self.by_id: dict[str, int] = {}

    def append(self, items: list[Item], vectors: np.ndarray) -> None:
        for offset, item in enumerate(items):
            self.by_id[item.id] = len(self.items) + offset
        self.items.extend(items)
        self.matrix = vectors if self.matrix is None else np.vstack([self.matrix, vectors])


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        path = Path(config.DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.executescript(SCHEMA)
        _conn.commit()


def item_id(request_id: str, kind: str, index: int, user_id: str = "") -> str:
    # user_id is part of the digest: the contract does not promise globally
    # unique request_ids, and an unsalted id would let one user's Add replace
    # another user's row through INSERT OR REPLACE.
    digest = hashlib.sha1(f"{user_id}\x00{request_id}".encode("utf-8")).hexdigest()[:16]
    return f"{digest}-{kind[0]}{index}"


_gates: dict[tuple[str, str], threading.Lock] = {}
_gates_guard = threading.Lock()


def request_gate(request_id: str, user_id: str) -> threading.Lock:
    """Serialize concurrent attempts at the same write.

    The platform retries Add on 408/409/425/429/5xx, so two attempts at one
    request_id can overlap. Without this gate both pass the duplicate check,
    both run the LLM, and the store ends up holding a mixture of two different
    extractions of the same chunk — with the in-process cache and SQLite
    disagreeing about how many rows exist.
    """
    key = (request_id, user_id)
    with _gates_guard:
        gate = _gates.get(key)
        if gate is None:
            gate = _gates[key] = threading.Lock()
        return gate


def request_seen(request_id: str, user_id: str) -> bool:
    with _lock:
        row = _conn.execute(
            "SELECT 1 FROM requests WHERE request_id = ? AND user_id = ?",
            (request_id, user_id),
        ).fetchone()
        return row is not None


def add(user_id: str, session_id: str, request_id: str, items: list[Item], vectors: np.ndarray) -> int:
    """Persist items and make them searchable. Returns the number stored."""
    with _lock:
        index = _load(user_id)
        seq = len(index.items)
        rows = [
            (
                item.id,
                user_id,
                session_id,
                request_id,
                item.kind,
                item.parent_id,
                item.content,
                item.created_at,
                seq + offset,
                vectors[offset].tobytes(),
            )
            for offset, item in enumerate(items)
        ]
        _conn.executemany(
            "INSERT OR REPLACE INTO items "
            "(id, user_id, session_id, request_id, kind, parent_id, content, created_at, seq, vec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        _conn.execute(
            "INSERT OR REPLACE INTO requests (request_id, user_id) VALUES (?, ?)", (request_id, user_id)
        )
        _conn.commit()
        global _cached_items
        index.append(items, vectors)
        _cached_items += len(items)
        _evict_to_fit()
        return len(items)


def get(user_id: str) -> UserIndex:
    with _lock:
        return _load(user_id)


def _evict_to_fit() -> None:
    """Hold the cache under AMI_CACHE_MAX_ITEMS rows, oldest use first.

    Callers already hold a live reference to whatever they were handed, so
    dropping an entry never invalidates an in-flight request; the next lookup
    reads it back from SQLite, which is the source of truth either way.
    """
    global _cached_items
    while _cached_items > config.CACHE_MAX_ITEMS and len(_cache) > 1:
        _, evicted = _cache.popitem(last=False)
        _cached_items -= len(evicted.items)


def _load(user_id: str) -> UserIndex:
    index = _cache.get(user_id)
    if index is not None:
        _cache.move_to_end(user_id)
        return index
    index = UserIndex()
    rows = _conn.execute(
        "SELECT id, kind, parent_id, content, created_at, vec FROM items WHERE user_id = ? ORDER BY seq",
        (user_id,),
    ).fetchall()
    if rows:
        items = [Item(id=r[0], kind=r[1], parent_id=r[2], content=r[3], created_at=r[4]) for r in rows]
        matrix = np.vstack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
        index.append(items, matrix)
    global _cached_items
    _cache[user_id] = index
    _cached_items += len(index.items)
    _evict_to_fit()
    return index


def stats() -> dict:
    with _lock:
        users = _conn.execute("SELECT COUNT(DISTINCT user_id) FROM items").fetchone()[0]
        items = _conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return {"users": users, "items": items}
