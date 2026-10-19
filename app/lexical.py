"""Lexical channel: BM25 over character trigrams, per user, in memory.

Trigrams rather than words because a word needs a tokenizer, and a tokenizer
is a decision about language: whitespace does not split Chinese, and a stemmer
knows one language. A trigram is three consecutive characters of the
lower-cased text, so `get_user_id`, `auth/session.py` or `KeyError: 'token'`
match the items containing them as substrings, in any script, as grep would.
Inverse document frequency does the weighting: a trigram that occurs in every
item scores nearly nothing, one that occurs in two items scores a lot.

The index lives beside the user's vectors (store.UserIndex). It is built on
the user's first lexical search, extended by every Add after that, and
dropped least-recently-used first when all built indexes together exceed
AMI_LEXICAL_MAX_POSTINGS; a dropped index is rebuilt on the next search.
Nothing is written to the database, and the channel costs nothing while off.
"""
from __future__ import annotations

import weakref
from collections import OrderedDict

import numpy as np

from . import config, store

K1 = 1.2
B = 0.75
# A new Add becomes its own small sorted segment, so appending never re-sorts
# the user's whole history; past this many segments they are merged into one.
MAX_SEGMENTS = 8

# Users whose index is built, least recently searched first. Weak references:
# when the store's cache drops a user, the index goes with it.
_built: "OrderedDict[int, weakref.ref]" = OrderedDict()


def grams(text: str) -> np.ndarray:
    """Every trigram of the lower-cased *text*, hashed to 32 bits.

    Three code points pack exactly into 63 bits; the multiplicative hash folds
    that to 32. Two different trigrams of one user's history sharing a hash
    is rare enough that it only perturbs a BM25 weight, never a result's text.
    """
    points = np.frombuffer(text.lower().encode("utf-32-le"), dtype=np.uint32).astype(np.uint64)
    if len(points) < 3:
        return np.empty(0, dtype=np.uint32)
    packed = (points[:-2] << np.uint64(42)) | (points[1:-1] << np.uint64(21)) | points[2:]
    return ((packed * np.uint64(0x9E3779B97F4A7C15)) >> np.uint64(32)).astype(np.uint32)


class Index:
    """Sorted segments of postings: (trigram, row, count of the trigram in the row)."""

    def __init__(self) -> None:
        self.segments: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        self.lengths = np.empty(0, dtype=np.float32)

    @property
    def postings(self) -> int:
        return sum(len(keys) for keys, _, _ in self.segments)

    def extend(self, contents: list[str]) -> None:
        first = len(self.lengths)
        keys, rows, counts, lengths = [], [], [], []
        for offset, content in enumerate(contents):
            every = grams(content)
            unique, count = np.unique(every, return_counts=True)
            keys.append(unique)
            rows.append(np.full(len(unique), first + offset, dtype=np.int32))
            counts.append(np.minimum(count, np.iinfo(np.uint16).max).astype(np.uint16))
            lengths.append(len(every))
        self.lengths = np.concatenate([self.lengths, np.asarray(lengths, dtype=np.float32)])
        if contents:
            self.segments.append(_sorted(np.concatenate(keys), np.concatenate(rows), np.concatenate(counts)))
        if len(self.segments) > MAX_SEGMENTS:
            self.segments = [_sorted(*(np.concatenate(part) for part in zip(*self.segments)))]

    def scores(self, query: str) -> np.ndarray:
        """BM25 of every row against the query's trigrams; 0 where nothing matches."""
        total = len(self.lengths)
        wanted = np.unique(grams(query))
        if total == 0 or len(wanted) == 0:
            return np.zeros(total, dtype=np.float32)
        spans = [(np.searchsorted(keys, wanted, side="left"), np.searchsorted(keys, wanted, side="right"))
                 for keys, _, _ in self.segments]
        frequency = sum(end - start for start, end in spans)
        idf = np.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))
        norm = K1 * (1.0 - B + B * self.lengths / max(float(self.lengths.mean()), 1.0))
        scores = np.zeros(total, dtype=np.float64)
        for (keys, rows, counts), (start, end) in zip(self.segments, spans):
            width = end - start
            if not width.any():
                continue
            # Every posting of every wanted trigram in this segment, at once.
            hit = np.repeat(np.arange(len(wanted)), width)
            at = np.repeat(start - np.concatenate([[0], np.cumsum(width)[:-1]]), width) + np.arange(width.sum())
            row = rows[at]
            tf = counts[at].astype(np.float64)
            scores += np.bincount(row, weights=idf[hit] * tf * (K1 + 1.0) / (tf + norm[row]), minlength=total)
        return scores.astype(np.float32)


def _sorted(keys: np.ndarray, rows: np.ndarray, counts: np.ndarray):
    order = np.argsort(keys, kind="stable")
    return keys[order], rows[order], counts[order]


def _index(user_index) -> Index:
    """The user's postings, built if absent; the cache of built indexes is
    kept under its bound, least recently searched first. Holds the store lock."""
    index = user_index.lexical
    if index is None or len(index.lengths) != len(user_index.items):
        index = Index()
        index.extend([item.content for item in user_index.items])
        user_index.lexical = index
    _built[id(user_index)] = weakref.ref(user_index)
    _built.move_to_end(id(user_index))
    users = {key: ref() for key, ref in _built.items()}
    for key, user in users.items():
        if user is None or user.lexical is None:
            del _built[key]
    total = sum(user.lexical.postings for user in users.values() if user is not None and user.lexical is not None)
    for key in list(_built)[:-1]:
        if total <= config.LEXICAL_MAX_POSTINGS:
            break
        total -= users[key].lexical.postings
        users[key].lexical = None
        del _built[key]
    return index


def fuse(user_index, scores: np.ndarray, query: str) -> np.ndarray:
    """Reciprocal-rank fusion of the dense ranking with the lexical one.

    Rank, not score: cosine is bounded and BM25 is not, so a fixed weighting of
    the raw values would be set by their scales. Every row keeps its dense
    rank, so a query that matches nothing degrades exactly to the dense order,
    and a row ruled out of selection (-inf) stays out.
    """
    if not config.LEXICAL or not len(scores):
        return scores
    # Under the store lock, which Add holds while it appends: the postings and
    # the item list must describe the same rows.
    with store._lock:
        lexical = _index(user_index).scores(query)
    k = config.LEXICAL_RRF_K
    fused = np.empty(len(scores), dtype=np.float64)
    fused[np.argsort(-scores, kind="stable")] = 1.0 / (k + np.arange(1, len(scores) + 1))
    hits = np.flatnonzero(lexical > 0)
    if len(hits):
        best = hits[np.argsort(-lexical[hits], kind="stable")][: config.LEXICAL_CANDIDATES]
        fused[best] += 1.0 / (k + np.arange(1, len(best) + 1))
    return np.where(np.isfinite(scores), fused, -np.inf)
