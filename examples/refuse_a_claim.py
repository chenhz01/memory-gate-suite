#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""The evidence ceiling, executed.

A vendor can write "erasure always works" in a README.  Nothing stops them.
This example shows the one place where the sentence cannot survive: the seal
step.  A claim that asserts absoluteness while resting on a model-dependent
layer raises ``ProtocolError``, and no report file is produced.

That is the whole difference between a guideline and a gate:

    A guideline can be ignored.
    A seal that refuses to emit the file cannot.

Run:  python examples/refuse_a_claim.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mgate.protocol import (DETERMINISTIC, MODEL_DEPENDENT, Claim,
                            ProtocolError, Layer, Report, Subject)


def build(claim_text: str, layer_confidence: str) -> Report:
    rep = Report(
        gate="demo",
        gate_version="1.0.0",
        subject=Subject(kind="memory_store", name="example-store",
                        version="0.1.0", adapter="DemoAdapter"),
    )
    L = Layer("re_extraction", confidence=layer_confidence,
              note="counts recovered under a deterministic stand-in model")
    L.add("no_reextraction", True, "0 of 24 recovered (stub extractor)")
    rep.layers = [L]
    rep.claims = [Claim(claim_text, status="supported",
                        layer="re_extraction")]
    return rep


def main() -> None:
    print("1) absolute claim on a model-dependent layer")
    try:
        rep = build("Erased text always stays erased.", MODEL_DEPENDENT)
        rep.seal()
        print("   UNEXPECTED: seal accepted the claim")
    except ProtocolError as exc:
        print(f"   REFUSED at seal time -> {exc}")
        print("   no report file exists; the sentence cannot be published "
              "as a sealed verdict")

    print("\n2) the same evidence, stated at the strength it supports")
    rep = build("0 of 24 samples recovered after erase (stub extractor).",
                MODEL_DEPENDENT)
    sealed = rep.seal()
    print(f"   SEALED gate={sealed.gate} verdict={sealed.verdict()} "
          f"digest={sealed.digest()[:23]}...")

    print("\n3) an absolute claim backed by a deterministic layer")
    rep = build("Erased text never re-enters the extraction prompt "
                "(deterministic adapter).", DETERMINISTIC)
    sealed = rep.seal()
    print(f"   SEALED gate={sealed.gate} verdict={sealed.verdict()} "
          f"digest={sealed.digest()[:23]}...")

    print("\nThe rule is not 'do not claim'. It is 'claim at the "
          "resolution your evidence actually has'.")


if __name__ == "__main__":
    main()
