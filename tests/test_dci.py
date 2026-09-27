"""AMI_DCI_SEARCH: an agent greps and reads the store and names ids to return.

Pins: the agent can only return ids that exist (nothing it writes reaches the
response); its order is kept; unknown ids are dropped; the limit holds; grep
shows context from the same file; the budget forces a finish; an API failure
falls back to the ordinary selection; arm `dcifill` puts the agent's ids first
and fills the rest without duplicates. Run directly: python tests/test_dci.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, dci, llm, main, store  # noqa: E402

ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


A, B = "a" * 16, "b" * 16
items = [
    store.Item(id=f"{A}-r0", kind="raw", parent_id=None, content="[2023-05-01 10:00] I: I go to the gym at 7 pm on Tuesdays.", created_at="2023-05-01T10:00:00Z"),
    store.Item(id=f"{A}-r1", kind="raw", parent_id=None, content="[2023-05-01 10:01] Assistant: Evening sessions are great.", created_at="2023-05-01T10:01:00Z"),
    store.Item(id=f"{A}-f0", kind="fact", parent_id=None, content="[2023-05-01] I go to the gym at 7 pm on Tuesdays.", created_at="2023-05-01T10:00:00Z"),
    store.Item(id=f"{B}-r0", kind="raw", parent_id=None, content="[2023-06-10 09:00] I: I moved my gym time to 6 pm, it is quieter.", created_at="2023-06-10T09:00:00Z"),
    store.Item(id=f"{B}-r1", kind="raw", parent_id=None, content="[2023-06-10 09:01] Assistant: Noted, 6 pm it is.", created_at="2023-06-10T09:01:00Z"),
    store.Item(id=f"{B}-r2", kind="raw", parent_id=None, content="[2023-06-10 09:02] I: Also I adopted a cat named Max.", created_at="2023-06-10T09:02:00Z"),
]
index = store.UserIndex()
index.append(items, np.eye(6, dtype=np.float32))

# --- Corpus tools --------------------------------------------------------------
corpus = dci.Corpus(index)
listing = corpus.listing()
check(A in listing and B in listing and "facts  1 lines" in listing, "listing names each chunk file and the facts file")
hit = corpus.grep("6 pm", 1)
check(f"{B}-r0" in hit and f"{B}-r1" in hit and f"{A}-r0" not in hit, "grep matches by regex, case-insensitive, with same-file context")
check(corpus.grep("[", 0).startswith("invalid regular expression"), "a bad regex is reported, not raised")
check(corpus.grep("zzzz") == "no matches", "no hits says so")
page = corpus.read(B, 1, 5)
check(f"{B}-r1" in page and f"{B}-r2" in page and f"{B}-r0" not in page, "read shows the requested line range of one file, clamped")
check(corpus.read("facts", 0, 0).startswith(f"{A}-f0"), "read on 'facts' pages the facts file")
check(corpus.read("nope", 0, 1) == "no such file", "unknown file is reported")


# --- a scripted model --------------------------------------------------------
def scripted(*replies):
    replies = list(replies)
    seen = []

    def fake(messages, tools, max_tokens, tool_choice=None):
        seen.append((messages, tools, tool_choice))
        if not replies:
            return None
        return replies.pop(0)
    fake.seen = seen
    return fake


def tool(name, **args):
    return {"id": f"call_{name}_{len(args)}", "name": name, "arguments": json.dumps(args)}


saved = (llm.chat_tools, config.llm_available, config.DCI_BUDGET)
config.llm_available = lambda: True

# 1. grep -> read -> finish with a made-up id and a duplicate; order kept, limit holds
llm.chat_tools = scripted(
    {"content": "", "tool_calls": [tool("grep", pattern="gym", context=1)]},
    {"content": "", "tool_calls": [tool("read", file=B, start=0, end=1)]},
    {"content": "", "tool_calls": [tool("finish", ids=[f"{B}-r0", "made-up-id", f"{B}-r1", f"{B}-r0", f"{A}-r0"])]},
)
picked = dci.run(index, "What time do I go to the gym?", None, limit=2)
check([it.id for it in picked] == [f"{B}-r0", f"{B}-r1"], "finish returns existing ids only, agent order, deduplicated, capped at the limit")
tool_messages = [m for m in llm.chat_tools.seen[-1][0] if m.get("role") == "tool"]
check(len(tool_messages) == 2 and "6 pm" in tool_messages[0]["content"], "each tool call's result is fed back to the model")

# 2. budget exhausted: the next call is restricted to finish
config.DCI_BUDGET = 1
llm.chat_tools = scripted(
    {"content": "", "tool_calls": [tool("grep", pattern="cat")]},
    {"content": "", "tool_calls": [tool("finish", ids=[f"{B}-r2"])]},
)
picked = dci.run(index, "What is my cat called?", None, limit=5)
_, tools_offered, choice = llm.chat_tools.seen[-1]
check([it.id for it in picked] == [f"{B}-r2"] and len(tools_offered) == 1 and choice == dci.FORCE_FINISH,
      "after the budget the model is offered finish only, and forced to call it")
config.DCI_BUDGET = saved[2]

# 3. the model answers in prose instead of using tools: nudged once, then None
llm.chat_tools = scripted(
    {"content": "You go at 6 pm.", "tool_calls": []},
    {"content": "Still 6 pm.", "tool_calls": []},
)
check(dci.run(index, "q", None, limit=5) is None, "a model that will not use tools yields None (fallback), never its prose")

# 4. API failure -> None
llm.chat_tools = scripted()
check(dci.run(index, "q", None, limit=5) is None, "an API failure yields None")

# --- persistent searcher (AMI_DCI_MIN_CALLS) ----------------------------------
check("Stop as soon as" in dci.system_prompt(5) and "later restatements" not in dci.system_prompt(5),
      "min calls 0: the early-stop instruction stands")
config.DCI_MIN_CALLS = 2
check("Stop as soon as" not in dci.system_prompt(5) and "later restatements" in dci.system_prompt(5)
      and f"You have {config.DCI_BUDGET} tool calls" in dci.system_prompt(5),
      "min calls > 0: early stop dropped, persistence and budget stated")
llm.chat_tools = scripted(
    {"content": "", "tool_calls": [tool("grep", pattern="gym")]},
    {"content": "", "tool_calls": [tool("finish", ids=[f"{A}-r0"])]},          # refused: 1 of 2
    {"content": "", "tool_calls": [tool("grep", pattern="gym time", context=1)]},
    {"content": "", "tool_calls": [tool("finish", ids=[f"{B}-r0"])]},          # accepted: 3 calls done
)
before_refused, before_calls = dci.counters["refused"], dci.counters["tool_calls"]
picked = dci.run(index, "What time do I go to the gym?", None, limit=5)
refusal = [m for m in llm.chat_tools.seen[-1][0] if m.get("role") == "tool" and m["content"].startswith("Not yet")]
check([it.id for it in picked] == [f"{B}-r0"] and len(refusal) == 1 and "1 of at least 2" in refusal[0]["content"],
      "a finish before the minimum is refused with the reason, and the later finish is accepted")
check(dci.counters["refused"] == before_refused + 1 and dci.counters["tool_calls"] == before_calls + 2,
      "refusals are counted apart from grep/read tool calls")
config.DCI_BUDGET, config.DCI_MIN_CALLS = 1, 3
llm.chat_tools = scripted(
    {"content": "", "tool_calls": [tool("grep", pattern="cat")]},
    {"content": "", "tool_calls": [tool("finish", ids=[f"{B}-r2"])]},
)
picked = dci.run(index, "What is my cat called?", None, limit=5)
check([it.id for it in picked] == [f"{B}-r2"] and llm.chat_tools.seen[-1][2] == dci.FORCE_FINISH,
      "at the budget the forced finish is accepted even below the minimum")
config.DCI_BUDGET = saved[2]
config.DCI_MIN_CALLS = 0

# --- through search(): membership and the fill arm -----------------------------
saved_main = (main.rank, store.get, config.AUTH_SCHEME, config.WINDOW_RADIUS, config.DCI_SEARCH,
              config.DCI_FILL, config.FACT_EVIDENCE)
main.rank = lambda index, query, options, recall_question=None: np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1], dtype=np.float32)
store.get = lambda user_id: index
config.AUTH_SCHEME = "none"
config.WINDOW_RADIUS = 0
config.FACT_EVIDENCE = 0
request = main.SearchRequest(query="gym time?", user_id="u", top_k=4)

config.DCI_SEARCH = False
base_ids = [row["id"] for row in main.search(request, None, None)["data"]]
check(base_ids[:1] == [f"{A}-r0"], "switch off: ordinary selection")

config.DCI_SEARCH = True
config.DCI_FILL = False
llm.chat_tools = scripted({"content": "", "tool_calls": [tool("finish", ids=[f"{B}-r0", f"{B}-r1"])]})
data = main.search(request, None, None)["data"]
check([row["id"] for row in data] == [f"{B}-r0", f"{B}-r1"], "arm dci: exactly the agent's ids, agent order")
check(all(row["content"] == index.items[index.by_id[row["id"]]].content for row in data), "returned text is the stored text, untouched")
check(data[0]["score"] > data[1]["score"], "scores descend with the agent's order")

config.DCI_FILL = True
llm.chat_tools = scripted({"content": "", "tool_calls": [tool("finish", ids=[f"{B}-r0", f"{B}-r1"])]})
ids = [row["id"] for row in main.search(request, None, None)["data"]]
check(ids[:2] == [f"{B}-r0", f"{B}-r1"] and len(ids) == 4 and len(set(ids)) == 4 and f"{A}-r0" in ids,
      "arm dcifill: agent's ids first, then the ordinary selection fills to top_k without duplicates")

llm.chat_tools = scripted()
before = dci.counters["fallbacks"]
ids = [row["id"] for row in main.search(request, None, None)["data"]]
check(ids == base_ids and dci.counters["fallbacks"] == before + 1, "agent failure falls back to the ordinary selection and is counted")

llm.chat_tools, config.llm_available, config.DCI_BUDGET = saved
(main.rank, store.get, config.AUTH_SCHEME, config.WINDOW_RADIUS, config.DCI_SEARCH,
 config.DCI_FILL, config.FACT_EVIDENCE) = saved_main

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
