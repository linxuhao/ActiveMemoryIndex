"""Guards on the two ways the write path can silently poison the store."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm  # noqa: E402

REASONING = """<think>
Here's a thinking process:
**Analyze the Input:**
Participants: User (Caroline), Assistant (Melanie)
</think>

{"facts": ["I adopted a beagle named Ollie.", "My sister Mei lives in Kyoto."]}"""

TRUNCATED_REASONING = """<think>
Here's a thinking process:
1. Analyze the input.
2. Date/Time: 2023-05-08 13:56 to 14:13
3. Participants: User (Caroline)"""


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True
ok &= check(llm._strip_reasoning(REASONING).startswith('{"facts"'),
            "a closed reasoning block is removed and the payload survives")
ok &= check(llm._strip_reasoning(TRUNCATED_REASONING) == "",
            "an unterminated reasoning block yields nothing, not prose")
ok &= check(llm._parse_facts(llm._strip_reasoning(REASONING)) ==
            ["I adopted a beagle named Ollie.", "My sister Mei lives in Kyoto."],
            "facts parse out of the JSON payload")
ok &= check(llm._parse_facts("Here's a thinking process:\nAnalyze the input.\nParticipants: two") == [],
            "prose is never accepted as facts by the bare-list fallback")
ok &= check(llm._parse_facts("- I bought Asics on Tuesday.\n- [2023-05-20] I adopted Ollie.") ==
            ["I bought Asics on Tuesday.", "[2023-05-20] I adopted Ollie."],
            "a genuine bullet list is still accepted")

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
