#!/usr/bin/env bash
# Convenience wrapper around run_swebench_smoke.py.
#
# Prerequisites:
#   1. ANTHROPIC_API_KEY is exported
#   2. .venv-openhands/ exists  (pip install openhands-ai datasets gitpython)
#
# Usage:
#   source .env.openhands
#   bash scripts/run_swebench_smoke.sh

set -euo pipefail

N="${EVAL_N:-10}"
OUTPUT_DIR="${EVAL_OUTPUT_DIR:-data/openhands_output}"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set."
  echo "  Run:  source .env.openhands   (after filling in your key)"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "==> Running SWE-bench Lite smoke test: $N instances with ${OPENHANDS_MODEL:-claude-haiku-4-5-20251001}"
.venv-openhands/bin/python scripts/run_swebench_smoke.py \
  --n "$N" \
  --out "$OUTPUT_DIR/output.jsonl"

echo ""
echo "==> Done. $(wc -l < "$OUTPUT_DIR/output.jsonl") records in $OUTPUT_DIR/output.jsonl"
echo "==> Next: python scripts/ingest_openhands.py"
