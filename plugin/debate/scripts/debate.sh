#!/usr/bin/env bash
# Wrapper script for the agent-debate Python package.
# Used by the /debate command to check availability and run debates.
#
# Usage:
#   debate.sh check    — exit 0 if agent-debate is installed, 1 otherwise
#   debate.sh run ...  — pass all args to agent-debate run

set -euo pipefail

case "${1:-}" in
  check)
    if command -v agent-debate &>/dev/null; then
      echo '{"available": true, "version": "'"$(agent-debate --version 2>/dev/null || echo 'unknown')"'"}'
      exit 0
    else
      echo '{"available": false}'
      exit 1
    fi
    ;;
  run)
    shift
    exec agent-debate run "$@"
    ;;
  discover)
    exec agent-debate discover
    ;;
  *)
    echo "Usage: debate.sh {check|run|discover}" >&2
    exit 1
    ;;
esac
