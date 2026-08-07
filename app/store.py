"""SQLite-backed memory store with a per-user in-process vector cache.

Add is synchronous: a record is committed and inserted into the cache before the
HTTP response is written, so it is immediately searchable (contract requirement).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_cache: dict[str, "UserIndex"] = {}

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
-- Lexical index for hybrid retrieval. Written on every Add in the same
-- transaction as the row itself, whether or not AMI_HYBRID is on: an index that
-- is only maintained while a flag is set is an index that is silently stale the
-- first time the flag is turned on. `porter` stems, so a fact written in the
-- present tense still matches a question asked in the past tense.
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    content,
    item_id UNINDEXED,
    user_id UNINDEXED,
    tokenize='porter unicode61 remove_diacritics 2'
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
        # id -> row position, so a lexical hit can be fused with the dense
        # scores without rescanning the item list on every search.
        self.positions: dict[str, int] = {}

    def append(self, items: list[Item], vectors: np.ndarray) -> None:
        for offset, item in enumerate(items):
            self.positions[item.id] = len(self.items) + offset
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
        # Same transaction as the row itself: Add returns 200 only once the
        # memory is searchable, and that has to include the lexical channel.
        _conn.executemany(
            "DELETE FROM items_fts WHERE item_id = ?", [(item.id,) for item in items]
        )
        _conn.executemany(
            "INSERT INTO items_fts (content, item_id, user_id) VALUES (?, ?, ?)",
            [(item.content, item.id, user_id) for item in items],
        )
        _conn.execute(
            "INSERT OR REPLACE INTO requests (request_id, user_id) VALUES (?, ?)", (request_id, user_id)
        )
        _conn.commit()
        index.append(items, vectors)
        return len(items)


def get(user_id: str) -> UserIndex:
    with _lock:
        return _load(user_id)


def _load(user_id: str) -> UserIndex:
    index = _cache.get(user_id)
    if index is not None:
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
    _cache[user_id] = index
    return index


def stats() -> dict:
    with _lock:
        users = _conn.execute("SELECT COUNT(DISTINCT user_id) FROM items").fetchone()[0]
        items = _conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return {"users": users, "items": items}


_MATCH_TOKEN = re.compile(r"[0-9a-z]+")


def match_expression(text: str, max_terms: int = 32) -> str:
    """Turn arbitrary user text into a valid FTS5 MATCH expression.

    FTS5's MATCH argument is a query language, not a string: `?`, `-`, `(`, `"`
    and `:` are operators, so passing a natural question straight through raises
    `fts5: syntax error`. Every token is quoted as a literal phrase and joined
    with OR, which is the bag-of-words reading BM25 expects.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for token in _MATCH_TOKEN.findall(text.lower()):
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{term}"' for term in terms)


def lexical(user_id: str, text: str, limit: int) -> list[str]:
    """BM25-ranked item ids for *text*, best first. Empty list on no match."""
    expression = match_expression(text)
    if not expression:
        return []
    with _lock:
        try:
            rows = _conn.execute(
                "SELECT item_id FROM items_fts "
                "WHERE items_fts MATCH ? AND user_id = ? "
                "ORDER BY bm25(items_fts) LIMIT ?",
                (expression, user_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # A malformed expression must degrade to dense-only retrieval, never
            # turn a Search into a 500.
            return []
    return [row[0] for row in rows]


def backfill_fts() -> int:
    """Populate the lexical index for rows written before it existed."""
    with _lock:
        indexed = _conn.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0]
        total = _conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if indexed >= total:
            return 0
        _conn.execute("DELETE FROM items_fts")
        _conn.execute(
            "INSERT INTO items_fts (content, item_id, user_id) "
            "SELECT content, id, user_id FROM items"
        )
        _conn.commit()
        return total
