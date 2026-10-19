# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""MGP-1.0 protocol objects: the grammar of a memory-quality verdict.

Why a protocol instead of more scripts
-------------------------------------
Every memory vendor ships its own "we fixed it" claim.  There is no shared
grammar for saying *what* was measured, *how* confident anyone can be, and
*what would falsify it*.  Without that grammar, a deterministic pipeline bug
and a stochastic model behaviour get averaged into one misleading number --
which is exactly the failure mode behind mem0ai/mem0#7452 (19/24 vs 17/24 vs
11/24 across runs) and behind most "memory is compliant" marketing.

MGP-1.0 fixes five rules at protocol level:

  R1  Four-state verdict.  ``invalid`` outranks everything: if the fixture
      itself is poisoned (the thing you measure was never there), the run
      reports nothing rather than reporting a comfortable zero.
  R2  Abstention is first class.  ``abstain`` is a legitimate outcome when a
      property cannot be observed with the available adapter.  Guessing is
      forbidden; silence is honest.
  R3  Every layer declares its epistemic class: ``deterministic`` (stub model,
      byte-stable), ``model_dependent`` (real model, report counts, never
      assert), ``observational`` (DB/audit snapshot, point-in-time only).
      A claim can never be stronger than the weakest layer backing it.
  R4  Every failure carries at least one reproducible sample, and every run
      carries a ledger digest.  No sample, no failure.
  R5  ``certified`` is a gated flag, not a comment.  Self-run reports are
      ``certified=False``.  A report may only be certified by an authorised
      issuer with a signature -- the protocol is free, the certification is
      not (see COMMERCIAL.md).

Zero dependencies.  Python >= 3.9.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

PROTOCOL_ID = "mgp/1.0"
PROTOCOL_VERSION = "1.0.0"

# --- Rule 1: four states, invalid outranks all ------------------------------
PASS = "pass"
FAIL = "fail"
INVALID = "invalid"
ABSTAIN = "abstain"
VERDICTS = (PASS, FAIL, INVALID, ABSTAIN)

# --- Rule 3: epistemic classes, ordered weakest -> strongest ----------------
OBSERVATIONAL = "observational"
MODEL_DEPENDENT = "model_dependent"
DETERMINISTIC = "deterministic"
CONFIDENCES = (OBSERVATIONAL, MODEL_DEPENDENT, DETERMINISTIC)
_CONFIDENCE_RANK = {OBSERVATIONAL: 0, MODEL_DEPENDENT: 1, DETERMINISTIC: 2}

# --- Claim statuses ---------------------------------------------------------
SUPPORTED = "supported"
REFUTED = "refuted"
UNTESTABLE = "untestable"
CLAIM_STATUSES = (SUPPORTED, REFUTED, UNTESTABLE)

# A claim whose text asserts determinism ("always", "never", "deterministic",
# "guaranteed") must be backed by a deterministic layer.  This is the single
# most useful sentence in the protocol: it is what stops a 24-run sample from
# being published as a guarantee.
_DETERMINISM_MARKERS = (
    "always", "never", "deterministic", "guaranteed", "guarantee",
    "by construction", "cannot", "100%",
)


class ProtocolError(ValueError):
    """Raised when a report violates MGP-1.0."""


def derive_verdict(layers: Iterable[Any]) -> str:
    """Aggregate layer states with MGP precedence.

    invalid > fail > abstain > pass, except that a single abstaining layer
    does not abstain the whole gate: abstention is per-question, and one
    untestable side-quest must not silently erase five real results.
    """
    states = {l.verdict if hasattr(l, "verdict") else l.get("verdict")
              for l in layers}
    if not states:
        return ABSTAIN
    if INVALID in states:
        return INVALID
    if FAIL in states:
        return FAIL
    if states == {ABSTAIN}:
        return ABSTAIN
    return PASS


def content_fingerprint(report: Dict[str, Any]) -> str:
    """Clock-independent, order-independent identity of a verdict.

    ``digest`` covers the whole document including run_id and timestamps, so
    two identical runs never share one.  That is correct for tamper detection
    and useless for the only question a reader actually asks: *did this gate
    reach the same conclusion twice?*  This is that second identity -- same
    gates, same layer verdicts, same check outcomes, same claim statuses
    produce the same string, on any machine, on any day.
    """
    layers = []
    for l in report.get("layers", []):
        checks = sorted(
            ({"name": c.get("name"), "ok": bool(c.get("ok"))}
             for c in l.get("checks", [])),
            key=lambda x: str(x["name"]))
        layers.append({"name": l.get("name"), "verdict": l.get("verdict"),
                       "confidence": l.get("confidence"), "checks": checks})
    body = {
        "gate": report.get("gate"),
        "gate_version": report.get("gate_version"),
        "verdict": report.get("verdict"),
        "layers": layers,
        "claims": [{"status": c.get("status"), "layer": c.get("layer")}
                   for c in report.get("claims", [])],
    }
    blob = json.dumps(body, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))
    return "fp:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Check:
    """A single assertable unit.  Cheap, many per layer."""

    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class Layer:
    """One separately-judged evidence layer (Rule 3).

    Layers are deliberately NOT merged.  ``prompt_resend`` and
    ``re_extraction`` answer different questions and must never be averaged.
    """

    name: str
    confidence: str = DETERMINISTIC
    verdict: str = PASS
    checks: List[Check] = field(default_factory=list)
    samples: List[Dict[str, Any]] = field(default_factory=list)
    total: int = 0
    failed: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCES:
            raise ProtocolError(f"unknown confidence class: {self.confidence}")
        if self.verdict not in VERDICTS:
            raise ProtocolError(f"unknown layer verdict: {self.verdict}")

    def claim_status(self) -> str:
        """The strongest claim this layer's verdict can support.

        A report that says FAIL while claiming "supported" is not a style
        problem; it is a self-contradicting document that a reader will
        believe over the raw checks.  Binding this to one function makes the
        contradiction impossible to write.
        """
        if self.verdict == FAIL:
            return REFUTED
        if self.verdict in (ABSTAIN, INVALID, "invalid"):
            return UNTESTABLE
        return SUPPORTED

    def add(self, name: str, ok: bool, detail: str = "") -> Check:
        c = Check(name=name, ok=ok, detail=detail)
        self.checks.append(c)
        self.total += 1
        if not ok:
            self.failed += 1
        return c

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "confidence": self.confidence,
            "verdict": self.verdict,
            "total": self.total,
            "failed": self.failed,
            "checks": [c.to_dict() for c in self.checks],
            "samples": self.samples,
            "note": self.note,
        }


@dataclass
class Claim:
    """A human-readable assertion bound to the layer that backs it.

    Rule 3 in practice: a claim is only as strong as its weakest bound layer.
    """

    text: str
    status: str = SUPPORTED
    layer: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "status": self.status,
            "layer": self.layer,
            "note": self.note,
        }


@dataclass
class Subject:
    """What was measured.  Version pinning is mandatory -- a verdict without a
    version is a rumour."""

    kind: str = "memory_store"
    name: str = ""
    version: str = ""
    adapter: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
            "adapter": self.adapter,
            "extra": self.extra,
        }


@dataclass
class Report:
    gate: str
    gate_version: str
    subject: Subject = field(default_factory=Subject)
    layers: List[Layer] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)
    limits: List[str] = field(default_factory=list)
    ledger_digest: str = ""
    ledger_entries: int = 0
    certified: bool = False
    issued_by: str = ""
    signature: str = ""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    # -- derived ----------------------------------------------------------
    def verdict(self) -> str:
        """Rule 1 + 2 aggregation.

        invalid > fail > abstain > pass, with one important refinement: a
        single abstaining layer does NOT abstain the whole gate.  Abstention is
        per-question.  If ``portability`` cannot be tested but ``session_reset``
        and ``record_integrity`` both pass, the gate passes and the abstention
        stays visible on the layer.  The gate only abstains when *nothing* was
        judged -- otherwise one untestable side-quest would silently erase five
        real results.
        """
        return derive_verdict(self.layers)

    def weakest_confidence(self) -> str:
        if not self.layers:
            return OBSERVATIONAL
        return min((l.confidence for l in self.layers),
                   key=lambda c: _CONFIDENCE_RANK[c])

    def layer(self, name: str) -> Optional[Layer]:
        for l in self.layers:
            if l.name == name:
                return l
        return None

    # -- validation -------------------------------------------------------
    def validate(self) -> None:
        if not self.gate:
            raise ProtocolError("gate name is required")
        if not self.gate_version:
            raise ProtocolError("gate_version is required")
        if not self.subject.name or not self.subject.version:
            raise ProtocolError(
                "subject.name and subject.version are mandatory: a verdict "
                "without a version pin is a rumour, not evidence")
        names = [l.name for l in self.layers]
        if len(names) != len(set(names)):
            raise ProtocolError(f"duplicate layer names: {names}")

        for l in self.layers:
            # Rule 4: no sample, no failure.
            if l.verdict == FAIL and not l.samples:
                raise ProtocolError(
                    f"layer {l.name!r} fails without a reproducible sample")
            if l.verdict == FAIL and l.failed == 0 and l.total:
                raise ProtocolError(
                    f"layer {l.name!r} marked fail but no check failed")

        for c in self.claims:
            if c.status not in CLAIM_STATUSES:
                raise ProtocolError(f"unknown claim status: {c.status}")
            if c.status in (SUPPORTED, REFUTED) and not c.layer:
                raise ProtocolError(
                    f"claim {c.text!r} is {c.status} but binds no layer "
                    "(Rule 3: every judgement must name its evidence)")
            if c.layer and c.layer not in names:
                raise ProtocolError(
                    f"claim {c.text!r} binds unknown layer {c.layer!r}")
            # A report may not contradict its own evidence.
            if c.layer:
                lay = self.layer(c.layer)
                expected = lay.claim_status()
                if c.status != expected:
                    raise ProtocolError(
                        f"claim {c.text[:70]!r} is {c.status!r} but layer "
                        f"{c.layer!r} is {lay.verdict!r} "
                        f"(expected {expected!r})")
            if c.status == SUPPORTED and c.layer:
                l = self.layer(c.layer)
                low = c.text.lower()
                asserts_determinism = any(m in low for m in _DETERMINISM_MARKERS)
                if asserts_determinism and l.confidence != DETERMINISTIC:
                    raise ProtocolError(
                        f"claim {c.text!r} asserts determinism but layer "
                        f"{c.layer!r} is {l.confidence} "
                        "(Rule 3: a claim may not outrun its evidence)")

        # Rule 5: certified is gated.
        if self.certified and not (self.issued_by and self.signature):
            raise ProtocolError(
                "certified=True requires issued_by and signature "
                "(Rule 5, see COMMERCIAL.md)")

        # An invalid run may not carry supported claims: the fixture is
        # poisoned, so nothing measured on it counts.
        if self.verdict() == INVALID:
            bad = [c.text for c in self.claims if c.status == SUPPORTED]
            if bad:
                raise ProtocolError(
                    f"invalid run cannot support claims: {bad}")

    # -- sealing ----------------------------------------------------------
    def body(self) -> Dict[str, Any]:
        """Everything except the mutable tail.  Sorted keys => stable digest."""
        return {
            "protocol": PROTOCOL_ID,
            "gate": self.gate,
            "gate_version": self.gate_version,
            "run_id": self.run_id,
            "subject": self.subject.to_dict(),
            "layers": [l.to_dict() for l in self.layers],
            "claims": [c.to_dict() for c in self.claims],
            "limits": list(self.limits),
            "ledger": {"entries": self.ledger_entries,
                       "digest": self.ledger_digest},
            "extra": self.extra,
        }

    def digest(self) -> str:
        return _sha256(json.dumps(self.body(), sort_keys=True,
                                  ensure_ascii=False, separators=(",", ":")))

    def to_dict(self) -> Dict[str, Any]:
        self.finished_at = self.finished_at or _now()
        d = self.body()
        d.update({
            "verdict": self.verdict(),
            "weakest_confidence": self.weakest_confidence(),
            "certified": self.certified,
            "issued_by": self.issued_by,
            "signature": self.signature,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "digest": self.digest(),
        })
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def seal(self) -> "Report":
        """Validate + freeze.  Gates call this before returning."""
        self.finished_at = self.finished_at or _now()
        self.validate()
        return self


def load_report(payload: Any) -> Dict[str, Any]:
    """Parse and structurally verify an external report (used by the AML
    submitter and by anyone consuming our verdicts)."""
    d = json.loads(payload) if isinstance(payload, str) else payload
    if d.get("protocol") != PROTOCOL_ID:
        raise ProtocolError(f"not an {PROTOCOL_ID} report: {d.get('protocol')!r}")
    for k in ("gate", "gate_version", "verdict", "digest", "layers"):
        if k not in d:
            raise ProtocolError(f"report missing required field {k!r}")
    if d["verdict"] not in VERDICTS:
        raise ProtocolError(f"unknown verdict {d['verdict']!r}")
    derived = derive_verdict(d["layers"])
    if d["verdict"] != derived:
        raise ProtocolError(
            f"verdict {d['verdict']!r} does not follow from layers "
            f"(derived {derived!r}); the report was edited after sealing")
    # Recompute the digest so a tampered report is detectable.
    body = {k: d[k] for k in ("protocol", "gate", "gate_version", "run_id",
                              "subject", "layers", "claims", "limits",
                              "ledger", "extra") if k in d}
    expect = _sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":")))
    if d["digest"] != expect:
        raise ProtocolError("digest mismatch: report was modified after sealing")
    return d


def aggregate(reports: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Suite-level rollup.  Same precedence as a single report."""
    verdicts = [r.get("verdict", ABSTAIN) for r in reports]
    if INVALID in verdicts:
        v = INVALID
    elif FAIL in verdicts:
        v = FAIL
    elif not verdicts or all(x == ABSTAIN for x in verdicts):
        v = ABSTAIN
    else:
        v = PASS
    return {
        "protocol": PROTOCOL_ID,
        "gates": len(reports),
        "verdict": v,
        "by_gate": {r.get("gate", "?"): r.get("verdict", ABSTAIN)
                    for r in reports},
        "invalid": verdicts.count(INVALID),
        "fail": verdicts.count(FAIL),
        "abstain": verdicts.count(ABSTAIN),
        "pass": verdicts.count(PASS),
        "abstained_gates": [r.get("gate") for r in reports
                            if r.get("verdict") == ABSTAIN],
        "digests": [r.get("digest", "") for r in reports],
        "aggregate_digest": _sha256("|".join(r.get("digest", "")
                                             for r in reports)),
    }
