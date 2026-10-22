"""Grouped return on the proxy: semantic block first, then a grep block of hits
not already shown. Lists come from the dense and grep-only arms at top_k=100."""
import collections, json, math, sys
from pathlib import Path
sys.path.insert(0, "/src")
import numpy as np
from bench import grep_study as gs
from app import config, lexical, main, store

data = Path(sys.argv[1])
experience = {t["instance_id"]: t for t in gs.load(data / "SWEContextBench_Experience.jsonl")}
related = {t["instance_id"]: t for t in gs.load(data / "SWEContextBench_Related.jsonl")}
links = collections.defaultdict(set)
for row in gs.load(data / "SWEContextBench_Relationship.jsonl"):
    links[row["related_instance_id"]].add(row["experience_instance_id"])
store.init()
owner = {}
for task in experience.values():
    owner[store.item_id(task["instance_id"], "raw", 0, task["repo"]).rsplit("-", 1)[0]] = task["instance_id"]
queries = []
for rid, task in sorted(related.items()):
    gold = links[rid] & set(experience)
    if not gold:
        continue
    paths = " ".join(dict.fromkeys(gs.DIFF_FILE.findall(task["patch"])))
    for form, text in (("issue", task["problem_statement"]), ("paths", paths)):
        if text.strip():
            queries.append((rid, form, text, task["repo"], gold))

dense_fuse = lexical.fuse
def grep_only(user_index, scores, query):
    with store._lock:
        lex = lexical._index(user_index).scores(query)
    return np.where(np.isfinite(scores), lex.astype(np.float64), -np.inf)

def ids(text, user, grep):
    config.LEXICAL = grep
    lexical.fuse = grep_only if grep else dense_fuse
    out = main.search(main.SearchRequest(query=text, user_id=user, top_k=100), None, None)["data"]
    lexical.fuse = dense_fuse
    # grep block: only items that actually matched something
    return [d["id"] for d in out if not grep or d["score"] > 0]

def first(lst, gold):
    for i, x in enumerate(lst):
        if owner.get(x.rsplit("-", 1)[0]) in gold:
            return i + 1
    return None

rows = []
for rid, form, text, user, gold in queries:
    d, g = ids(text, user, False), ids(text, user, True)
    rec = {"form": form}
    for k in (10, 100):
        rec[f"dense@{k}"] = first(d[:k], gold) is not None
        for share in (0.2, 0.3, 0.5):
            b = int(k * share); a = k - b
            top = d[:a]; seen = set(top)
            block = [x for x in g if x not in seen][:b]
            merged = top + block
            if len(merged) < k:
                merged += [x for x in d[a:] if x not in set(merged)][: k - len(merged)]
            rec[f"split{int(share*100)}@{k}"] = first(merged, gold) is not None
    rows.append(rec)

for form in ("issue", "paths"):
    rs = [r for r in rows if r["form"] == form]
    for k in (10, 100):
        base = [r[f"dense@{k}"] for r in rs]
        line = f"{form:6} @{k:<3} dense {sum(base)/len(rs):.3f}"
        for s in (20, 30, 50):
            v = [r[f"split{s}@{k}"] for r in rs]
            w = sum(1 for x, y in zip(v, base) if x and not y); l = sum(1 for x, y in zip(v, base) if y and not x)
            n = w + l; p = min(1, 2 * sum(math.comb(n, i) for i in range(min(w, l) + 1)) / 2 ** n) if n else 1
            line += f" | grep{s}% {sum(v)/len(rs):.3f} (+{w}/-{l} p={p:.2g})"
        print(line)
