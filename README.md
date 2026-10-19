# memory-gate-suite — MGP-1.0

**A verdict a third party can re-run is evidence. A green light only its author can see is a logo.**

Six gates that judge whether an AI memory store actually behaves — erasure,
retrieval influence, staleness, write-path trust, handoff losslessness, and
the auditability of the claims vendors publish. Every verdict names the store
version, the epistemic class of its evidence, a reproducible sample for each
failure, and a hash-chained ledger digest.

`mgate` is the reference implementation of [MGP-1.0](PROTOCOL.md). Zero
dependencies, Python ≥ 3.9, ~2.4k lines.

First run against a store we did not write: **[VENDOR-TEST.md](VENDOR-TEST.md)**
— mem0 2.2.1, four of six gates fail, with reproduction steps for each.

---

## What this is not (read this before judging it)

The agent-memory evaluation space is **crowded** — DolphinBench, STATE-Bench,
MemEval, Veracium, governed-memory all predate or parallel this work, and
MemEval's adapter architecture is close enough to ours that saying otherwise
would be dishonest. See [RELATED-WORK.md](RELATED-WORK.md) for a line-by-line
comparison.

This repository is **not a benchmark**. Benchmarks rank memory systems —
"which one is better". MGP-1.0 certifies a **specific build against specific
falsifiable properties** — "did this build pass this line, and who signs it".

The difference is not marketing. A benchmark outputs a score; a score cannot
express *"the fixture was poisoned, this run counts for nothing"*. MGP's
`invalid` state can. That is the whole bet, stated plainly.

---

## The one rule a vendor cannot self-issue

Published guidance on agent memory already says the right thing: *a capability
claim should carry experimental evidence*. That guidance is a document. A
document cannot stop a README from saying "erasure always works".

MGP-1.0 turns that sentence into a build failure. Claims carry an evidence
class; layers carry a confidence class; at seal time a claim that asserts
absoluteness (`always`, `never`, `100%`, `guaranteed`) while resting on a
`model_dependent` layer raises `ProtocolError` — and **no report file is
produced**:

```
$ python examples/refuse_a_claim.py
1) absolute claim on a model-dependent layer
   REFUSED at seal time -> claim 'Erased text always stays erased.' asserts
   determinism but layer 're_extraction' is model_dependent
   (Rule 3: a claim may not outrun its evidence)
   no report file exists; the sentence cannot be published as a sealed verdict
```

Anyone can copy the gates. Copying this means giving up the sentence you
wanted to publish — which is exactly why it is worth something.

Rule 3 is not "don't claim". It is: *claim at the resolution your evidence
actually has*.

---

## The failure this was built for

A store accepts a delete, returns 200, and the memory is still there on the
next write. Concretely, from mem0ai/mem0#7452 — three people measured the same
defect and got three incompatible numbers:

| Method | Result | What it actually showed |
|---|---|---|
| stub-LLM repro | 32/32 canaries re-sent | a **deterministic pipeline** bug |
| real-model runs | 19/24, 17/24, 11/24 | **model-dependent** re-extraction |
| DB audit | rows retained | **observational** retention |

All three are true. Averaging them produces a number that is false. The
thread argued for weeks because there was no grammar for saying *which layer*
each number came from.

That grammar is this repository.

## What a gate catches that a test suite does not

```
$ python -m mgate selftest
{
  "ok": true,
  "clean_suite_verdict": "pass",
  "matrix": [
    {"defect": "resend_after_erase",  "gate": "erasure",   "caught": true},
    {"defect": "scope_keeps_records", "gate": "erasure",   "caught": true},
    {"defect": "surface_only_recall", "gate": "retrieval", "caught": true},
    {"defect": "no_supersession",     "gate": "staleness", "caught": true},
    {"defect": "trust_all_writes",    "gate": "poisoning", "caught": true}
  ]
}
```

`selftest` is the point of the repo. It plants five real defects into a
reference store — the same shapes that ship in production — and asserts that
the paired gate turns **red**. A gate that cannot be made to fail is
decoration. This one is measured in both directions: clean store green, every
planted defect red.

## Run it

```bash
python -m mgate list                    # what each gate asks
python -m mgate run                     # full suite against the reference store
python -m mgate run --gate erasure --defects resend_after_erase
python -m mgate run --json --out report.json
python -m mgate verify report.json      # digest + ledger + verdict consistency
python -m unittest discover -s tests    # 79 tests, 119 assertions
```

Sample output:

```
store: reference-store v1.0.0  defects=none
SUITE VERDICT: PASS  (6 gates: 6 pass, 0 fail, 0 abstain, 0 invalid)

  [erasure] PASS  gate=1.0.0 weakest=deterministic
    - prompt_resend        pass     (deterministic) 0/2 failed
    - re_extraction        pass     (model_dependent) 0/2 failed
    - storage_residue      pass     (observational) 0/2 failed
```

## Judge your own store

Implement eight methods and every gate applies:

```python
from mgate.adapters import MemoryAdapter

class MyStore(MemoryAdapter):
    name, version = "mystore", "1.4.2"

    def setup(self, *, reset=True): ...        # load fixtures
    def add(self, messages, *, user_id="u1"):  # -> list of new memory ids
    def retrieve(self, query, *, user_id="u1", limit=5):
    def erase_scope(self, *, user_id="u1"):
    def erase_record(self, *, memory_id):
    def extraction_prompts(self):              # prompts SENT to your LLM
    def raw_rows(self):                        # storage snapshot
    def checkpoint(self):
```

`extraction_prompts()` is the one that matters. It is the only way to tell
"the API said 200" apart from "the erased text was never handed to a model
again". If your adapter cannot expose it, the `prompt_resend` layer reports
`abstain` — the protocol refuses to substitute a guess.

## The five rules

1. **Four states, `invalid` outranks all.** A poisoned fixture reports nothing
   rather than a comfortable zero.
2. **Abstention is first class.** "I could not test this" is never silently
   converted to `pass`.
3. **Every layer declares its epistemic class.** A claim containing *always*,
   *never*, *guaranteed* or *100%* must bind a `deterministic` layer — the
   implementation rejects the report otherwise.
4. **No sample, no failure.** A failure without a reproducible sample is a
   rumour.
5. **`certified` is a gated flag.** Requires an authorised issuer and a
   signature. Self-run reports cannot carry it.

Full normative text: [PROTOCOL.md](PROTOCOL.md).

## Claims you can cite

Six clauses a memory product can be held to, each checkable by one gate:
see `CLAUSES` in [`mgate/gates/claims.py`](mgate/gates/claims.py), ids C1–C6.
A repo reviewing memory vendors can cite `C1` instead of re-arguing what
"erasure works" means.

## Honest limits

- Gates judge the **adapter's public verbs**. An adapter that hides prompts
  will look clean.
- `re_extraction` is `model_dependent` by nature. It reports counts and is
  never asserted in CI. Do not quote it as a guarantee.
- `storage_residue` is a **flag**, not a failure. Audit retention is often a
  legal requirement.
- One injection shape is tested (imperative override). Encoded and indirect
  injections are out of scope for v1.0.
- The reference store is a test rig, not a product. It exists so the gates
  have something to falsify.
- Adapters may declare `ranking_signal = "none"` when their ordering carries
  no information (e.g. constant embeddings with no lexical index). Every
  rank-dependent layer then **abstains** instead of reporting a position as a
  finding. The mem0 run is in exactly this state.

## Licensing

- Code: **Apache-2.0** — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
- Specification: **CC BY 4.0** — implement freely; attribute the spec when you
  claim conformance.
- Certification: a separate, gated function. See
  [COMMERCIAL.md](COMMERCIAL.md) for exactly what is open, what is withheld,
  and why.

## Provenance

Built by **正明 (Zhengming)** for 善伦 / chenhz01, out of real defect threads
including mem0ai/mem0#7452 and thedotmack/claude-mem#4138. Design decisions and
their dates: [ORIGIN.md](ORIGIN.md). Cite as [CITATION.cff](CITATION.cff).
