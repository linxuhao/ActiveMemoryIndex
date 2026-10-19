"""Guard on the lexical channel (app/lexical.py, AMI_LEXICAL).

The channel exists for literal strings the embedding of a sentence blurs:
identifiers, paths, error messages. These checks pin that such a string
reaches the item containing it, in any script; that a query matching nothing
leaves the dense order exactly as it was; that a row ruled out of selection
stays out; that the postings built on demand and extended by Add are the same
as a fresh build; and that with the switch off nothing changes at all.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, lexical, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


CONTENTS = [
    "[2026-10-01 10:00] I: we refactored get_user_ids in api/users.py last week",
    "[2026-10-01 10:01] Assistant: the weather looks fine for the release",
    "[2026-10-01 10:02] I: tests fail with KeyError: 'token' in auth/session.py line 42",
    "[2026-10-01 10:03] I: 我把数据库迁移到了 /home 目录，容器没有重启",
    "[2026-10-01 10:04] Assistant: noted, the migration finished",
]


def user_index(contents):
    items = [store.Item(id=f"aaaaaaaaaaaaaaaa-r{p}", kind="raw", parent_id=None,
                        content=c, created_at=None) for p, c in enumerate(contents)]
    index = store.UserIndex()
    index.append(items, np.zeros((len(items), 4), dtype=np.float32))
    return index


ok = True
saved = config.LEXICAL
config.LEXICAL = True

built = lexical.Index()
built.extend(CONTENTS)
top = lambda query: int(np.argmax(built.scores(query)))
ok &= check(top("KeyError token auth/session.py") == 2, "an error string and a path find the turn holding them")
ok &= check(top("get_user_id") == 0, "an identifier matches inside a longer one, as a substring")
ok &= check(top("数据库迁移") == 3, "a query with no spaces matches in a script without spaces")
ok &= check(not built.scores("zzqx").any(), "a query sharing no trigram scores every row 0")
ok &= check(not built.scores("ab").any(), "a query shorter than a trigram scores nothing and does not fail")

# Four hundred filler turns the dense channel prefers, then the five above; the
# turn holding the error string is the one dense likes least. The evaluation
# asks for top_k=100, so the question is whether the match gets into that set.
N = 400
FILLER = [f"[2026-10-02 {m // 60:02d}:{m % 60:02d}] Assistant: ok, step {m} of the build is done" for m in range(N)]
rng = np.random.default_rng(0)
dense = np.concatenate([rng.uniform(.5, .9, N), [.4, .45, .1, .3, .35]]).astype(np.float32)
index = user_index(FILLER + CONTENTS)
fused = lexical.fuse(index, dense, "zzqx")
ok &= check(list(np.argsort(-fused, kind="stable")) == list(np.argsort(-dense, kind="stable")),
            "no lexical match leaves the dense order exactly as it was")
fused = lexical.fuse(index, dense, "KeyError: 'token' in auth/session.py")
target = N + 2
position = int(np.flatnonzero(np.argsort(-fused, kind="stable") == target)[0])
print(f"turn with the error string: dense place {int(np.flatnonzero(np.argsort(-dense) == target)[0]) + 1}"
      f" of {len(dense)}, fused place {position + 1}")
ok &= check(position < 100, "a literal match lifts the turn dense ranks last into the top_k=100 set")
ruled_out = dense.copy()
ruled_out[target] = -np.inf
ok &= check(lexical.fuse(index, ruled_out, "KeyError token")[target] == -np.inf,
            "a row ruled out of selection stays out whatever it matches")

grown = user_index(CONTENTS[:2])
lexical.fuse(grown, dense[:2], "token")
extra = [store.Item(id=f"aaaaaaaaaaaaaaaa-r{p}", kind="raw", parent_id=None, content=c, created_at=None)
         for p, c in enumerate(CONTENTS[2:], start=2)]
grown.append(extra, np.zeros((len(extra), 4), dtype=np.float32))
fresh = lexical.Index()
fresh.extend(CONTENTS)
ok &= check(all(np.allclose(grown.lexical.scores(q), fresh.scores(q))
                for q in ("token", "auth/session.py", "数据库", "release weather")),
            "postings extended Add by Add score exactly like a fresh build of the same rows")
many = lexical.Index()
for content in FILLER[:30]:
    many.extend([content])
whole = lexical.Index()
whole.extend(FILLER[:30])
ok &= check(len(many.segments) <= lexical.MAX_SEGMENTS
            and np.allclose(many.scores("step 7 of the build"), whole.scores("step 7 of the build")),
            "thirty one-turn Adds merge into a bounded number of segments with identical scores")
saved_bound = config.LEXICAL_MAX_POSTINGS
config.LEXICAL_MAX_POSTINGS = 1
first, second = user_index(CONTENTS), user_index(CONTENTS)
lexical.fuse(first, dense[:5], "token")
lexical.fuse(second, dense[:5], "token")
config.LEXICAL_MAX_POSTINGS = saved_bound
dropped = first.lexical is None and second.lexical is not None
lexical.fuse(first, dense[:5], "token")
ok &= check(dropped and first.lexical is not None
            and np.allclose(first.lexical.scores("auth/session.py"), fresh.scores("auth/session.py")),
            "over the postings bound the least recently searched index is dropped, and rebuilt on demand")
import gc, weakref  # noqa: E402
gone = user_index(CONTENTS)
lexical.fuse(gone, dense[:5], "token")
ref = weakref.ref(gone)
del gone
gc.collect()
ok &= check(ref() is None, "the lexical cache never keeps a user the store has let go of")

other = user_index(["nothing about tokens here", "KeyError: 'token' in auth/session.py"])
ok &= check(int(np.argmax(lexical.fuse(other, np.zeros(2, dtype=np.float32), "auth/session.py"))) == 1
            and index.lexical is not other.lexical,
            "each user has their own postings and statistics")

config.LEXICAL = False
ok &= check(lexical.fuse(user_index(FILLER + CONTENTS), dense, "KeyError token") is dense,
            "switched off, the dense scores pass through untouched")

# Through /search: the literal match is returned first among the verbatim turns.
config.LEXICAL = True
saved_main = (main.rank, store.get, config.llm_available, config.WINDOW_RADIUS, config.AUTH_SCHEME)
main.rank = lambda idx, q, o, recall_question=None: dense
store.get = lambda uid: index
config.llm_available = lambda: False
config.WINDOW_RADIUS, config.AUTH_SCHEME = 0, "none"
request = main.SearchRequest(query="KeyError: 'token' auth/session.py", user_id="u", top_k=100)
returned = [r["id"] for r in main.search(request, None, None)["data"]]
(main.rank, store.get, config.llm_available, config.WINDOW_RADIUS, config.AUTH_SCHEME) = saved_main
config.LEXICAL = saved
ok &= check(f"aaaaaaaaaaaaaaaa-r{target}" in returned and len(returned) == 100,
            "/search returns the literal match within top_k=100 and still respects top_k")
ok &= check(config.LEXICAL is False, "the channel is off by default")

print("\nall lexical checks passed" if ok else "\nLEXICAL CHECKS FAILED")
sys.exit(0 if ok else 1)
