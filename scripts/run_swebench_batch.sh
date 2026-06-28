#!/usr/bin/env bash
# Run a SWE-bench Lite subset with OpenHands at full turn budgets (MAX_TURNS=100).
#
# Delegates to scripts/run_swebench_sdk.py which uses the installed
# openhands-ai SDK (LocalConversation) — no Docker required.
#
# Prerequisites
# -------------
#   export ANTHROPIC_API_KEY=sk-ant-...   (or OPENAI_API_KEY)
#   pip install openhands-ai datasets      (done automatically if missing)
#
# Usage
# -----
#   bash scripts/run_swebench_batch.sh                    # 60 instances, haiku
#   bash scripts/run_swebench_batch.sh django 20          # 20 django instances
#   bash scripts/run_swebench_batch.sh "" 10 gpt-4o       # 10 instances with GPT-4o
#
# Outputs
# -------
#   data/traces/run_<timestamp>/     — one JSONL per instance
#   data/traces/run_<timestamp>/metadata.json  — run config

set -euo pipefail

REPO_FILTER="${1:-}"
MAX_INSTANCES="${2:-60}"
MODEL="${3:-claude-haiku-4-5-20251001}"

# ── pre-flight checks ────────────────────────────────────────────────────── #
if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: Set ANTHROPIC_API_KEY or OPENAI_API_KEY before running."
    echo ""
    echo "  export ANTHROPIC_API_KEY=sk-ant-..."
    echo "  bash scripts/run_swebench_batch.sh"
    exit 1
fi

# activate venv if present
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

# ensure required packages
python3 -c "import openhands" 2>/dev/null || pip install openhands-ai --quiet
python3 -c "from datasets import load_dataset" 2>/dev/null || pip install datasets --quiet

# ── delegate to Python runner ────────────────────────────────────────────── #
ARGS=("--max-instances" "$MAX_INSTANCES" "--model" "$MODEL")
[[ -n "$REPO_FILTER" ]] && ARGS+=("--repo" "$REPO_FILTER")

exec python3 scripts/run_swebench_sdk.py "${ARGS[@]}"
