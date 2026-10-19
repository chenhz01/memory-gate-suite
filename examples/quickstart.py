# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Quickstart: judge a store, then audit a vendor sentence about it.

Run from the repository root:

    python examples/quickstart.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mgate.adapters import ReferenceStore
from mgate.gates import claims as claims_gate
from mgate.gates import erasure
from mgate.runner import run_suite
from mgate.submit import aml


def part1_full_suite() -> None:
    print("=" * 68)
    print("1. Full suite against a healthy reference store")
    print("=" * 68)
    out = run_suite()
    for r in out["reports"]:
        layers = ", ".join(f"{l['name']}={l['verdict']}" for l in r["layers"])
        print(f"  {r['gate']:<10} {r['verdict']:<8} {layers}")
    print(f"\n  suite verdict: {out['aggregate']['verdict'].upper()}")
    print(f"  digest:        {out['aggregate']['aggregate_digest'][:34]}...")


def part2_single_defect() -> None:
    print()
    print("=" * 68)
    print("2. Same suite, one planted defect (erasure resend)")
    print("=" * 68)
    store = ReferenceStore(defects={"resend_after_erase": True})
    rep = erasure.run(store)
    print(f"  verdict: {rep.verdict().upper()}")
    for layer in rep.layers:
        print(f"    {layer.name:<18} {layer.verdict:<6} "
              f"({layer.confidence}) {layer.failed}/{layer.total} failed")
    sample = rep.layer("prompt_resend").samples
    if sample:
        print(f"  sample: {json.dumps(sample[0], ensure_ascii=False)[:150]}")
    print("  -> a fix must clear BOTH erasure paths, not just delete_all")


def part3_claim_audit() -> None:
    print()
    print("=" * 68)
    print("3. Audit vendor sentences against a failing erasure report")
    print("=" * 68)
    bad = erasure.run(ReferenceStore(
        defects={"resend_after_erase": True})).to_dict()
    sentences = [
        "Our memory store is GDPR compliant with full right to erasure.",
        "Erasure always removes data from every path.",
        "Memory quality is enterprise-grade and best-in-class.",
        "We reduced context tokens by 82% in internal testing.",
    ]
    for s in sentences:
        res = claims_gate.audit(s, reports=[bad])
        print(f"  [{res['status']:<10}] {s}")
        for reason in res["reasons"][:2]:
            print(f"              - {reason}")


def part4_submission() -> None:
    print()
    print("=" * 68)
    print("4. Self-attesting observation (verifiable without trusting us)")
    print("=" * 68)
    rep = erasure.run(ReferenceStore()).to_dict()
    obs = aml.to_observation(rep)
    print(f"  kind:     {obs['kind']}")
    print(f"  gate:     {obs['gate']} v{obs['gate_version']}")
    print(f"  verdict:  {obs['verdict']}  value={obs['value']}")
    print(f"  evidence: {obs['evidence_digest'][:34]}...")
    print(f"  verifier: {obs['verifier']['match_rule']}")
    print(f"  self-verify: {aml.verify_observation(obs, rep)['ok']}")
    obs["evidence_digest"] = "sha256:" + "0" * 64
    print(f"  after tampering the digest: "
          f"{aml.verify_observation(obs, rep)['ok']}")


if __name__ == "__main__":
    part1_full_suite()
    part2_single_defect()
    part3_claim_audit()
    part4_submission()
    print()
    print("Done. Every number above came from an actual run in this process.")
