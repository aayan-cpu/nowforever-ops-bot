#!/usr/bin/env bash
# Worker self-registration.
# Generates a unique session id, records an "online" heartbeat, pushes it, and
# prints the id on the last line for the session to use when claiming tasks.
#
# Usage:
#   id=$(bash scripts/agent_register.sh)        # register, capture id
#   bash scripts/agent_register.sh heartbeat <id>   # later: ping liveness
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
mkdir -p .agents

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if [ "${1:-}" = "heartbeat" ]; then
  id="${2:?heartbeat needs an id}"
  echo "$(now) heartbeat ($id)" >> ".agents/${id}.log"
  git pull --rebase --quiet 2>/dev/null || true
  git add ".agents/${id}.log" && git commit -q -m "agent ${id} heartbeat" || true
  git push -q 2>/dev/null || true
  echo "$id"
  exit 0
fi

host=$(hostname | tr '[:upper:]' '[:lower:]' | cut -d. -f1)
id="${host}-$(printf '%04d' $((RANDOM % 10000)))"
# ensure uniqueness against existing logs
while [ -e ".agents/${id}.log" ]; do
  id="${host}-$(printf '%04d' $((RANDOM % 10000)))"
done

echo "$(now) online ($id)" >> ".agents/${id}.log"
git pull --rebase --quiet 2>/dev/null || true
git add ".agents/${id}.log" && git commit -q -m "agent ${id} online" || true
git push -q 2>/dev/null || true

# id is the last line of output, easy to capture
echo "$id"
