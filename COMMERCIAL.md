# Commercial boundary — what is open, what is not, and why

This file exists because "open source" and "we make money from this" are not
contradictory, but they do need a line drawn in public so nobody is surprised
later. The line follows the **certification-body model** (think UL or TÜV):
the standard is published, the test method is published, the certification
mark is licensed.

## 1. The three rings

### Ring 1 — Open (Apache-2.0 code, CC BY 4.0 spec)

- The protocol grammar (`PROTOCOL.md`) and the five rules.
- All six reference gates and the suite runner.
- The adapter contract and the reference store with its defect modes.
- The falsification matrix (`mgate selftest`) — including the stores that are
  *supposed* to fail.
- The claim-audit clause library (`CLAUSES`, C1–C6), citable by id.

Anyone may use, modify, embed, or resell Ring 1. No permission needed, no
royalty, no field-of-use restriction. That is the point: adoption is the
product's distribution.

### Ring 2 — Open, but gated by the protocol itself

- The `certified: true` flag on a report.

`certified` is not a comment field. R5 requires `issued_by` and `signature`.
A self-run report is structurally incapable of carrying it — the reference
implementation raises at seal time. So "certified MGP-1.0" means a specific
authorised issuer ran the suite on a specific version and put their name on
the digest.

This is the entire commercial mechanism, and it is deliberately thin: the
protocol does the enforcement, not a contract.

### Ring 3 — Not open

Deliberately withheld, and stated here so the withholding is honest rather
than discovered:

| Withheld | Why |
|---|---|
| Real-world memory corpora and adversarial fixture packs | These are the calibration asset. Publishing them lets anyone reproduce the *hard* cases without doing the work, and hands attackers a target list. |
| Scoring curves and per-vendor calibration data | Measuring a store is cheap; knowing how the measurement behaves across stores is not. |
| Cross-vendor compatibility matrix (measured, dated) | This is field data from real runs. It is the thing customers actually buy. |
| Enterprise deployment packaging, audit report templates | Delivery artefacts, not standards. |
| Customer identities and case data | Not ours to publish. |

**Nothing in Ring 3 is required to implement or use MGP-1.0.** A conforming
implementation can be built entirely from Rings 1 and 2. Ring 3 only affects
how *accurate* your calibration is and whether a third party will accept your
verdict — which is precisely the difference between "I ran a test" and
"someone certified the result".

## 2. What certification buys and does not buy

A certified report states: *this version of this store, on this date, judged by
these gates at this gate version, produced these verdicts, and the digests
reproduce.*

It does **not** state: that the product is secure, that it is legally
compliant, that it will behave the same after an upgrade, or that a `pass`
covers properties no gate tested. Every report carries a mandatory `limits`
array for exactly this reason.

Certification is per gate, per version, per date. A vendor who changes their
extraction pipeline invalidates the certification by shipping, which is the
intended behaviour.

## 3. Honest statements about licensing durability

- Already-published versions under Apache-2.0 are irrevocable. That is the
  licence, and it is not a trick.
- Future *new* files may be published under a different licence. No blanket
  "everything forever is Apache-2.0" promise is made here, because a promise
  like that is usually broken quietly and it is better not to make it.
- The specification is CC BY 4.0 permanently for published versions.
- `MGP`, `Memory Gate Protocol`, and `mgate` are used as source identifiers.
  No registered trademark is claimed at time of writing; the identifiers exist
  so that conformance claims can be checked against a named standard rather
  than an unnamed one.

## 4. What we ask in return

Nothing enforceable. Three requests, in order of how much they matter:

1. **If you implement this, say so by name.** "MGP-1.0-conforming" plus a link
   costs you nothing and keeps the grammar traceable.
2. **If you find a gate that cannot fail, tell us.** A gate that always passes
   is worse than no gate, because it manufactures confidence. That is a bug
   report worth more than a star.
3. **If you publish a number, publish its layer.** A percentage with no
   `confidence` class is the exact failure this protocol was built to stop.

## 5. Why not just MIT everything and monetise consulting?

Because that is what everyone does, and it produces the current state of the
market: a dozen vendors with incompatible green lights and no way to compare
them. The certification ring is the only part of this design that gives a
verdict *external* meaning. Remove it and the protocol becomes a formatting
convention.

The bet is simple: **a verdict that a third party can verify is worth more than
a verdict that only its author can.** If that bet is wrong, Ring 1 is still
useful to everyone who took it, and that is an acceptable failure mode.
