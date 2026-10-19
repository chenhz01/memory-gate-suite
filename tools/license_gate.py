#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chenhz01 (Zhengming, for Shanlun)
"""F21 dual-licence gate -- code Apache-2.0 + spec CC BY 4.0, no exceptions.

Usage:
    python tools/license_gate.py [path]            # human report
    python tools/license_gate.py [path] --json     # machine report

Exit codes: 0 = all five requirements present, 1 = one or more missing,
2 = usage error.

Why a gate and not a checklist: a licence is the only part of attribution that
survives someone copying the code.  A missing LICENSE-SPEC is not a paperwork
gap, it is a permanent loss of the right to be named when someone claims
conformance.  F21 requires the check to be executable, not remembered.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist",
             "build", ".mypy_cache", ".pytest_cache"}
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs", ".go",
            ".java", ".kt", ".rb", ".sh", ".c", ".h", ".cpp", ".hpp", ".swift"}


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _code_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in CODE_EXT:
                yield os.path.join(dirpath, name)


def check(root: str = ".") -> dict:
    root = os.path.abspath(root)
    checks = []

    def add(name: str, ok: bool, detail: str, severity: str = "hard"):
        checks.append({"name": name, "ok": bool(ok), "detail": detail,
                       "severity": severity})

    lic = _read(os.path.join(root, "LICENSE"))
    add("LICENSE_apache_full",
        "Apache License" in lic and "Version 2.0" in lic,
        "LICENSE must contain the full Apache-2.0 text, not just an SPDX id")

    spec = _read(os.path.join(root, "LICENSE-SPEC"))
    add("LICENSE_SPEC_cc_by",
        bool(spec) and ("CC BY 4.0" in spec or "creativecommons.org/licenses/by/4.0" in spec),
        "LICENSE-SPEC must declare CC BY 4.0 with the legalcode link")

    notice = _read(os.path.join(root, "NOTICE"))
    has_both = "Apache" in notice and ("CC BY" in notice or "Creative Commons" in notice)
    has_trigger = any(k in notice.lower() for k in
                      ("attribution", "conformance", "符合", "署名"))
    add("NOTICE_dual_and_trigger", has_both and has_trigger,
        "NOTICE must state both licences and when attribution is required")

    readme = _read(os.path.join(root, "README.md"))
    low = readme.lower()
    add("README_licence_section",
        "apache-2.0" in low and ("cc by 4.0" in low or "creative commons" in low)
        and ("licen" in low or "许可" in readme),
        "README must carry a Licence section naming both licences")

    files = list(_code_files(root))
    missing = [os.path.relpath(p, root) for p in files
               if "SPDX-License-Identifier" not in _read(p)[:400]]
    add("SPDX_headers", not missing,
        f"{len(files) - len(missing)}/{len(files)} code files carry an SPDX "
        f"identifier" + (f"; missing: {missing[:5]}" if missing else ""))

    hard_fail = [c for c in checks if not c["ok"] and c["severity"] == "hard"]
    return {
        "root": root,
        "protocol": "F21/1.0",
        "ok": not hard_fail,
        "checks": checks,
        "failed": [c["name"] for c in hard_fail],
        "code_files": len(files),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="F21 dual-licence gate")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.path):
        print(f"not a directory: {args.path}")
        return 2

    res = check(args.path)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"F21 dual-licence gate  {res['root']}")
        for c in res["checks"]:
            print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']:<26} {c['detail']}")
        print(f"\n{'OK' if res['ok'] else 'BLOCKED'}  "
              f"({len(res['checks']) - len(res['failed'])}/{len(res['checks'])} checks)")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
