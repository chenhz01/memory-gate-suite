# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Gate registry.  Import order is the default suite order."""

from . import claims, erasure, handoff, poisoning, retrieval, staleness

GATES = {
    "erasure": {"module": erasure, "layer_d": "D1",
                "question": "can erased text reach a model or return as memory?"},
    "retrieval": {"module": retrieval, "layer_d": "D2",
                  "question": "is retrieval contributing, or just matching tokens?"},
    "staleness": {"module": staleness, "layer_d": "D3",
                  "question": "does memory know which fact version is current?"},
    "poisoning": {"module": poisoning, "layer_d": "D4",
                  "question": "is the write path a trust boundary?"},
    "handoff": {"module": handoff, "layer_d": "D8",
                "question": "does memory survive a session or vendor handoff?"},
    "claims": {"module": claims, "layer_d": "D6",
               "question": "does a published claim name its evidence layer?"},
}

ORDER = ("erasure", "retrieval", "staleness", "poisoning", "handoff", "claims")

__all__ = ["GATES", "ORDER", "claims", "erasure", "handoff", "poisoning",
           "retrieval", "staleness"]
