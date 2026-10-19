# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""mgate -- MGP-1.0 memory quality gates.

Public surface:
    from mgate import ReferenceStore, run_suite, selftest
    from mgate.protocol import Report, Layer, Claim
"""

from .adapters import MemoryAdapter, NullAdapter, ReferenceStore
from .ledger import Ledger, NullLedger
from .protocol import (ABSTAIN, DETERMINISTIC, FAIL, INVALID,
                       MODEL_DEPENDENT, OBSERVATIONAL, PASS, PROTOCOL_ID,
                       PROTOCOL_VERSION, Claim, Layer, ProtocolError, Report,
                       Subject, aggregate, load_report)
from .runner import run_suite, selftest

__all__ = [
    "ABSTAIN", "DETERMINISTIC", "FAIL", "INVALID", "MODEL_DEPENDENT",
    "OBSERVATIONAL", "PASS", "PROTOCOL_ID", "PROTOCOL_VERSION",
    "Claim", "Layer", "Ledger", "MemoryAdapter", "NullAdapter", "NullLedger",
    "ProtocolError", "ReferenceStore", "Report", "Subject", "aggregate",
    "load_report", "run_suite", "selftest",
]

__version__ = "1.0.0"
