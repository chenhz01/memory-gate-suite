# Memory Gate Protocol — MGP-1.0

**Status:** stable · **Version:** 1.0.0 · **Editor:** 正明 (Zhengming), for 善伦 / chenhz01
**Reference implementation:** `mgate` in this repository
**Specification licence:** CC BY 4.0 — implementations are free, attribution of
the specification is not optional (see [§8](#8-licensing-and-attribution))

---

## 0. Why this document exists

Every memory product says it works. Almost none says **what was measured**,
**how confident a reader may be**, or **what result would prove it wrong**.

The result is a market where three incompatible claims circulate as if they
were the same quantity:

| Claim | Actually means |
|---|---|
| "erasure is fixed" | a DELETE endpoint returned 200 |
| "19/24 runs passed" | one sampled model behaviour, one afternoon |
| "60% token savings" | nobody recomputed it |

MGP-1.0 replaces that with a small grammar. A verdict produced under this
protocol is a machine-checkable object: it names the store version, the
epistemic class of the evidence, the exact checks that failed, a reproducible
sample for each failure, and a hash-chained ledger digest that makes the run
tamper-evident.

The grammar is deliberately boring. The value is not in the words; it is in
the fact that two parties can now disagree **about a specific layer** instead
of about vibes.

---

## 1. Scope

MGP-1.0 covers verdicts about **memory quality** in agent systems: erasure,
retrieval influence, staleness, write-path trust, handoff losslessness, and
the auditability of published claims.

Out of scope: performance benchmarking, cost benchmarking, model quality,
prompt design, and anything that requires reading a vendor's private source.

---

## 2. Normative rules

The five rules below are the protocol. An implementation that violates any of
them is not MGP-1.0, regardless of what it calls itself.

### R1 — Four-state verdict, `invalid` outranks everything

A verdict is exactly one of `pass`, `fail`, `abstain`, `invalid`.

`invalid` means the *fixture* was poisoned: the property being measured was
never present, so the run measured nothing. An invalid run MUST NOT be
reported as a pass, a fail, or a clean zero. This rule exists because the most
common way to "fix" a failing erasure test is to make the setup silently stop
planting the canary.

Precedence for aggregation: `invalid` > `fail` > `abstain` > `pass`.

### R2 — Abstention is first class

`abstain` is a legitimate result when a property cannot be observed through the
available adapter. Implementations MUST NOT guess, and MUST NOT translate "I
could not test this" into `pass`.

A single abstaining **layer** does not abstain the whole gate: abstention is
per-question. If `portability` cannot be tested but `session_reset` and
`record_integrity` both pass, the gate passes and the abstention remains
visible on that layer. A gate abstains only when *no* layer was judged.

### R3 — Every layer declares its epistemic class

Each layer MUST carry exactly one of:

| Class | Meaning | May a claim rest on it? |
|---|---|---|
| `deterministic` | stub model, byte-stable, CI-assertable | yes, including absolute language |
| `model_dependent` | real model, run-to-run variance | counts only, never absolutes |
| `observational` | point-in-time snapshot (DB rows, audit log) | as a flag, never as pass/fail |

A claim may not be stronger than the weakest layer bound to it. Concretely: a
claim containing `always`, `never`, `deterministic`, `guaranteed`, `cannot`, or
`100%` MUST bind a `deterministic` layer. The reference implementation rejects
such a report at seal time.

This is the rule that stops a 24-run sample from being published as a
guarantee. It is the single most useful sentence in this document.

**R3 is executed, not recommended.** Published guidance already says a
capability claim should carry experimental evidence; guidance is a document,
and a document cannot stop a README from saying "always". Here the seal step
raises `ProtocolError` and emits no file, so the sentence has nowhere to live:

```
$ python examples/refuse_a_claim.py
REFUSED at seal time -> claim 'Erased text always stays erased.' asserts
determinism but layer 're_extraction' is model_dependent
(Rule 3: a claim may not outrun its evidence)
```

An implementation that copies the gates but skips this step inherits the
paperwork without the enforcement.

### R4 — No sample, no failure

A layer may only be marked `fail` if it carries at least one reproducible
sample (the concrete input, the observed output, and the steps to re-create
it). A failure without a sample is a rumour.

Every run MUST also carry a ledger: an append-only, hash-chained record of the
operations performed, whose digest is bound into the report. Any insertion,
deletion, or reordering of ledger entries breaks the chain and the report no
longer reproduces.

### R5 — `certified` is a gated flag, not a comment

Self-run reports carry `certified: false`. A report may carry
`certified: true` only when it also carries `issued_by` and `signature` from an
authorised issuer.

The protocol is free. The certification is not. This is deliberate: see
[COMMERCIAL.md](COMMERCIAL.md) for the boundary and the reasoning.

---

## 3. Report structure

Serialised as JSON. Field names are normative.

```json
{
  "protocol": "mgp/1.0",
  "gate": "erasure",
  "gate_version": "1.0.0",
  "run_id": "f4ce76822435435e",
  "subject": {
    "kind": "memory_store",
    "name": "mem0",
    "version": "2.2.1",
    "adapter": "Mem0Shim",
    "extra": {}
  },
  "layers": [
    {
      "name": "prompt_resend",
      "confidence": "deterministic",
      "verdict": "fail",
      "total": 2,
      "failed": 1,
      "checks": [{"name": "scope:no_resend", "ok": true, "detail": ""}],
      "samples": [{"path": "record", "stage": "prompt_resend", "repro": "..."}],
      "note": ""
    }
  ],
  "claims": [
    {"text": "...", "status": "supported", "layer": "prompt_resend", "note": ""}
  ],
  "limits": ["..."],
  "ledger": {"entries": 42, "digest": "sha256:..."},
  "verdict": "fail",
  "weakest_confidence": "deterministic",
  "certified": false,
  "issued_by": "",
  "signature": "",
  "started_at": "2026-10-19T10:00:00Z",
  "finished_at": "2026-10-19T10:00:03Z",
  "digest": "sha256:..."
}
```

Required: `protocol`, `gate`, `gate_version`, `subject.name`,
`subject.version`, `layers`, `verdict`, `digest`, `limits`.

**`subject.version` is mandatory.** A verdict without a version pin is a
rumour about a moving target, not evidence about a build.

`limits` is mandatory and must be non-empty. A gate that cannot state its own
blind spots is not a gate.

---

## 4. Verdict derivation

`verdict` is a pure function of the layer states:

```
if any layer is invalid   -> invalid
elif any layer is fail    -> fail
elif all layers abstain   -> abstain
else                      -> pass
```

Because the digest does not cover the derived field, a verifier MUST recompute
`verdict` from `layers` and reject the report on mismatch. Editing `verdict`
alone is the cheapest possible forgery; the protocol closes it explicitly.

---

## 5. Verification

A third party verifies a report in three steps, none of which requires
trusting the submitter:

1. **Structure and integrity** — recompute the digest from the body fields;
   recompute `verdict` from `layers`. Both must match.
2. **Ledger integrity** — re-walk the hash chain; confirm the head and length
   match the digest bound into the report.
3. **Reproduction** — re-run the gate against the same `subject.version` and
   compare. Digest equality means it is the same run modulo adapter clock
   skew; inequality means it is not, and the submitter owes an explanation.

The self-attesting submitter (`mgate.submit.aml`) emits observations that carry
the digest plus this recipe, so a reviewer can show *why* a submission was
rejected rather than just rejecting it.

---

## 6. Reference gates

| Gate | Question | Layers |
|---|---|---|
| `erasure` | Can erased text reach a model again, or return as memory? | `prompt_resend` (det), `re_extraction` (model), `storage_residue` (obs) |
| `retrieval` | Is a hit contributing, or merely sharing tokens? | `surface_substitution` (det), `claimed_savings` (obs), `spec_drift` (det) |
| `staleness` | Does memory know which fact version is current? | `supersession` (det), `contradiction` (det), `age_visibility` (obs) |
| `poisoning` | Is the write path a trust boundary? | `quarantine` (det), `influence` (det), `persistence` (obs) |
| `handoff` | Does memory survive a session or vendor handoff? | `session_reset` (det), `record_integrity` (det), `portability` (det/abstain) |
| `claims` | Does a published claim name its evidence layer? | `claim_audit` (det) |

`det` = deterministic, `model` = model-dependent, `obs` = observational.

---

## 7. Extending the protocol

A new gate is MGP-1.0-conforming if it:

1. emits a report with every required field, including non-empty `limits`;
2. declares a confidence class per layer, never mixing classes within a layer;
3. implements `abstain` for every unobservable path, and `invalid` for every
   poisoned-fixture path;
4. attaches a reproducible sample to every failure;
5. pins `gate_version` and refuses to emit a report whose version drifts from
   the one it asserts.

Vendors are explicitly invited to publish third-party gates. The grammar is
the point; the reference implementation is only one instantiation of it.

---

## 8. Licensing and attribution

Two licences, on purpose:

- **This specification** is licensed **CC BY 4.0**. You may implement it
  freely, including commercially and in closed source. If you describe your
  implementation as MGP-1.0-conforming, you must attribute the specification
  (a link to this repository and the string `MGP-1.0` is sufficient).
- **The reference implementation** (`mgate` code) is **Apache-2.0**. See
  [LICENSE](LICENSE) and [NOTICE](NOTICE).

The split is not decoration. Apache-2.0 on code maximises adoption; CC BY on
the spec means the name of the protocol stays attached to the thing that made
it mean something. Anyone may build a conforming gate. Nobody may quietly
relabel this grammar as their own.

How this protocol came to exist, and from which public threads, is recorded in
[ORIGIN.md](ORIGIN.md).
