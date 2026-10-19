# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Gate 6 -- claim audit against quality clauses (D6).

This is the gate aimed at *other people's marketing*, which is where the
memory market is weakest.  It ships two artefacts:

1. ``CLAUSES`` -- six clauses a memory product can be held to.  Short enough
   to paste into a vendor review, checkable enough that "trust us" is not an
   answer.  Repos like AgentMemoryRepo can cite them by id.
2. ``audit`` -- take a vendor sentence, decide whether it is supported,
   refuted, or untestable *given the evidence available*.

The whole point is the third bucket.  A claim that cannot be tested is not a
soft pass; it is an unpriced liability, and the protocol says so out loud.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from ..protocol import (ABSTAIN, Claim, DETERMINISTIC, FAIL, PASS, Layer,
                        ProtocolError, Report, Subject, SUPPORTED, REFUTED,
                        UNTESTABLE)

GATE = "claims"
GATE_VERSION = "1.0.0"

CLAUSES: List[Dict[str, str]] = [
    {
        "id": "C1",
        "title": "Erasure is not undone by later writes",
        "text": "After a successful erasure call, the erased content does not "
                "re-enter an extraction prompt and does not reappear in "
                "retrievable memory. A store that only clears one erasure "
                "path does not satisfy this clause.",
        "gate": "erasure",
        "judgeable_by": "deterministic layer (prompt_resend) + counted layer",
    },
    {
        "id": "C2",
        "title": "Retrieval is not surface matching",
        "text": "A retrieved record that shares tokens with the query but "
                "inverts its fact must not outrank the correct record.",
        "gate": "retrieval",
        "judgeable_by": "deterministic substitution test",
    },
    {
        "id": "C3",
        "title": "Supersession is explicit",
        "text": "When a fact is updated, the current version outranks the "
                "superseded one, and two incompatible live facts are never "
                "returned as equally valid without a version marker.",
        "gate": "staleness",
        "judgeable_by": "deterministic ordering test",
    },
    {
        "id": "C4",
        "title": "The write path is a trust boundary",
        "text": "Instruction-shaped user or tool output is not stored at full "
                "trust and cannot steer a factual query.",
        "gate": "poisoning",
        "judgeable_by": "deterministic quarantine + influence test",
    },
    {
        "id": "C5",
        "title": "Handoff is lossless",
        "text": "Across a session boundary, every established fact remains "
                "reachable without re-priming, and the record set is unchanged.",
        "gate": "handoff",
        "judgeable_by": "deterministic reachability test",
    },
    {
        "id": "C6",
        "title": "Claims name their evidence layer",
        "text": "Any published quality statement states the store version, "
                "the layer it rests on, and whether that layer is "
                "deterministic, model-dependent, or observational. Numbers "
                "without a ledger are not evidence.",
        "gate": "claims",
        "judgeable_by": "this gate",
    },
]

_DETERMINISM = ("always", "never", "guaranteed", "guarantee", "deterministic",
                "100%", "cannot", "impossible")
_STATISTICAL = re.compile(r"(\d+\s*/\s*\d+)|(\d+(?:\.\d+)?\s*%)")
_COMPLIANCE = ("gdpr", "ccpa", "compliant", "compliance", "right to erasure",
               "right to be forgotten", "audited", "certified")
_VERSION = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
_VAGUE = ("high quality", "robust", "enterprise-grade", "best-in-class",
          "state of the art", "seamless", "world-class")


def classify(text: str) -> str:
    """Coarse claim family.  Cheap, explainable, good enough to triage."""
    low = (text or "").lower()
    if any(m in low for m in _COMPLIANCE):
        return "compliance"
    if "100%" in low or "100 %" in low:
        return "determinism"      # absolutes are stronger than statistics
    if _STATISTICAL.search(low):
        return "statistical"
    if any(m in low for m in _DETERMINISM):
        return "determinism"
    if any(m in low for m in _VAGUE):
        return "vague"
    return "descriptive"


def _evidence_for(family: str, reports: Sequence[Dict[str, Any]]
                  ) -> Optional[Dict[str, Any]]:
    """Return the strongest report that could back this claim family."""
    if not reports:
        return None
    if family == "compliance":
        want = "erasure"
    elif family == "determinism":
        want = None          # any report with a deterministic failing layer
    else:
        return None
    for r in reports:
        if want and r.get("gate") != want:
            continue
        layers = r.get("layers") or []
        if any(l.get("confidence") == DETERMINISTIC for l in layers):
            return r
    return None


def audit(text: str, *, reports: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Judge one vendor sentence.  Pure function, no I/O."""
    family = classify(text)
    reasons: List[str] = []
    versioned = bool(_VERSION.search(text or ""))
    ev = _evidence_for(family, reports)

    if family == "vague":
        status = UNTESTABLE
        reasons.append("no measurable predicate; nothing to falsify")
    elif family == "determinism":
        if ev is None:
            status = UNTESTABLE
            reasons.append("asserts determinism but no deterministic-layer "
                           "report was supplied")
        else:
            failed = [l["name"] for l in ev.get("layers", [])
                      if l.get("verdict") == "fail"
                      and l.get("confidence") == DETERMINISTIC]
            status = REFUTED if failed else SUPPORTED
            reasons.append(f"evidence gate={ev.get('gate')} "
                           f"failing_layers={failed}")
    elif family == "statistical":
        if not versioned:
            status = UNTESTABLE
            reasons.append("statistic without a store version pin")
        elif not reports:
            status = UNTESTABLE
            reasons.append("statistic without a run ledger to recompute from")
        else:
            status = SUPPORTED
            reasons.append("statistic accompanied by a version and a report")
    elif family == "compliance":
        if ev is None:
            status = UNTESTABLE
            reasons.append("compliance language without an erasure report; "
                           "a 200 from a delete endpoint is not compliance")
        else:
            failed = [l["name"] for l in ev.get("layers", [])
                      if l.get("verdict") == "fail"]
            status = REFUTED if failed else SUPPORTED
            reasons.append(f"erasure report failing_layers={failed}")
    else:
        status = SUPPORTED if versioned else UNTESTABLE
        reasons.append("descriptive claim; version pin required"
                       if not versioned else "descriptive claim, versioned")

    if not versioned:
        reasons.append("no version pin -> not attributable to a build")
    return {"text": text, "family": family, "status": status,
            "reasons": reasons}


def run(claim_texts: Sequence[str], *,
        reports: Sequence[Dict[str, Any]] = (),
        subject_name: str = "unnamed vendor",
        subject_version: str = "unstated") -> Report:
    rep = Report(gate=GATE, gate_version=GATE_VERSION,
                 subject=Subject(kind="vendor_claim", name=subject_name,
                                 version=subject_version, adapter="none"))
    L = Layer("claim_audit", confidence=DETERMINISTIC,
              note="each sentence judged against available reports")

    if not claim_texts:
        L.verdict = ABSTAIN
        L.add("claims_supplied", False, "nothing to audit")
    else:
        for i, t in enumerate(claim_texts):
            res = audit(t, reports=reports)
            ok = res["status"] == SUPPORTED
            L.add(f"claim_{i + 1}:{res['family']}", ok,
                  f"{res['status']} :: {'; '.join(res['reasons'])}")
            if not ok:
                L.samples.append({"claim": t, "family": res["family"],
                                  "status": res["status"],
                                  "reasons": res["reasons"]})
        # untestable is not a pass: an unbacked claim is a liability.  The
        # layer fails only when a claim is *refuted*; untestable claims are
        # recorded as samples and reported in the note, per MGP Rule 2.
        refuted = [s for s in L.samples if s["status"] == REFUTED]
        untestable = [s for s in L.samples if s["status"] == UNTESTABLE]
        L.verdict = FAIL if refuted else (ABSTAIN if untestable else PASS)
        L.note += (f" | supported={len(claim_texts) - len(L.samples)}"
                   f" untestable={len(untestable)} refuted={len(refuted)}")

    rep.layers = [L]
    rep.limits = [
        "Sentence-level audit: a claim that is true in aggregate but false "
        "for one build still trips this gate.",
        "Refuted requires a supplied report; without one, unsupported claims "
        "are reported as untestable rather than false.",
    ]
    if L.verdict != ABSTAIN:
        rep.claims = [
            Claim("Every audited sentence is attributable to a versioned "
                  "build and backed by a named evidence layer.",
                  status="untestable", layer="claim_audit",
                  note="see samples for per-sentence status"),
        ]
    rep.ledger_digest = ""
    rep.ledger_entries = 0
    return rep.seal()
