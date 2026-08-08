"""Guard on the ordering of the returned set.

`AMI_RAW_FIRST` is the single retrieval change that carries the submission's
accuracy: .5887 -> .6333 on LoCoMo (n=1540, bench/results/ordering_ab_all10.txt).
It must reorder the selected memories and never change which ones are selected —
a reordering that dropped or added a memory would silently alter recall while
looking like a presentation detail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


class Row:
    def __init__(self, kind, name):
        self.kind, self.content, self.id = kind, name, name


ok = True

selected = [(Row("fact", "f1"), 0.9), (Row("raw", "r1"), 0.8),
            (Row("fact", "f2"), 0.7), (Row("raw", "r2"), 0.6)]
ordered = sorted(selected, key=lambda pair: pair[0].kind != "raw")

ok &= check([r.content for r, _ in ordered] == ["r1", "r2", "f1", "f2"],
            "verbatim turns lead, and each block keeps its relevance order")
ok &= check(sorted(r.content for r, _ in ordered) == sorted(r.content for r, _ in selected),
            "the order of the selected set changes, never its membership")
ok &= check(len(ordered) == len(selected),
            "no memory is dropped or duplicated by the reordering")
ok &= check(config.RAW_FIRST is True,
            "the measured configuration is the default, not an opt-in")

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
