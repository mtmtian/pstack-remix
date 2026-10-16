#!/usr/bin/env python3
"""Print a checkout's xagent snapshot, so a native reviewer's own command output records the state it reviewed.

Usage: python3 -B scripts/e2e-snapshot.py <checkout>
Ignored files such as test receipts and bytecode caches are left out, as in xagent's read-only check.
"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: e2e-snapshot.py <checkout>")
    checkout = Path(sys.argv[1]).resolve()
    digest = runpy.run_path(str(ROOT / "bin/xagent"))["snapshot"](checkout, checkout.parent)
    print("PSTACK_E2E_SNAPSHOT", digest, checkout)


if __name__ == "__main__":
    main()
