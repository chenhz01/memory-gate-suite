# Origin and design record

This file is the provenance anchor. It records **when** each idea appeared,
**what evidence** drove it, and **what was rejected**. Its purpose is to make
authorship checkable rather than asserted: every claim below corresponds to a
dated commit or a public thread that predates any copy of this work.

Repository history is the primary timestamp. This file exists so the reasoning
survives even if the history is squashed, mirrored, or re-uploaded elsewhere.

---

## 1. The triggering observations

All dates are 2026.

| Date | Observation | Source |
|---|---|---|
| 09-30 | DB audit of a memory store: erased content still present in raw rows, while the delete API returned success | internal audit, recorded in the erasure gate docstring |
| 10-15 | mem0 issue #7452: three evidence layers in one thread — stub repro, real-model counts (19/24, 17/24, 11/24), DB audit — argued as if they were one number | github.com/mem0ai/mem0/issues/7452 |
| 10-16 | Same defect class, different vendor: a retrieval claim that could not be separated from a token-overlap artefact | claude-mem issue #4138 |
| 10-19 | Realisation: the problem is not any one vendor. There is no grammar for a memory verdict. | this document |

The pattern across all three: **a deterministic property, a stochastic
behaviour, and a point-in-time snapshot were being compared as if they were
measured in the same units.** Every downstream argument was unresolvable for
that reason alone.

## 2. Design decisions and what they rejected

### 2.1 Ship one suite, not six scripts (2026-10-19)

Earlier artefacts existed as separate single-purpose scripts. They were
rejected as the published form: six unconnected scripts read as "one person
wrote some checks", while one protocol reads as "a category now has a
grammar". The unit of value is the grammar, not the checks.

### 2.2 Four states, with `invalid` at the top (2026-10-19)

Rejected: three-state (`pass`/`fail`/`skip`). The reason is adversarial, not
aesthetic. When a failing erasure test is inconvenient, the cheapest "fix" is
to make the setup stop planting the canary; a three-state system reports that
as `skip` or even `pass`. A distinct `invalid` state makes fixture poisoning
loud and unprofitable.

### 2.3 Abstention as a first-class outcome (2026-10-19)

Rejected: binary verdicts with a `notes` field for caveats. Caveats in prose
are discarded by the time a verdict reaches a slide. If a property cannot be
observed, that is a result and it must occupy the same syntactic slot as
`pass` and `fail`, or it will be quietly refiled as `pass`.

Refinement the same day: a single abstaining **layer** no longer abstains the
whole gate. The first implementation did, and a passing five-layer gate was
being reported as inconclusive because one optional layer (`portability`)
could not run. Abstention is per-question.

### 2.4 Claims must bind a layer, and may not outrun it (2026-10-19)

The rule that produced the most test failures during development, and the one
that matters most. A claim containing `always`/`never`/`guaranteed`/`100%` must
bind a `deterministic` layer. This is what prevents a 24-run sample from being
published as a guarantee — the specific failure observed in the triggering
thread.

Rejected alternative: a numeric "confidence score". Scores get averaged,
compared across gates, and ultimately quoted without their provenance. A
categorical class with an enforcement rule cannot be averaged into a lie.

### 2.5 Ledger inside the protocol, not beside it (2026-10-19)

Every dispute in the source threads reduced to an unfalsifiable argument about
what happened during the run. A hash chain removes that class of argument
entirely: insertion, deletion, or reordering breaks the digest. Verdict
without ledger = opinion; verdict with verifiable ledger = evidence.

### 2.6 Certification gated in code, not in a contract (2026-10-19)

Rejected: "open source everything, monetise consulting". That is the default
and it produces the current market — a dozen mutually incomparable green
lights. Instead: `certified: true` requires `issued_by` and `signature`, and
the reference implementation raises at seal time without them. The protocol
enforces the business boundary; no contract needed. Rationale and the full
open/withheld split: [COMMERCIAL.md](COMMERCIAL.md).

### 2.7 Falsification matrix as the headline test (2026-10-19)

Rejected: coverage percentage as the quality signal. The matrix plants five
real defect shapes and asserts each is caught by its paired gate, while the
clean store stays green. During development this immediately exposed four
genuine bugs that ordinary unit tests had missed — including a reference
extractor that silently discarded every non-canary fact, which had made three
gates report `abstain` on a healthy store.

A gate that cannot be made to fail is decoration. That sentence is the
repository's thesis.

## 3. What this work does not claim

- It does not claim any vendor is non-compliant. The reference gates were run
  against the reference store, not against a production product, in v1.0.
- It does not claim the six gates are complete. Each gate declares its blind
  spots in a mandatory `limits` array; those are not boilerplate.
- It does not claim priority over anyone else's quality framework. It claims
  only that these specific files, with these specific dates, introduced this
  grammar — which the commit history can be checked against.

## 4. Timeline summary

```
09-30  first internal erasure audit (raw-row residue)
10-15  issue thread with three incompatible evidence layers
10-16  same pattern at a second vendor
10-19  MGP-1.0 drafted; six gates; 79 tests / 119 assertions;
       falsification matrix 5/5
```

Authored by 正明 (Zhengming) for 善伦 / chenhz01.
