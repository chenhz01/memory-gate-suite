# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Suite runner + CLI.

Three entry points:

    python -m mgate list
    python -m mgate run --gate erasure --defects resend_after_erase
    python -m mgate selftest        # falsification matrix: does each gate
                                    # actually go red when it should?

``selftest`` is the point of the whole repository.  A gate that cannot be made
to fail is decoration.  Each defect mode in ``ReferenceStore`` is paired with
the gate that must catch it; selftest flips the defect and asserts the gate
turns red (and that the clean store is green).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from .adapters import ReferenceStore
from .gates import GATES, ORDER
from .protocol import ABSTAIN, FAIL, INVALID, PASS, aggregate, load_report
from .submit import aml

SUITE_VERSION = "1.0.0"


def run_suite(*, adapter: Optional[ReferenceStore] = None,
              gates: Sequence[str] = ORDER,
              claim_texts: Optional[Sequence[str]] = None,
              defects: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    store = adapter or ReferenceStore(defects=defects or {})
    reports: List[Dict[str, Any]] = []
    for name in gates:
        if name not in GATES:
            raise SystemExit(f"unknown gate {name!r}; known: {sorted(GATES)}")
        mod = GATES[name]["module"]
        if name == "claims":
            rep = mod.run(claim_texts or [], reports=reports,
                          subject_name=store.name,
                          subject_version=store.version).to_dict()
        else:
            rep = mod.run(store).to_dict()
        reports.append(rep)
    return {
        "suite_version": SUITE_VERSION,
        "store": store.stats(),
        "reports": reports,
        "aggregate": aggregate(reports),
        "observations": aml.batch(reports),
    }


# Each defect mode and the gate that must catch it.  If a defect exists that
# no gate catches, the suite has a hole and selftest fails.
FALSIFICATION_MATRIX = [
    ("resend_after_erase", "erasure"),
    ("scope_keeps_records", "erasure"),
    ("surface_only_recall", "retrieval"),
    ("no_supersession", "staleness"),
    ("trust_all_writes", "poisoning"),
]


def selftest() -> Dict[str, Any]:
    clean = run_suite(claim_texts=["the store always returns the newest fact"],
                      defects={})
    results: List[Dict[str, Any]] = []
    ok = clean["aggregate"]["verdict"] != FAIL

    for defect, gate in FALSIFICATION_MATRIX:
        out = run_suite(gates=(gate,), defects={defect: True})
        rep = out["reports"][0]
        caught = rep["verdict"] == FAIL
        results.append({
            "defect": defect, "gate": gate,
            "gate_verdict": rep["verdict"], "caught": caught,
            "digest": rep["digest"],
        })
        ok = ok and caught

    return {
        "ok": ok,
        "clean_suite_verdict": clean["aggregate"]["verdict"],
        "clean_by_gate": clean["aggregate"]["by_gate"],
        "matrix": results,
        "note": "clean suite must not fail; every planted defect must be "
                "caught by its paired gate",
    }


def _human(out: Dict[str, Any]) -> str:
    lines = []
    agg = out["aggregate"]
    lines.append(f"store: {out['store']['store']} "
                 f"v{out['store']['version']}  "
                 f"defects={out['store']['defects'] or 'none'}")
    lines.append(f"SUITE VERDICT: {agg['verdict'].upper()}  "
                 f"({agg['gates']} gates: {agg['pass']} pass, "
                 f"{agg['fail']} fail, {agg['abstain']} abstain, "
                 f"{agg['invalid']} invalid)")
    for r in out["reports"]:
        lines.append("")
        lines.append(f"  [{r['gate']}] {r['verdict'].upper()}  "
                     f"gate={r['gate_version']} weakest={r['weakest_confidence']}")
        for l in r["layers"]:
            lines.append(f"    - {l['name']:<20} {l['verdict']:<8} "
                         f"({l['confidence']}) "
                         f"{l['failed']}/{l['total']} failed")
        for s in r["limits"]:
            pass
    lines.append("")
    lines.append(f"aggregate digest: {agg['aggregate_digest'][:23]}...")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mgate",
                                 description="MGP-1.0 memory quality gates")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="list gates and the question each answers")

    p_run = sub.add_parser("run", help="run one or more gates")
    p_run.add_argument("--gate", action="append", default=[],
                       help="gate name; repeatable (default: all)")
    p_run.add_argument("--defects", default="",
                       help="comma-separated defect modes for the reference "
                            "store")
    p_run.add_argument("--claim", action="append", default=[],
                       help="vendor sentence to audit (claims gate)")
    p_run.add_argument("--adapter", default="reference",
                       help="store under test: reference (default) or mem0")
    p_run.add_argument("--json", action="store_true", help="emit JSON")
    p_run.add_argument("--out", default="", help="write JSON to this path")

    sub.add_parser("selftest", help="falsification matrix")

    p_ver = sub.add_parser("verify", help="verify a sealed report file")
    p_ver.add_argument("path")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        for name in ORDER:
            g = GATES[name]
            print(f"{name:<10} {g['layer_d']:<4} {g['question']}")
        return 0

    if args.cmd == "selftest":
        res = selftest()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res["ok"] else 1

    if args.cmd == "verify":
        payload = open(args.path, encoding="utf-8").read()
        try:
            doc = json.loads(payload)
        except Exception as exc:                     # noqa: BLE001
            print(f"INVALID: not JSON ({exc})")
            return 1
        # Accept either one sealed report or a suite file with reports[].
        targets = (doc.get("reports") if isinstance(doc, dict)
                   and "reports" in doc else [doc])
        bad = 0
        for item in targets:
            try:
                d = load_report(item)
                print(f"OK       gate={d['gate']:<10} verdict={d['verdict']:<8} "
                      f"digest={d['digest'][:23]}...")
            except Exception as exc:                 # noqa: BLE001
                bad += 1
                gate = item.get("gate", "?") if isinstance(item, dict) else "?"
                print(f"INVALID  gate={gate}: {exc}")
        print(f"\n{len(targets) - bad}/{len(targets)} reports verified")
        return 0 if bad == 0 else 1

    if args.cmd == "run":
        gates = tuple(args.gate) or ORDER
        defects = {}
        for d in [x.strip() for x in args.defects.split(",") if x.strip()]:
            defects[d] = True
        store = None
        if args.adapter and args.adapter != "reference":
            from .vendors import build as build_adapter
            store = build_adapter(args.adapter)
        out = run_suite(adapter=store, gates=gates, claim_texts=args.claim,
                        defects=defects)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2, ensure_ascii=False)
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(_human(out))
        return 0 if out["aggregate"]["verdict"] != FAIL else 2

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
