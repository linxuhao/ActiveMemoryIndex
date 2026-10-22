"""Guard on multimodal message content (FAQ Q23: an image field must not fail Add).

Content may be a list of parts. The service is text-only: it keeps the text
parts in order, drops images, and stores the Add instead of rejecting it with
422. A plain string is unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, main  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True
config.AUTH_SCHEME = "none"
config.LLM_API_KEY = ""
client = TestClient(main.app)
client.__enter__()  # runs startup: opens the store

image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
mixed = [{"type": "text", "text": "This is my new bike,"}, image, {"type": "text", "text": "a red Bianchi."}]

ok &= check(main.Message(role="user", content="plain text").content == "plain text", "a string is unchanged")
ok &= check(main.Message(role="user", content=mixed).content == "This is my new bike,\na red Bianchi.",
            "text parts are kept in order and the image is dropped")
ok &= check(main.Message(role="user", content=[image]).content == "", "an image-only message becomes empty")

r = client.post("/add", json={"request_id": "m1", "user_id": "mu", "session_id": "s", "messages": [
    {"role": "user", "content": mixed},
    {"role": "user", "content": [image]},
    {"role": "assistant", "content": "Nice bike!"}]})
ok &= check(r.status_code == 200, "an Add with image parts returns 200, not 422")
r = client.post("/search", json={"query": "What colour is my bike?", "user_id": "mu", "top_k": 10})
contents = [d["content"] for d in r.json()["data"]]
ok &= check(any("red Bianchi" in c for c in contents), "the text of a mixed message is searchable")
ok &= check(not any("base64" in c or "image_url" in c for c in contents), "no image data is stored or returned")

r = client.post("/add", json={"request_id": "m2", "user_id": "mu", "session_id": "s",
                              "messages": [{"role": "user", "content": [image]}]})
ok &= check(r.status_code == 200, "an image-only Add returns 200")
r = client.post("/add", json={"request_id": "m3", "user_id": "mu", "session_id": "s",
                              "messages": [{"role": "user", "content": 42}]})
ok &= check(r.status_code == 422, "content that is neither text nor parts is still rejected")

sys.exit(0 if ok else 1)
