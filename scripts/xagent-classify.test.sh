#!/usr/bin/env bash
# Offline verdict contract; optionally test another xagent implementation.
set -euo pipefail
python3 - "${1:-$(dirname "$0")/../bin/xagent}" <<'PY'
import runpy
import sys

classify = runpy.run_path(sys.argv[1])["classify"]
cases = [
    ("clean pass", "PASS", 0, False, "Fixed it.\nSTATUS: PASS\n"),
    ("trailing blank lines", "ISSUES", 0, False, "Found bugs.\nSTATUS: ISSUES\n\n"),
    ("markdown bold", "BLOCKED", 0, False, "Cannot reach repo.\n**STATUS: BLOCKED**\n"),
    ("final correction", "ISSUES", 0, False, "STATUS: PASS\nOne bug remains.\nSTATUS: ISSUES\n"),
    ("echoed instruction", "DROPOUT", 0, False, "End with STATUS: PASS, STATUS: ISSUES, or STATUS: BLOCKED.\n"),
    ("no verdict", "DROPOUT", 0, False, "I will create hello.txt now.\n"),
    ("empty reply", "DROPOUT", 0, False, ""),
    ("nonzero exit", "DROPOUT", 1, False, "STATUS: PASS\n"),
    ("timeout", "DROPOUT", 124, True, "STATUS: PASS\n"),
    ("lowercase", "DROPOUT", 0, False, "status: pass\n"),
    ("unfinished after verdict", "DROPOUT", 0, False, "STATUS: PASS\nI have not finished.\n"),
    ("quoted verdict", "DROPOUT", 0, False, "Example:\n> STATUS: PASS\n"),
    ("closed code sample", "DROPOUT", 0, False, "```text\nSTATUS: PASS\n```\n"),
    ("unclosed code sample", "DROPOUT", 0, False, "```text\nSTATUS: PASS\n"),
    ("indented code sample", "DROPOUT", 0, False, "Example:\n\n    STATUS: PASS\n"),
    ("tab code sample", "DROPOUT", 0, False, "Example:\n\n\tSTATUS: PASS\n"),
    ("tilde code sample", "DROPOUT", 0, False, "~~~text\nSTATUS: PASS\n"),
    ("verdict after code sample", "PASS", 0, False, "```text\nSTATUS: BLOCKED\n```\nSTATUS: PASS\n"),
]
for name, expected, code, timed_out, reply in cases:
    actual = classify(code, timed_out, reply)
    assert actual == expected, f"{name}: expected {expected}, got {actual}"
    print("ok  ", name)
PY
