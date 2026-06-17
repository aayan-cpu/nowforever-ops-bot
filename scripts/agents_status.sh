#!/usr/bin/env bash
# Manager view: who is online and which task each session is working on.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git pull --rebase --quiet 2>/dev/null || true

echo "=== Registered agents (.agents/*.log — last heartbeat) ==="
shopt -s nullglob
found=0
for f in .agents/*.log; do
  found=1
  id=$(basename "$f" .log)
  last=$(tail -n1 "$f")
  printf "  %-18s %s\n" "$id" "$last"
done
[ "$found" = 0 ] && echo "  (no agents registered yet)"

echo
echo "=== Claimed / in-review tasks (WORK.md) ==="
if grep -nE '^- \[.\] \((CLAIMED|REVIEW)' WORK.md >/dev/null 2>&1; then
  grep -nE '^- \[.\] \((CLAIMED|REVIEW)' WORK.md
else
  echo "  (none claimed)"
fi
