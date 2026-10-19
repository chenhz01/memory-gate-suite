# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Gate 3 -- staleness and supersession (D3).

Question: when a fact is updated, does memory know which version is current?

Most stores append.  Append-only memory without supersession is a slow-motion
correctness bug: the 2024 address keeps surfacing because it has more
tokens in common with the question than the 2026 address does.

Layers:
  supersession      deterministic  the newer fact must win over the older one
  contradiction     deterministic  two live incompatible facts = ambiguity
  age_visibility    observational  does the store expose age at all
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..adapters import MemoryAdapter
from ..protocol import (ABSTAIN, Claim, DETERMINISTIC, FAIL, OBSERVATIONAL,
                        PASS, Layer, Report, Subject)

GATE = "staleness"
GATE_VERSION = "1.0.0"

OLD = "my office address is 5 Old Mill Lane, Bristol"
NEW = "my office address is 88 Kingsway, Bristol"


def run(adapter: MemoryAdapter, *, user_id: str = "u1",
        query: str = "where is my office address",
        store_version: Optional[str] = None) -> Report:
    rep = Report(gate=GATE, gate_version=GATE_VERSION,
                 subject=Subject(kind="memory_store", name=adapter.name,
                                 version=store_version or adapter.version,
                                 adapter=type(adapter).__name__))

    L_sup = Layer("supersession", confidence=DETERMINISTIC,
                  note="newer fact must outrank the superseded one")
    L_con = Layer("contradiction", confidence=DETERMINISTIC,
                  note="two incompatible live facts must be flagged, not ranked")
    L_age = Layer("age_visibility", confidence=OBSERVATIONAL)

    adapter.setup(reset=True)
    adapter.add([{"role": "user", "content": OLD}], user_id=user_id)
    adapter.add([{"role": "user", "content": NEW}], user_id=user_id)

    hits = adapter.retrieve(query, user_id=user_id, limit=10)
    texts = [h.get("text", "") for h in hits]
    pos_old = next((i for i, t in enumerate(texts) if "Old Mill" in t), -1)
    pos_new = next((i for i, t in enumerate(texts) if "Kingsway" in t), -1)

    if pos_new < 0:
        L_sup.verdict = ABSTAIN
        L_sup.note += " | current fact never retrieved"
    else:
        L_sup.add("new_fact_retrieved", True, f"position={pos_new}")
        if pos_old < 0:
            L_sup.add("old_fact_superseded", True, "old fact absent")
        else:
            old_hit = hits[pos_old]
            # Primary judgement: was the old record explicitly retired?
            # Ranking order alone is not evidence -- two equally-overlapping
            # records are separated by float noise, not by a version rule.
            # Fall back to order only for adapters that expose no flag.
            if "superseded" in old_hit:
                L_sup.add("old_fact_marked_superseded",
                          old_hit.get("superseded") is True,
                          "record must carry superseded=True")
            else:
                L_sup.add("old_fact_not_outranking", pos_new < pos_old,
                          f"new@{pos_new} old@{pos_old} (no flag exposed)")
        if L_sup.failed:
            L_sup.samples.append({
                "old_pos": pos_old, "new_pos": pos_new, "query": query,
                "repro": "write fact A then fact A'; retrieve; newer must win",
            })
            L_sup.verdict = FAIL

    # Contradiction: both live with no version marker anywhere in the record.
    both_live = pos_old >= 0 and pos_new >= 0
    marked = any(
        h.get("superseded") is True
        or any(k in str(h.get("text", "")).lower()
               for k in ("superseded", "outdated", "replaced", "valid_from"))
        for h in hits
    )
    L_con.add("no_unmarked_contradiction", not both_live or marked,
              f"both_live={both_live} marked={marked}")
    if L_con.failed:
        L_con.samples.append({"old_pos": pos_old, "new_pos": pos_new,
                              "note": "both facts retrieved as equally valid"})
        L_con.verdict = FAIL

    # Age visibility: a store that never exposes timestamps cannot be audited
    # for staleness at all.  Informational only.
    has_ts = any("created_at" in h or "updated_at" in h for h in hits)
    L_age.add("timestamps_exposed", has_ts,
              "age is required to reason about staleness at all")
    L_age.verdict = PASS if has_ts else ABSTAIN

    rep.layers = [L_sup, L_con, L_age]
    rep.limits = [
        "Supersession is inferred from retrieval order, not from a declared "
        "validity interval; stores with intervals should report them in "
        "raw_rows().",
        "Age visibility is observational: absence of timestamps blocks "
        "audit but is not by itself a defect.",
    ]
    rep.claims = [
        Claim("The current fact outranks the superseded fact for the same "
              "query.", status="supported", layer="supersession"),
        Claim("Incompatible facts are never returned as equally valid.",
              status="supported", layer="contradiction"),
        Claim("Record age is exposed for audit.", status="untestable",
              layer="age_visibility",
              note="depends on adapter surface"),
    ]
    rep.ledger_digest = adapter.ledger.digest()
    rep.ledger_entries = len(adapter.ledger)
    return rep.seal()
