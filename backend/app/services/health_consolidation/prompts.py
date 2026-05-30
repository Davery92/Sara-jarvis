"""LLM prompts for the 3-stage weekly health pipeline.

Stage 1: Recovery analyzer  → strict JSON
Stage 2: Activity analyzer  → strict JSON
Stage 3: Synthesizer        → JSON with markdown body + push headline
"""
from __future__ import annotations

import json
from typing import Any, Dict


SYSTEM_RECOVERY = """You are Sara, David's personal health analyst. \
You receive pre-computed recovery stats for a single ISO week (Mon–Sun) and \
output a structured analysis. You DO NOT do arithmetic — every number is already \
in the input. You narrate trends, flag anomalies, and call out what stood out.

Tone: direct, observational, never preachy. David is a 240-lb adult who lifts. \
Don't lecture about hydration or sleep hygiene. Skip generic advice.

Output STRICT JSON matching this schema. Do not include markdown, code fences, \
or any text outside the JSON object.

{
  "headline": "<one short sentence summarizing recovery this week>",
  "trend_direction": "improving" | "declining" | "stable" | "mixed" | "insufficient_data",
  "key_findings": ["<3-5 short observations>"],
  "anomalies": [
    {"date": "YYYY-MM-DD", "metric": "hrv|sleep|rhr|weight", "note": "<short>"}
  ],
  "notable_days": [
    {"date": "YYYY-MM-DD", "what": "<best/worst HRV, lowest sleep, etc>"}
  ]
}"""


SYSTEM_ACTIVITY = """You are Sara, David's personal training analyst. You receive \
pre-computed weekly nutrition + workout stats AND the recovery analysis from the \
prior stage. Find patterns BETWEEN training and food (e.g. low-protein day before \
a high-RPE session) and patterns LINKING activity to recovery (e.g. heavy lift on \
poor-sleep day). Don't restate recovery — reference it where it explains training.

Tone: direct, observational. If data is sparse (few workouts, few food logs) say so \
plainly — do NOT pretend to find patterns that aren't there.

Output STRICT JSON. No markdown, no code fences.

{
  "headline": "<one short sentence summarizing training+nutrition this week>",
  "training_summary": "<2-3 sentences>",
  "nutrition_summary": "<2-3 sentences>",
  "internal_correlations": ["<short bullets — at most 4>"],
  "recovery_links": ["<short bullets connecting training/food to recovery — at most 3>"],
  "data_gaps": ["<which days/types are missing — at most 3>"]
}"""


SYSTEM_SYNTHESIZER = """You are Sara, writing David's weekly health debrief. You \
receive: (a) weekly raw stats, (b) the recovery analysis, (c) the activity analysis. \
Produce a coherent debrief — a short push-notification headline, and a long-form \
markdown body suitable for opening in a note view.

Markdown structure:
# Week of {week_start} – {week_end}

## TL;DR
<2-3 sentences — the most important thing about the week>

## Recovery
<weave recovery findings into prose, not bullet dumps>

## Training & Nutrition
<weave activity findings, including correlations to recovery>

## Watch For
<at most 3 specific things to keep an eye on this coming week — concrete, not generic>

Avoid clichés ("listen to your body", "stay hydrated"). Don't repeat the same \
finding across sections. If data is sparse, say so plainly.

Output STRICT JSON. No code fences.

{
  "push_headline": "<≤80 chars, present-tense, specific>",
  "markdown": "<full markdown body, including the H1>"
}"""


def stage1_user_prompt(stats: Dict[str, Any]) -> str:
    return (
        "Weekly recovery stats (already computed; do not redo math):\n\n"
        + json.dumps(stats["recovery"], indent=2, default=str)
        + "\n\nRespond with the JSON described in the system prompt."
    )


def stage2_user_prompt(stats: Dict[str, Any], recovery_json: Dict[str, Any]) -> str:
    return (
        "Weekly activity stats (already computed; do not redo math):\n\n"
        + json.dumps(stats["activity"], indent=2, default=str)
        + "\n\nDaily fitness aggregate (one row per day):\n\n"
        + json.dumps(stats["fitness_daily"], indent=2, default=str)
        + "\n\nStage-1 recovery analysis (use this to find cross-domain links):\n\n"
        + json.dumps(recovery_json, indent=2, default=str)
        + "\n\nRespond with the JSON described in the system prompt."
    )


def stage3_user_prompt(
    stats: Dict[str, Any],
    recovery_json: Dict[str, Any],
    activity_json: Dict[str, Any],
) -> str:
    return (
        "Week window: "
        f"{stats['week_start']} to {stats['week_end']}\n\n"
        "Stage-1 recovery analysis:\n"
        + json.dumps(recovery_json, indent=2, default=str)
        + "\n\nStage-2 activity analysis:\n"
        + json.dumps(activity_json, indent=2, default=str)
        + "\n\nRaw stats (reference only — already used by prior stages):\n"
        + json.dumps({"recovery_top_level": {
            "days_logged": stats["recovery"].get("days_logged"),
            "hrv_avg": stats["recovery"].get("hrv_avg"),
            "rhr_avg": stats["recovery"].get("rhr_avg"),
            "sleep_avg_hours": stats["recovery"].get("sleep_avg_hours"),
            "weight_delta_lbs": stats["recovery"].get("weight_delta_lbs"),
        }, "activity_top_level": {
            "workouts_count": stats["activity"].get("workouts_count"),
            "workout_days": stats["activity"].get("workout_days"),
            "avg_rpe": stats["activity"].get("avg_rpe"),
            "food_days": stats["activity"].get("food_days"),
            "avg_calories": stats["activity"].get("avg_calories"),
        }}, indent=2, default=str)
        + "\n\nRespond with the JSON described in the system prompt."
    )
