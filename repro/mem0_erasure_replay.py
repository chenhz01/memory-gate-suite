#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
"""Minimal, dependency-light reproduction of VENDOR-TEST finding 1.

Claim under test: mem0 2.2.1's ``delete_all()`` leaves the conversation
buffer in SQLite, and the next ``add()`` replays it into the extraction
prompt, so erased text can be re-materialised.

Scope, stated up front: the LLM is a fixed-response stand-in and the embedder
is a constant vector. Nothing here measures model quality; the question is
what mem0 hands to the model after a successful delete.

    pip install "mem0ai==2.2.1"
    python repro/mem0_erasure_replay.py

Exit 0 = reproduced (erased text came back), 1 = not reproduced.
"""

from __future__ import annotations

import json
import os
import re
import tempfile

os.environ["MEM0_TELEMETRY"] = "False"
os.environ.setdefault("OPENAI_API_KEY", "sk-not-used")

from mem0 import Memory                                    # noqa: E402
from mem0.configs.llms.base import BaseLlmConfig           # noqa: E402
from mem0.embeddings.base import EmbeddingBase             # noqa: E402
from mem0.llms.base import LLMBase                         # noqa: E402

CANARY = "CANARY-7F3A9B"
FACT = re.compile(r"my access code is [A-Z0-9-]+")


class FixedLLM(LLMBase):
    """Returns whatever access-code fact it can see in the prompt."""

    def __init__(self) -> None:
        super().__init__(BaseLlmConfig(model="repro-stub"))
        self.prompts = []

    def generate_response(self, messages, tools=None, tool_choice="auto", **kw):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        facts = FACT.findall(prompt)
        return json.dumps({"memory": [
            {"id": str(i), "text": t, "event": "ADD"} for i, t in enumerate(facts)]})


class ConstEmbed(EmbeddingBase):
    def embed(self, text, memory_action=None):
        return [0.1] * 10

    def embed_batch(self, texts, memory_action=None):
        return [[0.1] * 10 for _ in texts]


def main() -> int:
    from mem0.configs.embeddings.base import BaseEmbedderConfig

    work = tempfile.mkdtemp(prefix="mem0-repro-")
    cfg = {
        "llm": {"provider": "openai", "config": {"model": "s", "api_key": "x"}},
        "embedder": {"provider": "openai",
                     "config": {"model": "s", "api_key": "x",
                                "embedding_dims": 10}},
        "vector_store": {"provider": "qdrant", "config": {
            "collection_name": "repro",
            "path": os.path.join(work, "qdrant"),
            "embedding_model_dims": 10, "on_disk": True}},
        "history_db_path": os.path.join(work, "history.db"),
    }
    mem = Memory.from_config(cfg)
    stub = FixedLLM()
    mem.llm = stub
    mem.embedding_model = ConstEmbed(BaseEmbedderConfig(model="s",
                                                        embedding_dims=10))

    mem.add([{"role": "user", "content": f"my access code is {CANARY}"}],
            user_id="u1")
    stored = mem.get_all(filters={"user_id": "u1"}).get("results", [])
    print(f"[1] stored after add          : {len(stored)} record(s)")

    mem.delete_all(user_id="u1")
    left = mem.get_all(filters={"user_id": "u1"}).get("results", [])
    print(f"[2] delete_all returned       : success")
    print(f"[3] records in vector store   : {len(left)}")

    rows = mem.db.connection.execute(
        "SELECT role, content FROM messages").fetchall()
    kept = [r for r in rows if CANARY in (r[1] or "")]
    print(f"[4] messages table rows       : {len(rows)} "
          f"({len(kept)} still carry the canary)")

    before = len(stub.prompts)
    mem.add([{"role": "user", "content": "anything else you need?"}],
            user_id="u1")
    new_prompt = stub.prompts[before] if len(stub.prompts) > before else ""
    print(f"[5] next extraction prompt    : "
          f"{'CONTAINS the erased text' if CANARY in new_prompt else 'clean'}")

    back = mem.get_all(filters={"user_id": "u1"}).get("results", [])
    texts = [r.get("memory", "") for r in back]
    print(f"[6] records after that add    : {len(texts)} -> {texts}")

    reproduced = any(CANARY in t for t in texts)
    print("\nRESULT:", "REPRODUCED -- erased text re-materialised after a "
          "successful delete" if reproduced else "NOT REPRODUCED")
    return 0 if reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
