# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""mem0 adapter -- run the six gates against mem0's real OSS code path.

What is real here
-----------------
* ``mem0.Memory`` itself: ``add``, ``search``, ``get_all``, ``delete``,
  ``delete_all``, the SQLite history/messages tables, the Qdrant (local)
  vector store, hash de-duplication, BM25 + vector hybrid ranking.
* mem0 2.2.1's V3 phased pipeline: context gathering -> existing-memory
  retrieval -> extraction -> dedup -> persist -> history -> entity linking.

What is NOT real here (and is labelled as such in every report)
--------------------------------------------------------------
* The **extraction model** is replaced by ``DeterministicExtractor``: a
  rule-based stand-in that lifts declarative sentences out of the prompt's
  message sections.  MGP's ``re_extraction`` layer is ``model_dependent`` by
  protocol; this adapter makes it reproducible instead of pretending a real
  model was used.
* The **embedder** returns a constant vector (mem0 already ships the same idea
  as ``embeddings/mock.py``).  Ranking therefore comes from mem0's BM25 side,
  which is what we want to test -- not the embedding provider's quality.

Honest boundary: a verdict from this adapter says *"mem0's storage and
retrieval logic, driven by a deterministic extractor, behaves thus"*.  It does
**not** say *"mem0 in production with GPT-class extraction behaves thus"*.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from ..adapters import MemoryAdapter
from ..ledger import Ledger

# ---------------------------------------------------------------------------
# mem0 imports are optional: the core suite must run without them.
# ---------------------------------------------------------------------------
try:
    from mem0 import Memory
    import mem0 as _mem0

    MEM0_AVAILABLE = True
    MEM0_VERSION = getattr(_mem0, "__version__", "unknown")
except Exception:                                      # noqa: BLE001
    Memory = None                                      # type: ignore
    MEM0_AVAILABLE = False
    MEM0_VERSION = "not-installed"

try:
    from mem0.llms.base import LLMBase as _LLMBase
    from mem0.configs.llms.base import BaseLlmConfig as _BaseLlmConfig
except Exception:                                      # noqa: BLE001
    _LLMBase = object                                  # type: ignore
    _BaseLlmConfig = None                              # type: ignore

try:
    from mem0.embeddings.base import EmbeddingBase as _EmbeddingBase
    from mem0.configs.embeddings.base import BaseEmbedderConfig as _BaseEmbedderConfig
except Exception:                                      # noqa: BLE001
    _EmbeddingBase = object                            # type: ignore
    _BaseEmbedderConfig = None                         # type: ignore

EMBED_DIMS = 10

# The sections mem0's additive-extraction prompt uses for conversation turns.
_MSG_SECTIONS = re.compile(
    r"## (?:Last k Messages|New Messages)\n(.*?)(?=\n## |\Z)", re.S)
_SPEAKER = re.compile(r"^(?:user|assistant|system|human|ai)\s*:\s*", re.I)
_SENTENCE = re.compile(r"[^.!?\n]{12,300}")


def extract_message_facts(prompt: str) -> List[str]:
    """Lift declarative sentences out of the prompt's message sections.

    Deliberately generous: a real extraction model treats everything the user
    said as candidate material, including text that arrived through a session
    buffer rather than the current turn.  Being generous here is what makes
    re-materialisation observable at all.
    """
    out: List[str] = []
    seen = set()
    for section in _MSG_SECTIONS.findall(prompt or ""):
        for raw_line in section.splitlines():
            line = _SPEAKER.sub("", raw_line.strip())
            if not line or line.startswith("#"):
                continue
            for sentence in _SENTENCE.findall(line):
                s = " ".join(sentence.split()).strip(" -–—,;:")
                if len(s) < 12 or " " not in s:
                    continue
                low = s.lower()
                if low in seen:
                    continue
                seen.add(low)
                out.append(s)
    return out


class DeterministicExtractor(_LLMBase):                # type: ignore[misc]
    """Stand-in for the extraction model.  Deterministic, inspectable."""

    def __init__(self, model: str = "mgate-deterministic-extractor") -> None:
        if _BaseLlmConfig is not None:
            super().__init__(_BaseLlmConfig(model=model))
        self.prompts: List[str] = []

    def clear(self) -> None:
        self.prompts.clear()

    def generate_response(self, messages, tools=None, tool_choice="auto",
                          **kwargs):                   # noqa: D401
        user_prompt = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                user_prompt = m.get("content", "")
                break
        self.prompts.append(user_prompt)
        facts = extract_message_facts(user_prompt)
        return json.dumps({
            "memory": [
                {"id": str(i), "text": t, "event": "ADD", "old_memory": None}
                for i, t in enumerate(facts)
            ]
        })


class ConstantEmbedder(_EmbeddingBase):                # type: ignore[misc]
    """Constant vector: ranking is decided by mem0's BM25 side, not by us."""

    def __init__(self, dims: int = EMBED_DIMS) -> None:
        if _BaseEmbedderConfig is not None:
            try:
                super().__init__(_BaseEmbedderConfig(model="mgate-constant",
                                                     embedding_dims=dims))
            except Exception:                          # noqa: BLE001
                pass
        self.dims = dims

    def embed(self, text, memory_action=None):
        return [0.1] * self.dims

    def embed_batch(self, texts, memory_action=None):
        return [[0.1] * self.dims for _ in texts]


def _ranking_signal() -> str:
    """What does mem0's result ordering actually encode here?

    Constant embeddings contribute nothing to ranking.  mem0's hybrid search
    then falls back to its lexical (BM25) side -- which needs fastembed plus
    a downloaded model.  When that is absent, positions reflect insertion
    order, so the honest answer is ``none`` and the gates must abstain rather
    than manufacture a ranking finding.
    """
    try:
        import fastembed  # noqa: F401
    except Exception:                                  # noqa: BLE001
        return "none"
    cache = os.environ.get("FASTEMBED_CACHE_PATH") or os.path.join(
        os.path.expanduser("~"), ".cache", "fastembed")
    try:
        names = os.listdir(cache)
    except OSError:
        return "none"
    return "lexical" if any("bm25" in n.lower() for n in names) else "none"


class Mem0Adapter(MemoryAdapter):
    """MGP adapter over ``mem0.Memory`` (OSS, in-process, no network)."""

    name = "mem0"
    version = MEM0_VERSION

    def __init__(self, *, ledger: Optional[Ledger] = None,
                 workspace: Optional[str] = None) -> None:
        if not MEM0_AVAILABLE:
            raise RuntimeError(
                "mem0 is not installed. `pip install mem0ai` (2.2.x) and "
                "re-run with --adapter mem0")
        super().__init__(ledger)
        self._workspace = workspace or tempfile.mkdtemp(prefix="mgate-mem0-")
        self._owns_workspace = workspace is None
        self._workdir = ""
        self._mem: Any = None
        self.extractor = DeterministicExtractor()
        self.ranking_signal = _ranking_signal()
        self._erase_calls: List[Dict[str, Any]] = []

    # -- lifecycle --------------------------------------------------------
    def setup(self, *, reset: bool = True) -> None:
        self._teardown()
        self._workdir = tempfile.mkdtemp(dir=self._workspace, prefix="run-")
        cfg = {
            "llm": {"provider": "openai",
                    "config": {"model": "stub", "api_key": "unused"}},
            "embedder": {"provider": "openai",
                         "config": {"model": "stub", "api_key": "unused",
                                    "embedding_dims": EMBED_DIMS}},
            "vector_store": {"provider": "qdrant", "config": {
                "collection_name": "mgate",
                "path": os.path.join(self._workdir, "qdrant"),
                "embedding_model_dims": EMBED_DIMS,
                "on_disk": True,
            }},
            "history_db_path": os.path.join(self._workdir, "history.db"),
        }
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        os.environ.setdefault("OPENAI_API_KEY", "sk-mgate-unused")
        self._mem = Memory.from_config(cfg)
        self._mem.llm = self.extractor           # replace before first add
        self._mem.embedding_model = ConstantEmbedder(EMBED_DIMS)
        self.extractor.clear()
        self.ledger.record("setup", msg="mem0 store reset",
                           extra={"workdir": self._workdir})

    def _teardown(self) -> None:
        if self._mem is not None:
            try:
                client = getattr(self._mem.vector_store, "client", None)
                if client is not None:
                    client.close()
            except Exception:                          # noqa: BLE001
                pass
            try:
                self._mem.db.close()
            except Exception:                          # noqa: BLE001
                pass
            self._mem = None

    # -- core verbs -------------------------------------------------------
    def add(self, messages: Sequence[Dict[str, str]], *,
            user_id: str = "u1") -> List[str]:
        res = self._mem.add(list(messages), user_id=user_id)
        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        ids = [str(i.get("id")) for i in items if i.get("id")]
        self.ledger.record("add", msg=f"{len(ids)} new record(s)",
                           extra={"ids": ids, "user_id": user_id})
        return ids

    def retrieve(self, query: str, *, user_id: str = "u1",
                 limit: int = 5) -> List[Dict[str, Any]]:
        res = self._mem.search(query, filters={"user_id": user_id},
                               top_k=limit)
        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        hits = []
        for it in items:
            hits.append({
                "id": str(it.get("id", "")),
                "text": it.get("memory", "") or "",
                "score": it.get("score"),
            })
        self.ledger.record("retrieve", msg=f"{len(hits)} hit(s)",
                           extra={"query": query, "ids": [h["id"] for h in hits]})
        return hits

    def erase_scope(self, *, user_id: str = "u1") -> int:
        rows = self._records(user_id)
        self._mem.delete_all(user_id=user_id)
        self._erase_calls.append({"path": "scope", "user_id": user_id,
                                  "removed": len(rows)})
        self.ledger.record("erase_scope", msg=f"delete_all -> {len(rows)} rows",
                           extra={"user_id": user_id})
        return len(rows)

    def erase_record(self, *, memory_id: str) -> bool:
        try:
            self._mem.delete(memory_id)
            ok = True
        except Exception:                              # noqa: BLE001
            ok = False
        self._erase_calls.append({"path": "record", "memory_id": memory_id,
                                  "removed": 1 if ok else 0})
        self.ledger.record("erase_record", msg=f"delete id={memory_id[:8]}",
                           extra={"ok": ok})
        return ok

    # -- observation ------------------------------------------------------
    def extraction_prompts(self) -> List[str]:
        return list(self.extractor.prompts)

    def raw_rows(self) -> List[Dict[str, Any]]:
        """Records + history audit rows + the session message buffer.

        The last two are the point: ``delete_all`` empties the vector store but
        mem0 keeps both tables on disk, and the messages table is replayed into
        the next extraction prompt as ``Last k Messages``.
        """
        rows: List[Dict[str, Any]] = []
        try:
            got = self._mem.get_all(filters={"user_id": "u1"}, top_k=1000)
            items = got.get("results", []) if isinstance(got, dict) else (got or [])
            for it in items:
                rows.append({"id": str(it.get("id", "")),
                             "text": it.get("memory", "") or "",
                             "kind": "record"})
        except Exception:                              # noqa: BLE001
            pass
        try:
            cur = self._mem.db.connection.execute(
                "SELECT memory_id, new_memory, old_memory, event, is_deleted "
                "FROM history")
            for mid, new_m, old_m, ev, deleted in cur.fetchall():
                rows.append({"id": str(mid), "text": new_m or "",
                             "old_text": old_m or "", "event": ev,
                             "is_deleted": bool(deleted), "kind": "audit"})
        except Exception:                              # noqa: BLE001
            pass
        try:
            cur = self._mem.db.connection.execute(
                "SELECT session_scope, role, content FROM messages")
            for scope, role, content in cur.fetchall():
                rows.append({"id": str(scope), "text": content or "",
                             "role": role, "kind": "session"})
        except Exception:                              # noqa: BLE001
            pass
        return rows

    def _records(self, user_id: str = "u1") -> List[Dict[str, Any]]:
        try:
            got = self._mem.get_all(filters={"user_id": user_id}, top_k=1000)
        except Exception:                              # noqa: BLE001
            return []
        items = got.get("results", []) if isinstance(got, dict) else (got or [])
        return [{"id": str(i.get("id", "")), "text": i.get("memory", "")}
                for i in items]

    def checkpoint(self) -> None:
        self.extractor.clear()

    def stats(self) -> Dict[str, Any]:
        return {
            "store": self.name,
            "version": self.version,
            "adapter": type(self).__name__,
            "records": len(self._records()),
            "defects": "n/a (vendor store)",
            "extraction_model": "deterministic-extractor (not a real LLM)",
            "lexical_search": "enabled" if self.ranking_signal != "none"
                              else "disabled (fastembed/bm25 unavailable)",
            "embedder": f"constant-{EMBED_DIMS}d",
            "ranking_signal": self.ranking_signal,
            "vector_store": "qdrant-local",
            "erases": list(self._erase_calls),
        }

    def __del__(self):                                 # pragma: no cover
        try:
            self._teardown()
            if self._owns_workspace:
                shutil.rmtree(self._workspace, ignore_errors=True)
        except Exception:                              # noqa: BLE001
            pass


def build(**kwargs: Any) -> Mem0Adapter:
    return Mem0Adapter(**kwargs)
