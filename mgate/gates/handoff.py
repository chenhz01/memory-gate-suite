# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Gate 5 -- lossless handoff (D8).

Question: when a new agent session (or a new vendor) takes over, is prior
memory still fully reachable?

Agent frameworks hand off constantly: session boundaries, sub-agents, model
switches, provider migrations.  Each handoff is a chance to silently drop
memory, and *silent* is the operative word -- the new session does not know
what it never received.

Layers:
  session_reset     deterministic  memory survives a prompt-buffer reset
  record_integrity  deterministic  record count and content unchanged
  portability       abstain-able   export -> import into a second store
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..adapters import MemoryAdapter
from ..protocol import (ABSTAIN, Claim, DETERMINISTIC, FAIL, Layer, PASS,
                        Report, Subject)

GATE = "handoff"
GATE_VERSION = "1.0.0"

FACTS = [
    "account manager is Dana Whitfield",
    "preferred language for invoices is German",
    "shipping tier is next-day air for all EU orders",
    "contract renewal date is 2027-03-01",
]


def run(adapter: MemoryAdapter, *, user_id: str = "u1",
        store_version: Optional[str] = None) -> Report:
    rep = Report(gate=GATE, gate_version=GATE_VERSION,
                 subject=Subject(kind="memory_store", name=adapter.name,
                                 version=store_version or adapter.version,
                                 adapter=type(adapter).__name__))

    L_sess = Layer("session_reset", confidence=DETERMINISTIC,
                   note="new session must not lose established memory")
    L_int = Layer("record_integrity", confidence=DETERMINISTIC)
    L_port = Layer("portability", confidence=DETERMINISTIC,
                   note="export -> rehydrate into a second store")

    adapter.setup(reset=True)
    for f in FACTS:
        adapter.add([{"role": "user", "content": f}], user_id=user_id)

    before_rows = [r for r in adapter.raw_rows() if r.get("kind") != "audit"]
    before_texts = sorted(str(r.get("text", "")) for r in before_rows)

    # Simulate the handoff: the buffer that a fresh session would start with
    # is emptied, while durable memory should be untouched.
    adapter.checkpoint()

    probes = {
        "dana": "who is my account manager",
        "german": "what language for invoices",
        "shipping": "what shipping tier do EU orders use",
        "renewal": "when does the contract renew",
    }
    missed: List[str] = []
    for key, q in probes.items():
        hits = adapter.retrieve(q, user_id=user_id, limit=10)
        blob = " ".join(h.get("text", "") for h in hits).lower()
        if key not in blob:
            missed.append(key)
    L_sess.add("all_facts_reachable_after_handoff", not missed,
               f"missing={missed}")
    if missed:
        L_sess.samples.append({"missing_probes": missed,
                               "repro": "write 4 facts, checkpoint, retrieve"})
        L_sess.verdict = FAIL
    else:
        L_sess.verdict = PASS

    after_rows = [r for r in adapter.raw_rows() if r.get("kind") != "audit"]
    after_texts = sorted(str(r.get("text", "")) for r in after_rows)
    L_int.add("record_count_preserved", len(after_rows) >= len(before_rows),
              f"{len(before_rows)} -> {len(after_rows)}")
    L_int.add("content_preserved", after_texts == before_texts,
              "byte-identical record set")
    if L_int.failed:
        L_int.samples.append({"before": before_texts, "after": after_texts})
        L_int.verdict = FAIL
    else:
        L_int.verdict = PASS

    # Portability: only if the adapter exposes an import path.
    exporter = getattr(adapter, "import_rows", None)
    if not callable(exporter):
        L_port.verdict = ABSTAIN
        L_port.add("adapter_exposes_import", False,
                   "no import_rows(); cannot test migration")
    else:
        target = type(adapter)(defects=getattr(adapter, "defects", None) or {})
        target.setup(reset=True)
        try:
            n = exporter(target, rows=before_rows)
            rt_rows = [r for r in target.raw_rows() if r.get("kind") != "audit"]
            L_port.add("import_completed", True, f"{n} rows")
            L_port.add("roundtrip_lossless",
                       len(rt_rows) >= len(before_rows),
                       f"{len(before_rows)} -> {len(rt_rows)}")
            if L_port.failed:
                L_port.samples.append({"before": len(before_rows),
                                       "after": len(rt_rows)})
                L_port.verdict = FAIL
            else:
                L_port.verdict = PASS
        except Exception as exc:                     # noqa: BLE001
            L_port.add("import_completed", False, repr(exc))
            L_port.samples.append({"error": repr(exc)})
            L_port.verdict = FAIL

    rep.layers = [L_sess, L_int, L_port]
    rep.limits = [
        "Handoff is simulated in-process; cross-process and cross-region "
        "migration are out of scope.",
        "Portability abstains when the adapter does not expose import_rows().",
    ]
    rep.claims = [
        Claim("A new session recovers every established fact without "
              "re-priming.", status=L_sess.claim_status(),
              layer="session_reset"),
        Claim("The record set is unchanged across a session boundary.",
              status=L_int.claim_status(), layer="record_integrity"),
    ]
    rep.ledger_digest = adapter.ledger.digest()
    rep.ledger_entries = len(adapter.ledger)
    return rep.seal()
