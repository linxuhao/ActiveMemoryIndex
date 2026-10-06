"""AMI_EXTRACT_FALLBACK (lead L5, P2): a second, content prompt only for a chunk
the shipped extraction prompt returns no facts for; chat is untouched."""
import json
import types
import unittest
from unittest.mock import patch

from app import config, llm


class Chat:
    def __init__(self, replies):
        self.replies, self.systems = replies, []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        system = kw["messages"][0]["content"]
        self.systems.append("content" if system.startswith(llm.EXTRACT_CONTENT_SYSTEM[:60]) else "shipped")
        reply = self.replies[len(self.systems) - 1]
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content=json.dumps({"facts": reply})))])


class FallbackTests(unittest.TestCase):
    def run_extract(self, replies, enabled):
        chat = Chat(replies)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=chat), \
                patch.object(config, "EXTRACT_FALLBACK", enabled):
            facts = llm.extract_facts("user: The curtain rises on a small parlour.")
        return facts, chat.systems

    def test_off_by_default(self):
        self.assertFalse(config.EXTRACT_FALLBACK)
        facts, systems = self.run_extract([[]], enabled=False)
        self.assertEqual((facts, systems), ([], ["shipped"]))

    def test_zero_facts_get_the_content_prompt(self):
        facts, systems = self.run_extract([[], ["A small parlour is shown when the curtain rises."]], enabled=True)
        self.assertEqual(systems, ["shipped", "content"])
        self.assertEqual(facts, ["A small parlour is shown when the curtain rises."])

    def test_chat_with_facts_is_extracted_exactly_as_before(self):
        facts, systems = self.run_extract([["I adopted a beagle named Ollie."]], enabled=True)
        self.assertEqual(systems, ["shipped"])
        self.assertEqual(facts, ["I adopted a beagle named Ollie."])


if __name__ == "__main__":
    unittest.main()
