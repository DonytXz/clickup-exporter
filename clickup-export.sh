#!/usr/bin/env bash
# Quick Bash wrapper for clickup_export.py
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/clickup_export.py"

if [ -z "$1" ]; then
  echo "Usage: ./clickup-export.sh <CLICKUP_TASK_URL_OR_ID> [extra args]"
  echo "Example: ./clickup-export.sh https://app.clickup.com/t/86a1b2c3d -o ~/Downloads"
  exit 1
fi

python3 "$PYTHON_SCRIPT" "$@"
