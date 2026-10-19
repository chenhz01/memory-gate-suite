# Related work — and what this repository is not

Written after the first release, because the honest version is more useful
than the flattering one.

**Short version: the memory-evaluation space is crowded. The conformance space
is not.** Most existing work answers *"which memory system is better?"* This
repository answers a narrower question: *"did this build pass a specific,
falsifiable line — and who is willing to put their name on that answer?"*

If you are choosing a memory product, use a benchmark. If you are signing off
that one is safe to ship, you need a conformance verdict. Those are different
jobs, and conflating them is how "19/24 passed" became a marketing number.

---

## 1. The projects we overlap with

| Project | What it actually does | Where it differs from MGP-1.0 |
|---|---|---|
| **DolphinBench** (mem0, 2026) — [repo](https://github.com/mem0ai/dolphinbench), [arxiv 2609.24971](https://arxiv.org/abs/2609.24971) | Action-based agent-memory benchmark: 600 tool-using tests across three personas, cost and latency reported alongside accuracy, and per-test **solvability certification** via with/without-history agent runs. | Measures whether memory improves *task outcomes*. Does not ask whether a delete actually deletes, whether a superseded fact still outranks its replacement, or whether an injected instruction was stored at full trust. Its solvability check validates the *fixture*, not the *store*. |
| **STATE-Bench** (Microsoft, 2026) — [blog](https://opensource.microsoft.com/blog/2026/05/19/introducing-state-bench-a-benchmark-for-ai-agent-memory/) | Memory-agnostic enterprise task benchmark: 450 tasks, deterministic state assertions, pass^5 reliability. | Closest to us in spirit on "deterministic assertions", but its unit is the *task*, not the memory property. A task can fail for prompt reasons; a property violation cannot be blamed elsewhere. |
| **MemEval** — [write-up](https://www.mech.app/articles/memeval-testing-framework-for-ai-agent-memory-systems) | YAML scenarios, a harness, per-backend adapters (4 methods), 7 metrics, CI reports. | **Architecturally the closest thing to this repository**, and that deserves saying plainly. Its adapter contract and ours solve the same seam problem. The difference is the output: MemEval emits a *scorecard*; MGP emits a *sealed verdict* with four states, per-layer epistemic class, mandatory samples, and a tamper-evident ledger digest. |
| **Ground Truth First / Veracium** — [arxiv 2607.21962](https://scifaro.com/en/abs/ground-truth-first-a-longitudinal-evaluation-instrument-for-agent-memory-and-the-tenure-crossover-in-memory-architecture-rankings-2607.21962) | Longitudinal instrument: seeded life-script, validity intervals, injection probes, provenance typing, rankings that invert over horizons. | The most rigorous work in this list, and the closest on **write-path trust** (our `poisoning` gate). Its output is a ranking under controlled conditions; ours is a per-build verdict plus a clause library a third party can cite. |
| **governed-memory** (personizeai, MIT) — [repo](https://github.com/personizeai/governed-memory) | 15 reproducible experiment protocols covering extraction quality, routing, token savings, temporal conflict, and adversarial pressure. | Its stated norm — *"a memory layer's capability claims must ship with experimental evidence"* — is essentially our R3. The difference is enforcement: they state it as a standard, we reject the report at seal time when a claim outruns its evidence layer. |

Assessed 2026-10-19. If a listed project changes direction, this table is
wrong and should be corrected by PR.

## 2. The five things we are actually claiming

Narrow on purpose. Each is checkable against the table above.

1. **A verdict is a sealed object, not a score.** Four states with `invalid`
   taking precedence, a digest, and a hash-chained ledger bound into the
   report. A score cannot express "the fixture was poisoned, this run counts
   for nothing"; a verdict can.
2. **Epistemic class is a first-class field, and it is enforced.** A claim
   containing *always* / *never* / *guaranteed* / `100%` that binds a
   model-dependent layer is **rejected**, not merely discouraged.
3. **Certification is a gated flag in the code path.** `certified: true`
   requires an issuer and a signature; the reference implementation raises
   without them. Nobody else in this list sells or gates a certification mark,
   which is either an opportunity or a warning — see §4.
4. **Erasure re-materialisation as a named property.** Not "does memory help",
   but "after a successful delete, can the erased text re-enter a prompt, and
   can it come back as a new memory". This came from a specific public defect
   thread (mem0#7452) with three incompatible measurement layers.
5. **A clause library a third party can cite.** `C1`–`C6` in
   [`mgate/gates/claims.py`](mgate/gates/claims.py): six sentences a vendor can
   be held to, each with a gate that decides it.

## 3. What we are not claiming

- **Not first.** Benchmarks for agent memory predate this repository by at
  least a year. Any claim of priority over the space would be false.
- **Not a better benchmark.** DolphinBench has 13,539 messages, three
  personas, and a leaderboard. We have a reference store with switchable
  defects. Those are not comparable artefacts and we will not pretend they are.
- **Not better adapters.** MemEval's four-method adapter is simpler than our
  eight-method contract. Ours is larger because a gate needs
  `extraction_prompts()` — the ability to see what was sent to the model. That
  is a requirement of the erasure property, not a claim of superior design.
- **Not validated on production vendors in v1.0.** The six gates were run
  against the reference store. Cross-vendor results are explicitly withheld
  (see [COMMERCIAL.md](COMMERCIAL.md) §1 Ring 3). Anyone who needs that data
  should treat the current release as a method, not a survey.

## 4. The uncomfortable question

If benchmarks are crowded and certification is empty, why is certification
empty? Two possibilities:

- **Nobody needed it yet.** Plausible: memory products are young, buyers have
  not started asking for signed conformance evidence.
- **It is structurally hard.** Also plausible: a certification body needs
  neutrality, and the people best placed to run it are the people selling
  memory products. A vendor-run certification is a brochure with a signature.

We do not have evidence that settles this. What we have is a bet: that as
memory stores start handling regulated data, "which one scores higher" stops
being the question and "can you prove this build erases" becomes the question.
If that bet is wrong, §1's table is still a useful map and the gates are still
runnable, which is an acceptable way to be wrong.

Stated here rather than discovered later.
