#!/usr/bin/env bash
# Project Forge — Single batch run orchestrator
# Usage: ./run_batch.sh [--category CATEGORY] [--batch-size N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CATEGORY="${1:---all}"
BATCH_SIZE="${2:-10}"

echo "=============================================="
echo "  Project Forge — Batch Run"
echo "=============================================="
echo "  Category: $CATEGORY"
echo "  Batch size: $BATCH_SIZE"
echo ""

# Step 1: Check seeds exist
SEED_COUNT=$(cat seeds/*.jsonl 2>/dev/null | wc -l || echo 0)
if [ "$SEED_COUNT" -eq 0 ]; then
    echo "No seeds found. Generating seeds first..."
    python3 generate_seeds.py
fi

# Step 2: Check master prompt
if [ ! -f master_prompt.md ]; then
    echo "ERROR: master_prompt.md not found!"
    echo "Please paste the master prompt into forge-data/master_prompt.md first."
    exit 1
fi

# Step 3: Show status
echo ""
echo "Current progress:"
python3 generate_conversations.py --status

# Step 4: Prepare next batch
echo ""
echo "Preparing next batch..."
if [ "$CATEGORY" = "--all" ]; then
    python3 generate_conversations.py --batch-size "$BATCH_SIZE" --all
else
    python3 generate_conversations.py --batch-size "$BATCH_SIZE" --category "$CATEGORY"
fi

echo ""
echo "=============================================="
echo "  Next steps:"
echo "  1. Claude Code generates conversations for seeds listed above"
echo "  2. Run: python3 validate.py conversations/batch_NNN/"
echo "  3. Run: python3 score.py validated/"
echo "  4. Repeat until all seeds are done"
echo "=============================================="
