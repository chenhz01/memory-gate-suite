# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Adapters: the black-box seam between MGP gates and a concrete memory store.

A gate must never import a vendor SDK.  It talks to ``MemoryAdapter`` and
nothing else.  That is what lets the same verdict grammar cover mem0, Zep,
Letta, a custom pgvector store, or the reference stores shipped here.

Two things live in this module:

1. ``MemoryAdapter`` -- the 8-method contract.  Anything that implements it
   can be judged by every gate in the suite.
2. ``ReferenceStore`` -- a deliberately small, pure-Python memory store with
   switchable *defect modes*.  It is the suite's own falsification rig: the
   gates are tested against stores that are supposed to fail, so a green run
   proves the gate discriminates rather than that it always says pass.

The defect modes mirror real, documented failure shapes:
  resend_after_erase   extraction prompt still contains erased session
                       messages          <- mem0ai/mem0#7452 layer 1
  scope_keeps_records  delete_all removes the session but not the derived
                       memories          <- mem0#7452 layer 2
  surface_only_recall  retrieval matches on query/title token overlap only,
                       ignoring semantic distance   <- retrieval-influence-gate
  no_supersession      a updated fact never retires the old one  <- D3
  trust_all_writes     any injected instruction is stored verbatim <- D4

Zero dependencies.  Python >= 3.9.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .ledger import Ledger, NullLedger

CANARY_RE = re.compile(r"CANARY-[0-9A-Fa-f]{6,}")
_SLOT_RE = re.compile(r"^my\s+(?P<slot>[a-z][a-z ]{2,30}?)\s+is\s+", re.I)


class AdapterError(RuntimeError):
    pass


@dataclass
class Record:
    id: str
    text: str
    user_id: str = "u1"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source: str = "extraction"     # extraction | manual | injected
    trust: float = 1.0             # 0..1, set by the store's write policy
    superseded: bool = False       # replaced by a newer fact in the same slot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "text": self.text, "user_id": self.user_id,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "source": self.source, "trust": self.trust,
            "superseded": self.superseded,
        }


class MemoryAdapter:
    """The 8-method contract.  Subclass and override all of them.

    Methods are intentionally synchronous and boring: gates need determinism,
    not concurrency.  If your store is async, wrap it.
    """

    name = "unnamed"
    version = "0.0.0"

    def __init__(self, ledger: Optional[Ledger] = None) -> None:
        self.ledger: Ledger = ledger if ledger is not None else Ledger()

    # -- lifecycle --------------------------------------------------------
    def setup(self, *, reset: bool = True) -> None:
        raise NotImplementedError

    # -- core verbs -------------------------------------------------------
    def add(self, messages: Sequence[Dict[str, str]], *,
            user_id: str = "u1") -> List[str]:
        """Persist a conversation turn; return the ids of NEW memories."""
        raise NotImplementedError

    def retrieve(self, query: str, *, user_id: str = "u1",
                 limit: int = 5) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def erase_scope(self, *, user_id: str = "u1") -> int:
        """Delete-everything-for-a-user.  Returns count removed."""
        raise NotImplementedError

    def erase_record(self, *, memory_id: str) -> bool:
        raise NotImplementedError

    # -- observation ------------------------------------------------------
    def extraction_prompts(self) -> List[str]:
        """Prompts actually sent to the extraction model since last checkpoint.

        This is the single most important observation in the suite: it is what
        separates "the API said 200" from "the erased text was never handed to
        a model again".
        """
        raise NotImplementedError

    def raw_rows(self) -> List[Dict[str, Any]]:
        """Storage-level snapshot (including soft-deleted / audit rows)."""
        raise NotImplementedError

    def checkpoint(self) -> None:
        """Clear the prompt buffer.  Called by gates between phases."""
        raise NotImplementedError

    def stats(self) -> Dict[str, Any]:
        raise NotImplementedError


class ReferenceStore(MemoryAdapter):
    """Minimal extract-then-store memory with switchable defects.

    Not a competitor to any product.  It exists so the gates have a
    falsifiable target: flip one flag and the corresponding gate must go red.
    """

    name = "reference-store"
    version = "1.0.0"

    DEFECTS = {
        "resend_after_erase": False,
        "scope_keeps_records": False,
        "surface_only_recall": False,
        "no_supersession": False,
        "trust_all_writes": False,
    }

    def __init__(self, *, ledger: Optional[Ledger] = None,
                 defects: Optional[Dict[str, bool]] = None,
                 extraction_fidelity: float = 1.0,
                 clock: Optional[callable] = None) -> None:
        super().__init__(ledger)
        self.defects = dict(self.DEFECTS)
        if defects:
            unknown = set(defects) - set(self.DEFECTS)
            if unknown:
                raise AdapterError(f"unknown defect(s): {sorted(unknown)}")
            self.defects.update(defects)
        self.extraction_fidelity = extraction_fidelity
        self._clock = clock or time.time
        self.reset()

    # -- lifecycle --------------------------------------------------------
    def reset(self) -> None:
        self._records: List[Record] = []
        self._session: List[Dict[str, str]] = []   # raw conversation buffer
        self._prompts: List[str] = []
        self._audit: List[Dict[str, Any]] = []     # soft-deleted rows
        self._seq = 0
        self._call = 0

    def setup(self, *, reset: bool = True) -> None:
        if reset:
            self.reset()
        self.ledger.record("setup", store=self.name, version=self.version,
                           defects={k: v for k, v in self.defects.items() if v})

    # -- internals --------------------------------------------------------
    def _build_extraction_prompt(self, messages: Sequence[Dict[str, str]]) -> str:
        lines = ["Extract durable facts about the user."]
        for m in messages:
            lines.append(f"{m.get('role', 'user')}: {m.get('content', '')}")
        return "\n".join(lines)

    def _extract(self, prompt: str) -> List[str]:
        """Canned extractor: turns user turns into durable fact records.

        Deterministic by construction, so ``prompt_resend`` can be asserted in
        CI.  A real model would be non-deterministic -- that is exactly why the
        protocol puts it in a different layer (model_dependent) instead of
        pretending it is reproducible.

        Instruction-shaped turns are extracted too (labelled below); a store
        that rejects them at the door simply never reaches this point.
        """
        texts: List[str] = []
        for line in prompt.splitlines():
            if not line.lower().startswith("user:"):
                continue
            body = line.split(":", 1)[1].strip()
            if len(body) > 10:
                texts.append(body)
        # fidelity knob lets a caller simulate partial recall (e.g. 19/24)
        if self.extraction_fidelity < 1.0:
            keep = int(round(len(texts) * self.extraction_fidelity))
            texts = texts[:keep]
        return texts

    @staticmethod
    def _slot(text: str) -> Optional[str]:
        """Extract the attribute a fact is about ("office address").

        Deliberately crude: the reference store only needs to distinguish
        "same slot, new value" from "different slot".  A real store would use
        a typed schema, which is the point -- most stores use neither.
        """
        m = _SLOT_RE.match(text or "")
        return m.group("slot").strip().lower() if m else None

    def _retire_superseded(self, text: str, user_id: str) -> None:
        if self.defects["no_supersession"]:
            return
        slot = self._slot(text)
        if not slot:
            return
        for r in self._records:
            if (r.user_id == user_id and not r.superseded
                    and self._slot(r.text) == slot):
                r.superseded = True
                self.ledger.record("note", msg="supersede",
                                   memory_id=r.id, slot=slot)

    def _new_id(self) -> str:
        self._seq += 1
        return f"mem_{self._seq:04d}"

    # -- verbs ------------------------------------------------------------
    def add(self, messages: Sequence[Dict[str, str]], *,
            user_id: str = "u1") -> List[str]:
        self._call += 1
        msgs = list(messages)

        # What gets sent to the extractor decides what gets re-materialised.
        # A clean store extracts from THIS turn only.  A store with the resend
        # defect hands the whole session buffer over again, so the model
        # re-extracts history -- including anything already erased.
        for m in msgs:
            self._session.append(dict(m, user_id=user_id))
        prompt_msgs = (self._session[:] if self.defects["resend_after_erase"]
                       else msgs)
        prompt = self._build_extraction_prompt(prompt_msgs)
        self._prompts.append(prompt)
        texts = self._extract(prompt)

        ids: List[str] = []
        for t in texts:
            self._retire_superseded(t, user_id)
            trust = 1.0
            source = "extraction"
            if not self.defects["trust_all_writes"]:
                if "IGNORE ALL PREVIOUS" in t.upper() or \
                   "SYSTEM:" in t.upper():
                    source = "injected"
                    trust = 0.1          # quarantined, still stored
            rec = Record(id=self._new_id(), text=t, user_id=user_id,
                         created_at=self._clock(), updated_at=self._clock(),
                         source=source, trust=trust)
            self._records.append(rec)
            ids.append(rec.id)
            self.ledger.record("add", memory_id=rec.id, user_id=user_id,
                               source=source, trust=trust, call=self._call)
        self.ledger.record("observe", prompts=len(self._prompts),
                           records=len(self._records))
        return ids

    def retrieve(self, query: str, *, user_id: str = "u1",
                 limit: int = 5) -> List[Dict[str, Any]]:
        q = query.lower()
        q_terms = set(re.findall(r"[a-z0-9\-]+", q))
        scored = []
        now = self._clock()
        for r in self._records:
            if r.user_id != user_id:
                continue
            r_terms = set(re.findall(r"[a-z0-9\-]+", r.text.lower()))
            overlap = len(q_terms & r_terms)
            if self.defects["surface_only_recall"]:
                score = float(overlap)
                if overlap == 0:
                    continue
            else:
                score = float(overlap) * r.trust
                if score == 0 and r.trust >= 1.0:
                    continue
            if r.superseded and not self.defects["no_supersession"]:
                score *= 0.25          # retired fact: still reachable, ranked low
            age_days = max(0.0, (now - r.updated_at) / 86400.0)
            score *= 0.97 ** age_days          # gentle freshness decay
            scored.append((score, r))
        scored.sort(key=lambda x: (-x[0], x[1].id))
        out = [dict(r.to_dict(), score=round(s, 6)) for s, r in scored[:limit]]
        self.ledger.record("retrieve", query=query, hits=len(out),
                           ids=[o["id"] for o in out])
        return out

    def erase_scope(self, *, user_id: str = "u1") -> int:
        before = len(self._records)
        self._records = [r for r in self._records if r.user_id != user_id] \
            if not self.defects["scope_keeps_records"] else self._records
        # audit snapshot keeps the erased payload -- retention by design
        self._audit.append({
            "user_id": user_id, "texts": [r.text for r in self._records
                                          if r.user_id == user_id],
            "ts": self._clock(), "kind": "scope_erase",
        })
        if not self.defects["resend_after_erase"]:
            self._session = [m for m in self._session
                             if m.get("user_id", user_id) != user_id]
        self.ledger.record("erase_scope", user_id=user_id, removed=before - len(self._records))
        return before - len(self._records)

    def erase_record(self, *, memory_id: str) -> bool:
        for i, r in enumerate(self._records):
            if r.id == memory_id:
                self._audit.append({"user_id": r.user_id, "texts": [r.text],
                                    "ts": self._clock(), "kind": "record_erase",
                                    "memory_id": memory_id})
                self._records.pop(i)
                self.ledger.record("erase_record", memory_id=memory_id, ok=True)
                return True
        self.ledger.record("erase_record", memory_id=memory_id, ok=False)
        return False

    # -- observation ------------------------------------------------------
    def extraction_prompts(self) -> List[str]:
        return list(self._prompts)

    def raw_rows(self) -> List[Dict[str, Any]]:
        rows = [r.to_dict() for r in self._records]
        rows += [dict(a, kind="audit") for a in self._audit]
        return rows

    def checkpoint(self) -> None:
        self._prompts.clear()
        self.ledger.record("note", msg="checkpoint: prompt buffer cleared")

    def stats(self) -> Dict[str, Any]:
        return {
            "store": self.name, "version": self.version,
            "records": len(self._records),
            "session_messages": len(self._session),
            "prompts_sent": len(self._prompts),
            "audit_rows": len(self._audit),
            "defects": {k: v for k, v in self.defects.items() if v},
        }


class NullAdapter(MemoryAdapter):
    """For gates that need no store (e.g. spec/claim auditing)."""

    name = "null"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(NullLedger())

    def setup(self, *, reset: bool = True) -> None:
        return None

    def add(self, messages, *, user_id="u1"):
        return []

    def retrieve(self, query, *, user_id="u1", limit=5):
        return []

    def erase_scope(self, *, user_id="u1"):
        return 0

    def erase_record(self, *, memory_id):
        return False

    def extraction_prompts(self):
        return []

    def raw_rows(self):
        return []

    def checkpoint(self):
        return None

    def stats(self):
        return {"store": self.name}
