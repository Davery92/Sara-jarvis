#!/usr/bin/env bash
# Follow a research plan's live progress. Usage: research-watch.sh [plan-id-prefix]
# Research plans do NOT appear in the background-tasks tab — they live in the
# `research_plan` table and never create a `background_task` row.
set -euo pipefail
cd "$(dirname "$0")/.."
PREFIX="${1:-}"
WHERE="ORDER BY created_at DESC LIMIT 1"
[ -n "$PREFIX" ] && WHERE="AND id LIKE '${PREFIX}%' ORDER BY created_at DESC LIMIT 1"
while true; do
  clear
  docker compose exec -T db psql -U sara -d sara_hub -c "
    SELECT left(title,44) AS plan, status, current_step_index AS step, total_tokens_used AS tokens
    FROM research_plan WHERE true $WHERE;"
  docker compose exec -T db psql -U sara -d sara_hub -c "
    SELECT row_number() OVER () AS n, s->>'status' AS status, left(s->>'title',50) AS step,
           left(coalesce(s->'findings'->>'summary',''),46) AS findings
    FROM (SELECT steps FROM research_plan WHERE true $WHERE) p,
         jsonb_array_elements(p.steps) s;"
  echo "--- latest tool activity ---"
  docker logs jarvis-celery-david-priority-1 --since 3m 2>&1 \
    | grep -E "Executing step|Tool call:|compacted|report_findings|Step .* failed" \
    | tail -6 | cut -c1-160
  sleep 15
done
