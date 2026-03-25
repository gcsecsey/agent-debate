#!/usr/bin/env bash
# Wrapper script for the agent-debate Python package.
# Used by the /debate command to check availability and run debates.
#
# Usage:
#   debate.sh check    — exit 0 if agent-debate is installed, 1 otherwise
#   debate.sh run ...  — pass all args to agent-debate run

set -euo pipefail

# Find agent-debate: check venv in the plugin's repo first, then PATH
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV_BIN="$REPO_ROOT/venv/bin/agent-debate"

if [[ -x "$VENV_BIN" ]]; then
  AGENT_DEBATE="$VENV_BIN"
elif command -v agent-debate &>/dev/null; then
  AGENT_DEBATE="agent-debate"
else
  AGENT_DEBATE=""
fi

case "${1:-}" in
  check)
    if [[ -n "$AGENT_DEBATE" ]]; then
      echo '{"available": true, "version": "'"$("$AGENT_DEBATE" --version 2>/dev/null || echo 'unknown')"'"}'
      exit 0
    else
      echo '{"available": false}'
      exit 1
    fi
    ;;
  run)
    shift
    exec "$AGENT_DEBATE" run "$@"
    ;;
  discover)
    exec "$AGENT_DEBATE" discover
    ;;
  *)
    echo "Usage: debate.sh {check|run|discover}" >&2
    exit 1
    ;;
esac
