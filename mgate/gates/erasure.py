# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Gate 1 -- erasure re-materialisation (D1).

Question: after an erasure call returns success, can the erased text still
reach a model, and can it come back as memory?

Three layers, judged separately, never averaged:

  prompt_resend    deterministic   erased text appears in an extraction prompt
  re_extraction    model_dependent erased text reappears in retrievable memory
  storage_residue  observational   erased text still in raw/audit rows

Both erasure paths are exercised (scope + record).  A fix that only covers
``delete_all`` does not pass.

Origin: mem0ai/mem0#7452 -- three independent evidence sets (stub repro
ac12644, real-model counts 19/24 / 17/24 / 11/24 by csshafiqahmed, DB audit
chenhz01 2026-09-30) that were being argued about as if they were one number.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..adapters import CANARY_RE, MemoryAdapter
from ..protocol import (ABSTAIN, Claim, DETERMINISTIC, FAIL, INVALID, Layer,
                        MODEL_DEPENDENT, OBSERVATIONAL, PASS, Report, Subject)

GATE = "erasure"
GATE_VERSION = "1.0.0"

DEFAULT_CANARY = "CANARY-7F3A9B"
FILLER = "please remember my invoice address is 12 Harbour Road"


def _hits(prompts: Sequence[str], canary: str) -> List[int]:
    return [i for i, p in enumerate(prompts) if canary in p]


def _path_report(adapter: MemoryAdapter, *, path: str, canary: str,
                 user_id: str) -> Dict[str, Any]:
    """Run one erasure path and collect raw observations.

    Returns a dict of observations; judging happens in ``run`` so that both
    paths can be rolled into the same layer.
    """
    obs: Dict[str, Any] = {"path": path, "usable": False, "notes": []}
    adapter.setup(reset=True)

    ids = adapter.add([
        {"role": "user", "content": f"my access code is {canary}"},
        {"role": "assistant", "content": "noted"},
    ], user_id=user_id)
    adapter.add([{"role": "user", "content": FILLER}], user_id=user_id)

    pre = adapter.retrieve(canary, user_id=user_id, limit=10)
    obs["retrievable_before"] = any(canary in h.get("text", "") for h in pre)
    if not obs["retrievable_before"]:
        obs["notes"].append(
            "canary never landed in retrievable memory -> setup_failed")
        return obs

    adapter.checkpoint()

    if path == "scope":
        adapter.erase_scope(user_id=user_id)
    else:
        target = ""
        for h in pre:
            if canary in h.get("text", ""):
                target = h.get("id", "")
                break
        if not target:
            obs["notes"].append("no record id for canary -> setup_failed")
            return obs
        adapter.erase_record(memory_id=target)
        obs["erased_id"] = target

    # A benign write after erasure is the realistic trigger: most stores only
    # rebuild the extraction prompt when add() is called again.
    adapter.add([{"role": "user", "content": "anything else you need?"}],
                user_id=user_id)

    prompts = adapter.extraction_prompts()
    obs["resend_hits"] = _hits(prompts, canary)
    obs["prompts_after_erase"] = len(prompts)

    post = adapter.retrieve(canary, user_id=user_id, limit=10)
    obs["retrievable_after"] = [h.get("text", "") for h in post
                                if canary in h.get("text", "")]

    rows = adapter.raw_rows()
    obs["residue_rows"] = [r for r in rows if canary in str(r.get("text", ""))]
    obs["usable"] = True
    return obs


def run(adapter: MemoryAdapter, *, canary: str = DEFAULT_CANARY,
        user_id: str = "u1",
        paths: Sequence[str] = ("scope", "record"),
        store_version: Optional[str] = None) -> Report:
    """Execute the erasure gate and return a sealed MGP report."""

    rep = Report(gate=GATE, gate_version=GATE_VERSION,
                 subject=Subject(kind="memory_store", name=adapter.name,
                                 version=store_version or adapter.version,
                                 adapter=type(adapter).__name__))

    L_resend = Layer(
        "prompt_resend", confidence=DETERMINISTIC,
        note="stub-class determinism: erased text must never re-enter a prompt")
    L_reext = Layer(
        "re_extraction", confidence=MODEL_DEPENDENT,
        note="counts only; model behaviour is not a CI assertion")
    L_resid = Layer(
        "storage_residue", confidence=OBSERVATIONAL,
        note="audit retention is legitimate; reported, never verdict-level")

    usable = 0
    for path in paths:
        obs = _path_report(adapter, path=path, canary=canary, user_id=user_id)
        if not obs["usable"]:
            L_resend.verdict = INVALID
            L_resend.add(f"{path}:setup", False, "; ".join(obs["notes"]))
            L_resend.samples.append({"path": path, "stage": "setup",
                                     "notes": obs["notes"]})
            continue
        usable += 1

        resent = bool(obs["resend_hits"])
        L_resend.add(f"{path}:no_resend", not resent,
                     f"hits at prompt indexes {obs['resend_hits']}")
        if resent:
            L_resend.samples.append({
                "path": path, "stage": "prompt_resend",
                "prompt_indexes": obs["resend_hits"],
                "repro": "add benign turn after erase, then read "
                         "adapter.extraction_prompts()",
            })

        came_back = obs["retrievable_after"]
        L_reext.add(f"{path}:no_reextraction", not came_back,
                    f"{len(came_back)} record(s) recovered the canary")
        if came_back:
            L_reext.samples.append({"path": path, "stage": "re_extraction",
                                    "texts": came_back[:3]})

        residue = obs["residue_rows"]
        L_resid.add(f"{path}:residue_reported", True,
                    f"{len(residue)} row(s) retain the canary (audit window)")
        if residue:
            L_resid.samples.append({"path": path, "stage": "storage_residue",
                                    "rows": [{"id": r.get("id"),
                                              "kind": r.get("kind", "record")}
                                             for r in residue[:3]]})

    if usable == 0:
        L_reext.verdict = ABSTAIN
        L_resid.verdict = ABSTAIN
    else:
        if L_resend.failed:
            L_resend.verdict = FAIL
        if L_reext.failed:
            L_reext.verdict = FAIL
        # residue is a flag: pass, never fail
        L_resid.verdict = PASS

    rep.layers = [L_resend, L_reext, L_resid]
    rep.limits = [
        "Gate exercises the adapter's public verbs only; an adapter that "
        "hides prompts will look clean.",
        "re_extraction counts are model-dependent and must not be quoted as "
        "a guarantee.",
        "storage_residue is informational: retained audit rows may be "
        "required for compliance.",
    ]

    invalid = L_resend.verdict == INVALID
    if invalid:
        rep.limits.append(
            "Fixture was poisoned (canary never retrievable before erasure); "
            "no claim can be supported by this run.")
    rep.claims = [
        Claim("Erased text does not re-enter an extraction prompt after a "
              "scope or record erasure (deterministic under the reference "
              "adapter).",
              status="untestable" if invalid else "supported",
              layer="prompt_resend"),
        Claim("Erased text does not reappear in retrievable memory.",
              status="untestable" if invalid else "supported",
              layer="re_extraction"),
        Claim("Erased text is absent from raw storage rows.",
              status="untestable", layer="storage_residue",
              note="retention windows are a policy choice, not a defect"),
    ]

    rep.ledger_digest = adapter.ledger.digest()
    rep.ledger_entries = len(adapter.ledger)
    return rep.seal()
