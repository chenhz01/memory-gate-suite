# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""MGP-1.0 test suite.

Organised around the five protocol rules, then the six gates, then the
submission path.  The goal is not coverage theatre: each test states a rule
that a consumer would rely on when they trust a verdict.
"""

import json
import unittest

from mgate import adapters, protocol
from mgate.adapters import ReferenceStore
from mgate.gates import claims as claims_gate
from mgate.gates import erasure, handoff, poisoning, retrieval, staleness
from mgate.ledger import GENESIS, Ledger, NullLedger
from mgate.protocol import (ABSTAIN, DETERMINISTIC, FAIL, INVALID,
                            MODEL_DEPENDENT, OBSERVATIONAL, PASS, Claim, Layer,
                            ProtocolError, Report, Subject, aggregate,
                            load_report)
from mgate.runner import run_suite, selftest
from mgate.submit import aml


def _rep(**kw):
    base = dict(gate="demo", gate_version="1.0.0",
                subject=Subject(name="s", version="1"))
    base.update(kw)
    return Report(**base)


class Rule1FourStates(unittest.TestCase):
    def test_invalid_outranks_fail(self):
        r = _rep()
        r.layers = [Layer("a", verdict=FAIL, samples=[{"x": 1}]),
                    Layer("b", verdict=INVALID)]
        self.assertEqual(r.verdict(), INVALID)

    def test_invalid_outranks_pass(self):
        r = _rep()
        r.layers = [Layer("a", verdict=PASS), Layer("b", verdict=INVALID)]
        self.assertEqual(r.verdict(), INVALID)

    def test_fail_outranks_abstain(self):
        r = _rep()
        r.layers = [Layer("a", verdict=FAIL, samples=[{"x": 1}]),
                    Layer("b", verdict=ABSTAIN)]
        self.assertEqual(r.verdict(), FAIL)

    def test_partial_abstain_does_not_sink_the_gate(self):
        r = _rep()
        r.layers = [Layer("a", verdict=PASS), Layer("b", verdict=ABSTAIN)]
        self.assertEqual(r.verdict(), PASS)

    def test_all_abstain_is_abstain(self):
        r = _rep()
        r.layers = [Layer("a", verdict=ABSTAIN), Layer("b", verdict=ABSTAIN)]
        self.assertEqual(r.verdict(), ABSTAIN)

    def test_no_layers_is_abstain(self):
        self.assertEqual(_rep().verdict(), ABSTAIN)

    def test_invalid_run_cannot_support_claims(self):
        r = _rep()
        r.layers = [Layer("a", verdict=INVALID)]
        r.claims = [Claim("all good", status="supported", layer="a")]
        with self.assertRaises(ProtocolError):
            r.seal()


class Rule3ClaimStrength(unittest.TestCase):
    def test_determinism_claim_on_model_layer_rejected(self):
        r = _rep()
        r.layers = [Layer("a", confidence=MODEL_DEPENDENT, verdict=PASS)]
        r.claims = [Claim("erasure always works", status="supported",
                          layer="a")]
        with self.assertRaises(ProtocolError) as ctx:
            r.seal()
        self.assertIn("may not outrun its evidence", str(ctx.exception))

    def test_determinism_claim_on_deterministic_layer_ok(self):
        r = _rep()
        r.layers = [Layer("a", confidence=DETERMINISTIC, verdict=PASS)]
        r.claims = [Claim("erasure always works", status="supported",
                          layer="a")]
        r.seal()

    def test_soft_claim_on_model_layer_ok(self):
        r = _rep()
        r.layers = [Layer("a", confidence=MODEL_DEPENDENT, verdict=PASS)]
        r.claims = [Claim("erasure often works", status="supported",
                          layer="a")]
        r.seal()

    def test_claim_must_bind_existing_layer(self):
        r = _rep()
        r.layers = [Layer("a", verdict=PASS)]
        r.claims = [Claim("x", status="supported", layer="ghost")]
        with self.assertRaises(ProtocolError):
            r.seal()

    def test_claim_must_bind_something(self):
        r = _rep()
        r.layers = [Layer("a", verdict=PASS)]
        r.claims = [Claim("x", status="supported", layer="")]
        with self.assertRaises(ProtocolError):
            r.seal()

    def test_weakest_confidence(self):
        r = _rep()
        r.layers = [Layer("a", confidence=DETERMINISTIC),
                    Layer("b", confidence=OBSERVATIONAL)]
        self.assertEqual(r.weakest_confidence(), OBSERVATIONAL)


class Rule4NoSampleNoFailure(unittest.TestCase):
    def test_fail_without_sample_rejected(self):
        r = _rep()
        r.layers = [Layer("a", verdict=FAIL)]
        with self.assertRaises(ProtocolError) as ctx:
            r.seal()
        self.assertIn("reproducible sample", str(ctx.exception))

    def test_fail_with_sample_ok(self):
        r = _rep()
        L = Layer("a", verdict=FAIL)
        L.add("check", False, "detail")
        L.samples.append({"repro": "step"})
        r.layers = [L]
        r.seal()

    def test_version_pin_required(self):
        r = Report(gate="demo", gate_version="1.0.0",
                   subject=Subject(name="s", version=""))
        r.layers = [Layer("a")]
        with self.assertRaises(ProtocolError) as ctx:
            r.seal()
        self.assertIn("rumour", str(ctx.exception))

    def test_duplicate_layers_rejected(self):
        r = _rep()
        r.layers = [Layer("a"), Layer("a")]
        with self.assertRaises(ProtocolError):
            r.seal()


class Rule5Certification(unittest.TestCase):
    def test_certified_requires_issuer_and_signature(self):
        r = _rep()
        r.layers = [Layer("a")]
        r.certified = True
        with self.assertRaises(ProtocolError) as ctx:
            r.seal()
        self.assertIn("certified=True", str(ctx.exception))

    def test_certified_with_signature_ok(self):
        r = _rep()
        r.layers = [Layer("a")]
        r.certified = True
        r.issued_by = "issuer"
        r.signature = "sig"
        r.seal()

    def test_self_run_is_not_certified(self):
        out = run_suite(gates=("handoff",))
        self.assertFalse(out["reports"][0]["certified"])


class Sealing(unittest.TestCase):
    def test_digest_is_stable(self):
        r = _rep()
        r.layers = [Layer("a")]
        self.assertEqual(r.digest(), r.digest())

    def test_digest_changes_with_content(self):
        r1 = _rep()
        r1.layers = [Layer("a")]
        r2 = _rep()
        r2.layers = [Layer("a", verdict=FAIL, samples=[{"x": 1}])]
        self.assertNotEqual(r1.digest(), r2.digest())

    def test_load_report_roundtrip(self):
        out = run_suite(gates=("handoff",))
        d = json.loads(json.dumps(out["reports"][0]))
        self.assertEqual(load_report(d)["digest"], d["digest"])

    def test_tampered_report_rejected(self):
        out = run_suite(gates=("handoff",))
        d = json.loads(json.dumps(out["reports"][0]))
        for layer in d["layers"]:
            if layer["verdict"] == "abstain":
                layer["verdict"] = "pass"
                break
        else:
            layer["verdict"] = "fail"
        with self.assertRaises(ProtocolError) as ctx:
            load_report(d)
        self.assertIn("digest mismatch", str(ctx.exception))

    def test_wrong_protocol_rejected(self):
        with self.assertRaises(ProtocolError):
            load_report({"protocol": "other/1.0", "gate": "x"})

    def test_aggregate_precedence(self):
        a = {"gate": "a", "verdict": PASS, "digest": "d1"}
        b = {"gate": "b", "verdict": FAIL, "digest": "d2"}
        self.assertEqual(aggregate([a, b])["verdict"], FAIL)
        c = {"gate": "c", "verdict": INVALID, "digest": "d3"}
        self.assertEqual(aggregate([a, b, c])["verdict"], INVALID)


class LedgerChain(unittest.TestCase):
    def test_empty_chain_verifies(self):
        self.assertTrue(Ledger().verify()["ok"])

    def test_chain_verifies(self):
        led = Ledger()
        led.record("setup", store="s")
        led.record("add", memory_id="m1")
        led.record("retrieve", hits=2)
        self.assertTrue(led.verify()["ok"])
        self.assertEqual(len(led), 3)

    def test_head_changes_per_entry(self):
        led = Ledger()
        h0 = led.head
        led.record("setup", store="s")
        self.assertNotEqual(led.head, h0)
        self.assertNotEqual(led.head, GENESIS)

    def test_tampering_breaks_chain(self):
        led = Ledger()
        led.record("setup", store="s")
        led.record("add", memory_id="m1")
        led.entries[0]["data"]["store"] = "other"
        res = led.verify()
        self.assertFalse(res["ok"])
        self.assertTrue(any("hash mismatch" in p for p in res["problems"]))

    def test_reordering_breaks_chain(self):
        led = Ledger()
        led.record("setup", store="s")
        led.record("add", memory_id="m1")
        led.entries[0], led.entries[1] = led.entries[1], led.entries[0]
        self.assertFalse(led.verify()["ok"])

    def test_truncation_detected_by_digest(self):
        led = Ledger()
        led.record("setup", store="s")
        led.record("add", memory_id="m1")
        full = led.digest()
        led.entries.pop()
        self.assertNotEqual(led.digest(), full)

    def test_jsonl_roundtrip(self):
        led = Ledger()
        for i in range(4):
            led.record("add", memory_id=f"m{i}")
        back = Ledger.from_jsonl(led.to_jsonl())
        self.assertEqual(len(back), 4)
        self.assertEqual(back.head, led.head)

    def test_unknown_op_rejected(self):
        with self.assertRaises(ValueError):
            Ledger().record("frobnicate", x=1)

    def test_null_ledger_reports_itself(self):
        nl = NullLedger()
        nl.record("setup")
        self.assertFalse(nl.verify()["ok"])
        self.assertEqual(nl.digest(), "")

    def test_gate_writes_ledger(self):
        store = ReferenceStore()
        rep = handoff.run(store)
        self.assertTrue(rep.ledger_digest.startswith("sha256:"))
        self.assertGreater(rep.ledger_entries, 0)
        self.assertTrue(store.ledger.verify()["ok"])


class GateErasure(unittest.TestCase):
    def test_clean_store_passes(self):
        rep = erasure.run(ReferenceStore())
        self.assertEqual(rep.verdict(), PASS)
        self.assertEqual(rep.layer("prompt_resend").verdict, PASS)
        self.assertEqual(rep.layer("re_extraction").verdict, PASS)

    def test_resend_defect_caught(self):
        rep = erasure.run(ReferenceStore(defects={"resend_after_erase": True}))
        self.assertEqual(rep.verdict(), FAIL)
        self.assertEqual(rep.layer("prompt_resend").verdict, FAIL)
        self.assertTrue(rep.layer("prompt_resend").samples)

    def test_scope_defect_caught(self):
        rep = erasure.run(ReferenceStore(defects={"scope_keeps_records": True}))
        self.assertEqual(rep.verdict(), FAIL)
        self.assertEqual(rep.layer("re_extraction").verdict, FAIL)

    def test_both_paths_are_exercised(self):
        rep = erasure.run(ReferenceStore())
        names = [c.name for c in rep.layer("prompt_resend").checks]
        self.assertTrue(any(n.startswith("scope:") for n in names))
        self.assertTrue(any(n.startswith("record:") for n in names))

    def test_residue_is_flag_not_failure(self):
        rep = erasure.run(ReferenceStore())
        self.assertEqual(rep.layer("storage_residue").verdict, PASS)
        self.assertEqual(rep.verdict(), PASS)

    def test_poisoned_fixture_invalidates(self):
        store = ReferenceStore(extraction_fidelity=0.0)
        rep = erasure.run(store)
        self.assertEqual(rep.verdict(), INVALID)
        self.assertEqual(rep.layer("re_extraction").verdict, ABSTAIN)


class GateRetrieval(unittest.TestCase):
    def test_clean_store_passes(self):
        rep = retrieval.run(ReferenceStore())
        self.assertEqual(rep.verdict(), PASS)

    def test_surface_only_caught(self):
        rep = retrieval.run(ReferenceStore(defects={"surface_only_recall": True}))
        self.assertEqual(rep.verdict(), FAIL)
        self.assertEqual(rep.layer("surface_substitution").verdict, FAIL)

    def test_savings_claim_without_percent_abstains(self):
        rep = retrieval.run(ReferenceStore(), savings_claim="we save tokens")
        self.assertEqual(rep.layer("claimed_savings").verdict, ABSTAIN)

    def test_savings_claim_with_percent_passes_form_check(self):
        rep = retrieval.run(ReferenceStore(), savings_claim="we save 70%")
        self.assertEqual(rep.layer("claimed_savings").verdict, PASS)

    def test_savings_claim_over_100_fails(self):
        rep = retrieval.run(ReferenceStore(), savings_claim="we save 140%")
        self.assertEqual(rep.layer("claimed_savings").verdict, FAIL)

    def test_parse_savings(self):
        self.assertEqual(retrieval.parse_savings_claim("cut 82.5%"), 82.5)
        self.assertIsNone(retrieval.parse_savings_claim("cut a lot"))


class GateStaleness(unittest.TestCase):
    def test_clean_store_passes(self):
        rep = staleness.run(ReferenceStore())
        self.assertEqual(rep.verdict(), PASS)

    def test_no_supersession_caught(self):
        rep = staleness.run(ReferenceStore(defects={"no_supersession": True}))
        self.assertEqual(rep.verdict(), FAIL)
        self.assertEqual(rep.layer("supersession").verdict, FAIL)

    def test_contradiction_detected(self):
        rep = staleness.run(ReferenceStore(defects={"no_supersession": True}))
        self.assertEqual(rep.layer("contradiction").verdict, FAIL)

    def test_age_visibility_reported(self):
        rep = staleness.run(ReferenceStore())
        self.assertEqual(rep.layer("age_visibility").verdict, PASS)


class GatePoisoning(unittest.TestCase):
    def test_clean_store_passes(self):
        rep = poisoning.run(ReferenceStore())
        self.assertEqual(rep.verdict(), PASS)

    def test_trust_all_caught(self):
        rep = poisoning.run(ReferenceStore(defects={"trust_all_writes": True}))
        self.assertEqual(rep.verdict(), FAIL)
        self.assertEqual(rep.layer("quarantine").verdict, FAIL)

    def test_persistence_is_informational(self):
        rep = poisoning.run(ReferenceStore())
        self.assertEqual(rep.layer("persistence").verdict, ABSTAIN)
        self.assertEqual(rep.verdict(), PASS)


class GateHandoff(unittest.TestCase):
    def test_clean_store_passes(self):
        rep = handoff.run(ReferenceStore())
        self.assertEqual(rep.verdict(), PASS)

    def test_all_four_facts_survive(self):
        rep = handoff.run(ReferenceStore())
        self.assertEqual(rep.layer("session_reset").verdict, PASS)

    def test_portability_abstains_without_import(self):
        rep = handoff.run(ReferenceStore())
        self.assertEqual(rep.layer("portability").verdict, ABSTAIN)

    def test_record_set_is_unchanged_across_boundary(self):
        store = ReferenceStore()
        rep = handoff.run(store)
        self.assertEqual(rep.layer("record_integrity").verdict, PASS)
        self.assertEqual(rep.layer("record_integrity").samples, [])


class GateClaims(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(claims_gate.classify("works 100% of the time"),
                         "determinism")
        self.assertEqual(claims_gate.classify("19/24 runs passed"),
                         "statistical")
        self.assertEqual(claims_gate.classify("GDPR compliant"), "compliance")
        self.assertEqual(claims_gate.classify("best-in-class memory"), "vague")

    def test_vague_claim_is_untestable(self):
        res = claims_gate.audit("enterprise-grade memory quality")
        self.assertEqual(res["status"], "untestable")

    def test_statistic_without_version_untestable(self):
        res = claims_gate.audit("19/24 runs passed")
        self.assertEqual(res["status"], "untestable")

    def test_determinism_without_evidence_untestable(self):
        res = claims_gate.audit("erasure always removes data")
        self.assertEqual(res["status"], "untestable")

    def test_compliance_without_report_untestable(self):
        res = claims_gate.audit("we are GDPR compliant on erasure")
        self.assertEqual(res["status"], "untestable")

    def test_refuted_by_failing_erasure_report(self):
        rep = erasure.run(ReferenceStore(defects={"resend_after_erase": True}))
        res = claims_gate.audit("erasure always removes data",
                                reports=[rep.to_dict()])
        self.assertEqual(res["status"], "refuted")

    def test_supported_by_clean_erasure_report(self):
        rep = erasure.run(ReferenceStore())
        res = claims_gate.audit("erasure always removes data",
                                reports=[rep.to_dict()])
        self.assertEqual(res["status"], "supported")

    def test_gate_abstains_without_claims(self):
        rep = claims_gate.run([])
        self.assertEqual(rep.verdict(), ABSTAIN)

    def test_clauses_are_unique_and_pinned(self):
        ids = [c["id"] for c in claims_gate.CLAUSES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 6)
        for c in claims_gate.CLAUSES:
            self.assertTrue(c["gate"])
            self.assertTrue(c["judgeable_by"])


class Submission(unittest.TestCase):
    def setUp(self):
        self.report = handoff.run(ReferenceStore()).to_dict()

    def test_observation_shape(self):
        obs = aml.to_observation(self.report)
        self.assertEqual(obs["kind"], aml.KIND)
        self.assertEqual(obs["gate"], "handoff")
        self.assertEqual(obs["evidence_digest"], self.report["digest"])
        self.assertIn("verifier", obs)
        self.assertEqual(obs["value"], 1.0)

    def test_observation_verifies(self):
        obs = aml.to_observation(self.report)
        self.assertTrue(aml.verify_observation(obs, self.report)["ok"])

    def test_observation_rejects_wrong_digest(self):
        obs = aml.to_observation(self.report)
        obs["evidence_digest"] = "sha256:" + "0" * 64
        res = aml.verify_observation(obs, self.report)
        self.assertFalse(res["ok"])
        self.assertTrue(res["problems"])

    def test_observation_rejects_tampered_report(self):
        bad = json.loads(json.dumps(self.report))
        bad["verdict"] = "fail"
        res = aml.verify_observation(aml.to_observation(self.report), bad)
        self.assertFalse(res["ok"])

    def test_batch_rollup(self):
        out = run_suite()
        batch = aml.batch(out["reports"])
        self.assertEqual(len(batch["observations"]), len(out["reports"]))
        self.assertEqual(batch["rollup"], "pass")
        self.assertEqual(sum(batch["counts"].values()), len(out["reports"]))


class Suite(unittest.TestCase):
    def test_clean_suite_passes_all_six(self):
        out = run_suite()
        self.assertEqual(out["aggregate"]["verdict"], PASS)
        self.assertEqual(len(out["reports"]), 6)

    def test_selftest_matrix(self):
        res = selftest()
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["matrix"]), 5)
        for row in res["matrix"]:
            self.assertTrue(row["caught"], row["defect"])

    def test_every_gate_is_sealed(self):
        out = run_suite()
        for r in out["reports"]:
            self.assertEqual(load_report(json.dumps(r))["digest"], r["digest"])

    def test_every_gate_pins_version(self):
        out = run_suite()
        for r in out["reports"]:
            self.assertTrue(r["gate_version"])
            self.assertTrue(r["subject"]["version"])

    def test_every_gate_declares_limits(self):
        out = run_suite()
        for r in out["reports"]:
            self.assertTrue(r["limits"], f"{r['gate']} must state its limits")

    def test_every_gate_binds_claims(self):
        out = run_suite()
        for r in out["reports"]:
            for c in r["claims"]:
                self.assertTrue(c["layer"] or c["status"] == "untestable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
