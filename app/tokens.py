"""Token accounting for the platform's Answer window.

The official API guide fixes the window: 128,000 tokens, of which 8,192 are
reserved for output and 2,048 for safety, leaving 117,760 input tokens shared
by the Answer instructions, the question, its options and the archived Search
response. When the response does not fit, Answer keeps a token-counted prefix
of the candidates in returned order. The answer model and its tokenizer are
not public, so a Search response is sized here, in the service, against a
budget computed per request:

    memory budget = (ANSWER_INPUT_TOKENS - ANSWER_PROMPT_TOKENS) / TOKEN_SAFETY
                    - tokens(query) - tokens(options)

and every returned memory costs tokens(content) + ANSWER_ITEM_TOKENS.

Counting uses tiktoken's o200k_base (the gpt-4o family) when it is installed
and its encoding file is available (the image bakes it in). Without it, a
conservative byte-based estimate is used. TOKEN_SAFETY covers the difference
between o200k_base and other plausible answer tokenizers; the measurement that
sets it is in bench/results/token_budget_20261006.md.

Nothing here touches stored text: it only decides how many memories fit.
"""
from __future__ import annotations

import functools
import logging
import math
import threading

from . import config

log = logging.getLogger("ami.tokens")

_lock = threading.Lock()
_encoding = None
_loaded = False


def _get_encoding():
    global _encoding, _loaded
    if not _loaded:
        with _lock:
            if not _loaded:
                try:
                    import tiktoken

                    _encoding = tiktoken.get_encoding(config.TOKEN_ENCODING)
                except Exception as exc:  # noqa: BLE001 - missing package or encoding file
                    log.warning("tiktoken %s unavailable (%s); using the conservative byte estimate",
                                config.TOKEN_ENCODING, exc)
                    _encoding = None
                _loaded = True
    return _encoding


def backend() -> str:
    """'tiktoken:<encoding>' or 'estimate' — reported at startup."""
    return f"tiktoken:{config.TOKEN_ENCODING}" if _get_encoding() is not None else "estimate"


def estimate(text: str) -> int:
    """Upper-bound estimate used without tiktoken, by character class: an ASCII
    letter 1/3 token, a digit 1/2, ASCII whitespace 1/4, ASCII punctuation 1,
    anything else its UTF-8 bytes / 3 (a CJK character 1). Measured against
    o200k_base it over-counts LoCoMo/LongMemEval text by 1.6-1.7x, Chinese by
    ~1.4x and code by 1.7x, and matches it on digit runs; a single base64 blob
    can come in under it, which the totals and TOKEN_SAFETY absorb."""
    total = 0.0
    for char in text:
        if char.isascii():
            if char.isalpha():
                total += 1 / 3
            elif char.isdigit():
                total += 0.5
            elif char.isspace():
                total += 0.25
            else:
                total += 1.0
        else:
            total += len(char.encode("utf-8")) / 3
    return math.ceil(total) + 1


@functools.lru_cache(maxsize=4096)
def count(text: str) -> int:
    """Tokens in *text* (o200k_base, or the estimate)."""
    if not text:
        return 0
    encoding = _get_encoding()
    if encoding is None:
        return estimate(text)
    return len(encoding.encode(text, disallowed_special=()))


def item_cost(text: str) -> int:
    """What one returned memory costs in the Answer prompt: its text plus the
    per-memory formatting the platform adds (a list marker, a timestamp, a
    newline)."""
    return count(text) + config.ANSWER_ITEM_TOKENS


def memory_budget(query: str = "", options: list[str] | None = None) -> int:
    """Counted tokens available to this Search's returned memories. Can be
    zero or negative for a query that fills the window by itself."""
    fixed = count(query or "")
    if options:
        fixed += sum(count(str(option)) + 2 for option in options)
    usable = (config.ANSWER_INPUT_TOKENS - config.ANSWER_PROMPT_TOKENS) / max(config.TOKEN_SAFETY, 1.0)
    return int(usable) - fixed


def fit(contents: list[str], budget: int) -> int:
    """How many of *contents*, taken in order, fit in *budget*."""
    used = 0
    for position, text in enumerate(contents):
        used += item_cost(text)
        if used > budget:
            return position
    return len(contents)
