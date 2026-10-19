# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Self-attesting submitter (D7): turn a sealed MGP report into a portable
observation that a third party can verify without trusting us.

The problem this solves: every vendor dashboard says "green".  A green light
you cannot recompute is a logo, not a measurement.  D7 emits an observation
that carries (a) the run's digest, (b) the gate and version, (c) the evidence
class, and (d) a verifier recipe -- so a reviewer can re-run the gate and get
a byte-comparable digest, or detect that they did not.

Deliberately NOT a signature authority: signing is a commercial function
(see COMMERCIAL.md).  This module only produces *verifiable* payloads.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence

from ..protocol import PROTOCOL_ID, ProtocolError, load_report

SUBMIT_VERSION = "1.0.0"

# Observation kinds a receiver can bucket on without knowing our gates.
KIND = "memory_quality.gate_verdict"


def _iso(ts: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(ts if ts is not None else time.time()))


def to_observation(report: Dict[str, Any], *,
                   provider: str = "chenhz01",
                   subject_id: Optional[str] = None) -> Dict[str, Any]:
    """One report -> one observation.  Verifies the report first."""
    load_report(report)          # raises ProtocolError on tamper / bad shape

    verdict = report["verdict"]
    return {
        "kind": KIND,
        "submit_version": SUBMIT_VERSION,
        "protocol": PROTOCOL_ID,
        "provider": provider,
        "subject_id": subject_id or report["subject"].get("name", "unknown"),
        "gate": report["gate"],
        "gate_version": report["gate_version"],
        "verdict": verdict,
        "metric": f"{report['gate']}.verdict",
        "value": {"pass": 1.0, "abstain": 0.5, "fail": 0.0,
                  "invalid": 0.0}[verdict],
        "unit": "verdict_scale",
        "evidence_class": report.get("weakest_confidence", ""),
        "ledger": report.get("ledger", {}),
        "observed_at": report.get("finished_at") or _iso(),
        "evidence_digest": report["digest"],
        "verifier": {
            "action": "re-run the gate on the same subject version and "
                      "compare digests",
            "command": f"python -m mgate run --gate {report['gate']} "
                       f"--store <adapter> --json",
            "match_rule": "digest equality (barring adapter clock skew); "
                          "a differing digest means the run is not the same run",
            "protocol_doc": "PROTOCOL.md#verification",
        },
        "limitations": list(report.get("limits", [])),
    }


def batch(reports: Sequence[Dict[str, Any]], *, provider: str = "chenhz01",
          subject_id: Optional[str] = None) -> Dict[str, Any]:
    """Observation envelope for a whole suite run."""
    obs = [to_observation(r, provider=provider, subject_id=subject_id)
           for r in reports]
    verdicts = [o["verdict"] for o in obs]
    if "invalid" in verdicts:
        roll = "invalid"
    elif "fail" in verdicts:
        roll = "fail"
    elif not verdicts or all(v == "abstain" for v in verdicts):
        roll = "abstain"
    else:
        roll = "pass"
    return {
        "kind": "memory_quality.suite_verdict",
        "submit_version": SUBMIT_VERSION,
        "protocol": PROTOCOL_ID,
        "provider": provider,
        "subject_id": subject_id or "unknown",
        "observations": obs,
        "rollup": roll,
        "abstained_gates": [o["gate"] for o in obs
                            if o["verdict"] == "abstain"],
        "counts": {v: verdicts.count(v) for v in
                   ("pass", "fail", "abstain", "invalid")},
        "emitted_at": _iso(),
    }


def verify_observation(obs: Dict[str, Any],
                       report: Dict[str, Any]) -> Dict[str, Any]:
    """Receiver-side check: does this observation actually describe this
    report?  Returns a verdict instead of raising, because receivers should
    be able to show *why* a submission was rejected."""
    problems: List[str] = []
    try:
        load_report(report)
    except ProtocolError as exc:
        return {"ok": False, "problems": [f"report invalid: {exc}"]}
    if obs.get("evidence_digest") != report.get("digest"):
        problems.append("evidence_digest does not match report digest")
    if obs.get("gate") != report.get("gate"):
        problems.append("gate mismatch")
    if obs.get("verdict") != report.get("verdict"):
        problems.append("verdict mismatch")
    return {"ok": not problems, "problems": problems,
            "digest": report.get("digest")}
