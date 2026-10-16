#!/usr/bin/env bash
# Quick Bash wrapper for clickup_export.py
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/clickup_export.py"

if [ -z "$1" ]; then
  echo "Usage: ./clickup-export.sh <CLICKUP_TASK_URL_OR_ID> [options]"
  echo "       ./clickup-export.sh --from-export <DIR> --sdd [options]"
  echo ""
  echo "Standard Examples:"
  echo "  ./clickup-export.sh https://app.clickup.com/t/86a1b2c3d -o ~/Downloads"
  echo "  ./clickup-export.sh PROJ-101 --both"
  echo ""
  echo "Spec-Driven Development (SDD) Examples:"
  echo "  ./clickup-export.sh PROJ-101 --sdd"
  echo "  ./clickup-export.sh PROJ-101 --sdd --no-tracking"
  echo "  ./clickup-export.sh PROJ-101 --sdd --specs-dir ~/Developer/project-specs --workspace"
  echo "  ./clickup-export.sh --from-export /path/to/exported-story --sdd --no-tracking"
  exit 1
fi

python3 "$PYTHON_SCRIPT" "$@"
