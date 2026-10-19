# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Append-only, hash-chained operation ledger (MGP-1.0 / D5).

Why a ledger is part of the protocol, not an afterthought
---------------------------------------------------------
Every memory-quality dispute we have seen reduces to an unfalsifiable
argument about what happened during the run.  "It passed on my machine",
"the fixture was different", "you must have called erase before add".

A hash-chained ledger removes that class of argument: each entry commits to
its predecessor, so any insertion, deletion, or reordering breaks the chain
and the report's digest no longer reproduces.  A verdict without a ledger is
an opinion; a verdict with a verifiable ledger is evidence.

Design: one JSON object per line (JSONL), RFC-8785-ish canonical form for the
hashed payload (sorted keys, no whitespace).  Zero dependencies.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

GENESIS = "sha256:" + "0" * 64

# Canonical operation vocabulary.  Gates may not invent verbs -- an open verb
# set makes cross-vendor comparison impossible.
OPS = (
    "setup",          # create store / load fixture
    "add",            # write memory
    "retrieve",       # read memory
    "erase_scope",    # delete-all style erasure
    "erase_record",   # id-style erasure
    "observe",        # read internal state (prompts sent, rows present)
    "assert",         # a check was evaluated
    "note",           # human or adapter annotation
)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _digest(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Ledger:
    """Hash-chained operation log."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.entries: List[Dict[str, Any]] = []
        self._head = GENESIS
        self._seq = 0

    # -- write ------------------------------------------------------------
    def record(self, op: str, **fields: Any) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if op not in OPS:
            raise ValueError(f"unknown ledger op {op!r}; allowed: {OPS}")
        self._seq += 1
        entry = {
            "seq": self._seq,
            "op": op,
            "ts": round(time.time(), 6),
            "prev": self._head,
            "data": fields,
        }
        entry["hash"] = _digest(_canon(entry))
        self._head = entry["hash"]
        self.entries.append(entry)
        return entry

    # -- read -------------------------------------------------------------
    @property
    def head(self) -> str:
        return self._head

    def __len__(self) -> int:
        return len(self.entries)

    def digest(self) -> str:
        """Digest of the whole chain: head + length, so truncation is visible."""
        return _digest(f"{self._head}|{len(self.entries)}")

    def to_jsonl(self) -> str:
        return "\n".join(_canon(e) for e in self.entries)

    def ops_count(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.entries:
            out[e["op"]] = out.get(e["op"], 0) + 1
        return out

    # -- verification -----------------------------------------------------
    def verify(self) -> Dict[str, Any]:
        """Re-walk the chain.  Returns a structured result, never raises, so a
        gate can report a broken ledger as a layer rather than crashing."""
        prev = GENESIS
        problems: List[str] = []
        for i, e in enumerate(self.entries):
            if e.get("seq") != i + 1:
                problems.append(f"entry {i}: bad seq {e.get('seq')}")
            if e.get("prev") != prev:
                problems.append(f"entry {i}: broken prev link")
            body = {k: v for k, v in e.items() if k != "hash"}
            if e.get("hash") != _digest(_canon(body)):
                problems.append(f"entry {i}: hash mismatch (tampered or reordered)")
            prev = e.get("hash", "")
        if prev != self._head:
            problems.append("head does not match last entry")
        return {
            "ok": not problems,
            "entries": len(self.entries),
            "head": self._head,
            "digest": self.digest(),
            "problems": problems,
        }

    @classmethod
    def from_jsonl(cls, text: str) -> "Ledger":
        led = cls()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            led.entries.append(e)
            led._head = e.get("hash", led._head)
            led._seq = max(led._seq, int(e.get("seq", 0)))
        return led


class NullLedger(Ledger):
    """Used when a consumer explicitly opts out (e.g. a micro-benchmark).
    The report then carries ``ledger_enabled=False`` in ``limits`` so nobody
    mistakes it for a sealed run."""

    def __init__(self) -> None:
        super().__init__(enabled=False)

    def digest(self) -> str:
        return ""

    def verify(self) -> Dict[str, Any]:
        return {"ok": False, "entries": 0, "head": GENESIS, "digest": "",
                "problems": ["ledger disabled"]}
