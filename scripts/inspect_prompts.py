"""Print what the LLM does on both paths, for prompt calibration across models.

Run it once against the model you develop with and once against gpt-4o-mini,
then diff the output — the leaderboard reproduces the submission with
gpt-4o-mini, so the prompts must not depend on a local model's habits.

    OPENAI_API_KEY=... AMI_LLM_MODEL=gpt-4o-mini python scripts/inspect_prompts.py
    OPENAI_BASE_URL=http://127.0.0.1:8001/v1 OPENAI_API_KEY=x \
        AMI_LLM_MODEL=<local-model> python scripts/inspect_prompts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, llm  # noqa: E402

CHUNK = """[2023-05-20 14:00] user: I adopted a beagle puppy named Ollie last Saturday from the shelter in Malmo.
[2023-05-20 14:01] assistant: Congratulations! How is Ollie settling in?
[2023-05-20 14:02] user: He chewed my running shoes, so I bought new Asics on Tuesday. My sister Mei keeps telling me to crate-train him.
[2023-05-20 14:05] assistant: Crate training usually helps with chewing.
[2023-05-20 14:07] user: Maybe. I am also saving for a 35mm lens for Mei's wedding in Kyoto in October; my budget is about 900 euros."""

QUESTIONS = [
    ("What is the name of the dog?", None),
    ("Where is the wedding taking place?", None),
    ("How much does the user plan to spend on a lens?", None),
    ("What would the user most likely do this weekend?",
     ["A. Train the puppy", "B. Fly to Kyoto", "C. Sell the camera"]),
]

print(f"model      : {config.LLM_MODEL}")
print(f"base_url   : {config.LLM_BASE_URL or 'api.openai.com'}")
print(f"key present: {config.llm_available()}\n")

print("=== add path: extracted facts ===")
for fact in llm.extract_facts(CHUNK):
    print(f"  - {fact}")

print("\n=== search path: user-voice recall questions ===")
for question, options in QUESTIONS:
    print(f"  Q : {question}")
    print(f"  -> {llm.recall_question(question, options)}\n")
