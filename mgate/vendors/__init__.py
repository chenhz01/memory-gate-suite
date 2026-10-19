# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
# Part of memory-gate-suite / MGP-1.0. See NOTICE and ORIGIN.md.
"""Vendor adapters: run the MGP gates against a real store, not our toy.

Each module exposes ``build(**kwargs) -> MemoryAdapter`` and is imported
lazily, so the core suite keeps zero third-party dependencies.
"""

from __future__ import annotations

from typing import Any, Dict

_BUILDERS = {
    "mem0": "mgate.vendors.mem0_adapter:build",
}


def available() -> Dict[str, str]:
    return dict(_BUILDERS)


def build(name: str, **kwargs: Any):
    """Instantiate a vendor adapter by name, importing its module on demand."""
    try:
        target = _BUILDERS[name]
    except KeyError:
        raise SystemExit(
            f"unknown adapter {name!r}; available: {sorted(_BUILDERS)}") from None
    mod_name, func_name = target.split(":")
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, func_name)(**kwargs)
