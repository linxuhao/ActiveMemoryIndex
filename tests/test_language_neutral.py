"""No language-dependent regex or word list in the release code (rc5 rule).

Real users write in any language; a pattern or a word list can only ever see
the few languages someone wrote it for. Every regex in app/ and every list of
words used for a membership test must be on the allowlist below, each with the
reason it is language-neutral. A new one fails this test until it is reviewed
and added -- and a language-dependent one must instead be a gpt-4o-mini call.

Run: python tests/test_language_neutral.py [APP_DIR]
"""
import ast
import os
import re
import sys
import unittest
from pathlib import Path

APP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "app"

# pattern -> why it is language-neutral
ALLOWED_PATTERNS = {
    r"^\[(?:said )?(\d{4})-(\d{2})-(\d{2})[^\]]*\]\s*": "our own stamp prefix (and its [said ...] re-render), ISO digits",
    r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\] ": "our own stamp prefix",
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] ": "our own stamp prefix",
    r"\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?\s*": "ISO date the model returns",
    r"\d{4}-\d{2}-\d{2}": "ISO date the model returns",
    r"(.+)-(?:c0|s(\d+)-(\d+))$": "our own chunk/span id format",
    r"(.+)-r(\d+)$": "our own raw-turn id format",
    r"([0-9a-f]{16})-([rf])(\d+)": "our own item id format",
    r"<think>.*?</think>\s*": "reasoning-model markup",
    r"\{.*\}": "JSON object extraction",
    r"^(?:[-*]|\d+[.)]|\[)": "list-line markers (bullet, number, bracket) in a fallback reply",
    r"^\s*(?:[-*]|\d+[.)])\s*": "list-line markers (bullet, number) in a fallback reply",
    r"^\s*[+-]\s*\d": "a sign in front of a number (relative value), digits as data",
    r'\{\s*"text"\s*:\s*"(?:[^"\\]|\\.)*"\s*(?:,\s*"key"\s*:\s*(?:null|"(?:[^"\\]|\\.)*"))?\s*\}':
        "JSON object salvage (AMI_FACT_KEYS research, off on the release path)",
    r"[^a-z0-9._]+": "fact-key normalisation to our snake_case key format (AMI_FACT_KEYS research, off on the "
                     "release path; Latin-only keys, reported in the rc5 audit)",
    r"[a-z]": "fact-key validity (AMI_FACT_KEYS research, off on the release path)",
}
# (file, expression) -> why: patterns built at run time
ALLOWED_DYNAMIC = {
    ("dci.py", "pattern[:200]"): "the DCI agent's own grep pattern (gpt-4o-mini writes it; AMI_DCI_SEARCH, off)",
    ("updates.py", "f'(?<![a-z0-9]){re.escape(cleaned)}(?![a-z0-9])'"):
        "verbatim containment of a value the model quoted (escaped literal, no word list)",
}
# (file, sorted words) -> why: string collections used as membership tests
ALLOWED_WORDS = {
    ("updates.py", ("i", "me")): "protocol tokens: stage 2's user marker 'me' and our own speaker label 'I'",
    ("updates.py", ("CORRECTION", "EXPLICIT_REPLACEMENT")): "stage-1 label enum",
    ("asof.py", ("as_of_state", "event_on_date", "other")): "classifier label enum",
    ("asof.py", ("about_period", "not_valid", "valid")): "item-judgement JSON keys",
    ("llm.py", ("n_a", "na", "none", "null")): "JSON null spellings in a model-written key (AMI_FACT_KEYS, off)",
    ("main.py", ("bearer", "token", "x-api-key")): "auth scheme enum",
    ("main.py", ("bearer", "token")): "HTTP Authorization scheme names",
    ("main.py", ("chunk", "raw")): "our own item kinds",
    ("updates.py", ("fact", "raw")): "our own item kinds",
    ("embed.py", ("bge", "openai")): "embedding backend enum",
    ("embed.py", ("http", "https")): "URL schemes",
    ("config.py", ("", "change-me", "changeme", "your-token-here")): "placeholder secrets",
}
REGEX_FUNCTIONS = {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}


def scan(app: Path):
    patterns, dynamic, words = [], [], []
    for path in sorted(app.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in REGEX_FUNCTIONS and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re" and node.args):
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    patterns.append((path.name, node.lineno, first.value))
                else:
                    dynamic.append((path.name, node.lineno, ast.unparse(first)))
            collection = None
            if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                collection = node.elts
            elif isinstance(node, ast.Dict):
                collection = [k for k in node.keys if k is not None]
            if collection is None:
                continue
            strings = [e.value for e in collection if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(strings) < 2 or len(strings) != len(collection):
                continue
            # A word list: every element is letters (any script), spaces or apostrophes.
            if all(re.fullmatch(r"[^\W\d_]+(?:[ '’-][^\W\d_]+)*", s) or s == "" for s in strings):
                if isinstance(node, ast.Dict) or isinstance(node, ast.List):
                    if len(strings) < 5:
                        continue  # small literal dicts/lists are JSON shapes, not vocabularies
                words.append((path.name, node.lineno, tuple(sorted(strings))))
    return patterns, dynamic, words


class LanguageNeutralTests(unittest.TestCase):
    def setUp(self):
        self.patterns, self.dynamic, self.words = scan(APP)

    def test_every_regex_is_allowlisted(self):
        unknown = [(f, n, p) for f, n, p in self.patterns if p not in ALLOWED_PATTERNS]
        self.assertEqual(unknown, [], "a regex in app/ that is not on the allowlist (language-neutral only)")

    def test_every_dynamic_regex_is_allowlisted(self):
        unknown = [(f, n, e) for f, n, e in self.dynamic if (f, e) not in ALLOWED_DYNAMIC]
        self.assertEqual(unknown, [], "a regex built at run time that is not on the allowlist")

    def test_no_word_list(self):
        unknown = [(f, n, w) for f, n, w in self.words
                   if (f, w) not in ALLOWED_WORDS and not all(x.isupper() or "_" in x for x in w)]
        self.assertEqual(unknown, [], "a list of words used in a decision (use gpt-4o-mini instead)")

    def test_known_language_dependent_names_are_gone(self):
        from app import asof, main, updates
        for module, names in ((asof, ["MON", "_MONTHS", "PATTERNS", "RANGE_JOIN", "RANGE_OPEN", "RELATIVE",
                                      "ANY_YEAR", "candidate", "ranges", "dates"]),
                              (updates, ["RELATIVE_WORDS", "HISTORY_QUESTION", "DATED_QUESTION", "DATED_CJK", "SELF",
                                         "_SCRIPTS", "_STOPWORDS", "same_language", "protected_question",
                                         "prefilter_protected"]),
                              (main, ["_TIME_HINT"])):
            for name in names:
                self.assertFalse(hasattr(module, name), f"{module.__name__}.{name}")

    def test_the_scanner_finds_what_it_must(self):
        """The scanner itself: it sees literal and run-time regexes and word sets."""
        sample = ('import re\nA = re.compile(r"\\b(?:yesterday|ayer)\\b")\nB = {"me", "my", "mine"}\n'
                  'def f(x):\n    return re.search(x, "s") or x in ("hier", "gestern")\n')
        directory = Path(os.environ.get("TMPDIR", "/tmp")) / "ami-language-neutral-scan"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "sample.py").write_text(sample, encoding="utf-8")
        patterns, dynamic, words = scan(directory)
        self.assertEqual([p for _, _, p in patterns], [r"\b(?:yesterday|ayer)\b"])
        self.assertEqual([e for _, _, e in dynamic], ["x"])
        self.assertEqual(sorted(w for _, _, w in words), [("gestern", "hier"), ("me", "mine", "my")])


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
