#!/usr/bin/env bash
# Tests xagent's classify() against crafted replies. usage: xagent-classify.test.sh [path-to-xagent]
set -uo pipefail
src=${1:-"$(dirname "$0")/../bin/xagent"}
eval "$(sed -n '/^classify() {/,/^}/p' "$src")"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fail=0

check() { # name expected exit timed_out reply
  printf '%b' "$5" > "$tmp/r.md"
  local got; got=$(classify "$3" "$4" "$tmp/r.md")
  if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1: expected $2, got $got"; fail=1; fi
}

check "clean pass"                 PASS    0 0 'Fixed it.\nSTATUS: PASS\n'
check "trailing blank lines"       ISSUES  0 0 'Found 2 bugs.\nSTATUS: ISSUES\n\n\n'
check "markdown bold"              BLOCKED 0 0 'Cannot reach repo.\n**STATUS: BLOCKED**\n'
check "last verdict wins"          ISSUES  0 0 'STATUS: PASS\nre-checked, one bug left\nSTATUS: ISSUES\n'
check "echoed instruction only"    DROPOUT 0 0 'I will end with STATUS: PASS, STATUS: ISSUES, or STATUS: BLOCKED.\n'
check "said it would, no verdict"  DROPOUT 0 0 'I will create hello.txt now.\n'
check "empty reply"                DROPOUT 0 0 ''
check "nonzero exit with verdict"  DROPOUT 1 0 'STATUS: PASS\n'
check "timeout with verdict"       DROPOUT 124 1 'STATUS: PASS\n'
check "lowercase is not a verdict" DROPOUT 0 0 'status: pass\n'

exit $fail
