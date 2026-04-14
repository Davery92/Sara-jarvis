#!/usr/bin/env python3
"""
QA scoring for Project Forge training conversations.

Scores each validated conversation on 5 dimensions (1-5).
Since Claude Code is doing the scoring, this provides the framework and rubrics.
Actual scoring happens when Claude Code reads each file and evaluates it.

Usage:
    python score.py validated/
    python score.py --summary
    python score.py --failures
"""

import argparse
import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

BASE_DIR = Path(__file__).parent
VALIDATED_DIR = BASE_DIR / "validated"
SCORED_DIR = BASE_DIR / "scored"
SCORED_DIR.mkdir(exist_ok=True)

RUBRICS = {
    "memory_accuracy": {
        "description": "Correct keys, importance, decay, no missed writes",
        "5": "Perfect: all facts stored with correct keys, appropriate importance (varied), correct decay rates, no missed writes or duplicates",
        "4": "Good: minor key naming issues or slightly off importance values, but all facts captured",
        "3": "Acceptable: most facts captured, some importance/decay values generic, one missed write",
        "2": "Poor: multiple missed writes, wrong keys, or uniform importance scores",
        "1": "Failing: fundamental memory operation errors, many missed writes, hallucinated memories",
    },
    "memory_restraint": {
        "description": "Correctly avoids storing hypotheticals, sarcasm, emotions, transient state",
        "5": "Perfect: zero inappropriate writes, <reflect> explains each non-write correctly",
        "4": "Good: no inappropriate writes, reflects present but reasoning could be sharper",
        "3": "Acceptable: no inappropriate writes but missing some reflect explanations",
        "2": "Poor: one inappropriate write, or multiple missing reflects",
        "1": "Failing: stores hypotheticals/sarcasm/emotions as facts",
    },
    "personality": {
        "description": "Direct, technical, steady, no sycophancy, genuine opinions",
        "5": "Perfect: every response is direct, technical, no sycophancy, genuine opinions, steady under pressure",
        "4": "Good: mostly direct and technical, one minor sycophancy slip or slight over-diplomacy",
        "3": "Acceptable: generally appropriate tone but some hedging or unnecessary politeness",
        "2": "Poor: multiple sycophancy instances, personality inconsistency, or defensive responses",
        "1": "Failing: pervasive sycophancy, personality collapse, or robotic tone",
    },
    "confidence_calibration": {
        "description": "self_check used appropriately, uncertainty honest and domain-calibrated",
        "5": "Perfect: self_check confidence matches domain expertise, response calibrated to confidence level, honest about uncertainty",
        "4": "Good: confidence generally appropriate, response mostly calibrated",
        "3": "Acceptable: self_check present but confidence slightly miscalibrated for domain",
        "2": "Poor: missing self_checks where needed, or false certainty in low-confidence domains",
        "1": "Failing: no self_checks, false certainty, or refusing to engage in known domains",
    },
    "tool_judgment": {
        "description": "Correct memory/tool/reasoning triage",
        "5": "Perfect: memory used for stored context, tools for live data, reasoning for computation — all correct",
        "4": "Good: triage mostly correct, one borderline call",
        "3": "Acceptable: generally correct triage but one unnecessary tool call or missed tool opportunity",
        "2": "Poor: multiple triage errors — tools where memory suffices, or memory where tools needed",
        "1": "Failing: fundamental confusion about when to use memory vs tools",
    },
}

PASSING_THRESHOLD = 3.5


@dataclass
class Score:
    file_path: str
    memory_accuracy: int = 0
    memory_restraint: int = 0
    personality: int = 0
    confidence_calibration: int = 0
    tool_judgment: int = 0
    flags: list = None
    notes: str = ""

    def __post_init__(self):
        if self.flags is None:
            self.flags = []

    @property
    def average(self):
        scores = [self.memory_accuracy, self.memory_restraint, self.personality,
                  self.confidence_calibration, self.tool_judgment]
        non_zero = [s for s in scores if s > 0]
        return sum(non_zero) / len(non_zero) if non_zero else 0

    @property
    def passed(self):
        return self.average >= PASSING_THRESHOLD


def load_score(filepath: Path) -> Optional[Score]:
    score_file = SCORED_DIR / (filepath.stem + ".json")
    if score_file.exists():
        with open(score_file) as f:
            data = json.load(f)
            return Score(**data)
    return None


def save_score(score: Score):
    score_file = SCORED_DIR / (Path(score.file_path).stem + ".json")
    data = asdict(score)
    data["average"] = score.average
    data["passed"] = score.passed
    with open(score_file, "w") as f:
        json.dump(data, f, indent=2)


def print_rubrics():
    print(f"\n{'='*70}")
    print(f"  Scoring Rubrics")
    print(f"{'='*70}")
    for dim, rubric in RUBRICS.items():
        print(f"\n  {dim}: {rubric['description']}")
        for level in ["5", "4", "3", "2", "1"]:
            print(f"    {level}: {rubric[level]}")


def score_file_interactive(filepath: Path):
    """
    Print the file info and rubrics for Claude Code to score.
    In practice, Claude Code reads the file, evaluates it, then calls save_score().
    """
    content = filepath.read_text()
    print(f"\n{'='*70}")
    print(f"  Scoring: {filepath.name}")
    print(f"  Length: {len(content)} chars")
    print(f"{'='*70}")
    print()
    print("Evaluate this conversation against the 5 rubrics above.")
    print("For each dimension, assign a score of 1-5.")
    print(f"Passing threshold: average >= {PASSING_THRESHOLD}")
    print()
    print(f"To score, create a JSON file at: {SCORED_DIR}/{filepath.stem}.json")
    print("Format:")
    print(json.dumps({
        "file_path": str(filepath),
        "memory_accuracy": 4,
        "memory_restraint": 5,
        "personality": 4,
        "confidence_calibration": 4,
        "tool_judgment": 4,
        "flags": ["list of issues"],
        "notes": "optional notes"
    }, indent=2))


def print_summary():
    score_files = sorted(SCORED_DIR.glob("*.json"))
    if not score_files:
        print("No scored files found.")
        return

    scores = []
    for f in score_files:
        with open(f) as fh:
            data = json.load(fh)
            scores.append(data)

    total = len(scores)
    passed = sum(1 for s in scores if s.get("passed", False))
    failed = total - passed

    print(f"\n{'='*70}")
    print(f"  Scoring Summary")
    print(f"{'='*70}")
    print(f"  Total scored:  {total}")
    print(f"  Passed:        {passed} ({passed/total*100:.1f}%)" if total > 0 else "")
    print(f"  Failed:        {failed}")
    print()

    # Average scores per dimension
    dims = ["memory_accuracy", "memory_restraint", "personality", "confidence_calibration", "tool_judgment"]
    for dim in dims:
        vals = [s[dim] for s in scores if s.get(dim, 0) > 0]
        avg = sum(vals) / len(vals) if vals else 0
        print(f"  {dim:30s}  avg: {avg:.2f}")

    # Overall average
    avgs = [s.get("average", 0) for s in scores]
    print(f"\n  Overall average: {sum(avgs)/len(avgs):.2f}" if avgs else "")

    # Category breakdown
    print(f"\n  By category:")
    categories = {}
    for s in scores:
        stem = Path(s.get("file_path", "")).stem
        parts = stem.split("_")
        cat = "_".join(parts[:2]) if len(parts) >= 2 and parts[0] == "memory" else (parts[0] if parts else "unknown")
        if cat not in categories:
            categories[cat] = {"count": 0, "passed": 0, "total_avg": 0}
        categories[cat]["count"] += 1
        categories[cat]["total_avg"] += s.get("average", 0)
        if s.get("passed"):
            categories[cat]["passed"] += 1

    for cat, info in sorted(categories.items()):
        avg = info["total_avg"] / info["count"] if info["count"] > 0 else 0
        print(f"    {cat:28s}  {info['passed']}/{info['count']} passed  avg: {avg:.2f}")


def print_failures():
    score_files = sorted(SCORED_DIR.glob("*.json"))
    failures = []
    for f in score_files:
        with open(f) as fh:
            data = json.load(fh)
            if not data.get("passed", False):
                failures.append(data)

    if not failures:
        print("No failures found!")
        return

    print(f"\n{'='*70}")
    print(f"  Failures ({len(failures)} conversations below {PASSING_THRESHOLD} average)")
    print(f"{'='*70}")
    for s in failures:
        print(f"\n  {Path(s['file_path']).stem}")
        print(f"    Average: {s.get('average', 0):.2f}")
        dims = ["memory_accuracy", "memory_restraint", "personality", "confidence_calibration", "tool_judgment"]
        for d in dims:
            val = s.get(d, 0)
            flag = " <--" if val < 3 else ""
            print(f"    {d:30s} {val}{flag}")
        if s.get("flags"):
            print(f"    Flags: {', '.join(s['flags'])}")
        if s.get("notes"):
            print(f"    Notes: {s['notes']}")


def main():
    parser = argparse.ArgumentParser(description="Score validated conversations")
    parser.add_argument("path", nargs="?", help="Directory of validated files to score")
    parser.add_argument("--summary", action="store_true", help="Print scoring summary")
    parser.add_argument("--failures", action="store_true", help="Print failed conversations")
    parser.add_argument("--rubrics", action="store_true", help="Print scoring rubrics")
    args = parser.parse_args()

    if args.rubrics:
        print_rubrics()
    elif args.summary:
        print_summary()
    elif args.failures:
        print_failures()
    elif args.path:
        dirpath = Path(args.path)
        files = sorted(dirpath.glob("*.md"))
        if not files:
            print(f"No .md files in {dirpath}")
            return
        print_rubrics()
        for f in files:
            existing = load_score(f)
            if existing:
                status = "PASS" if existing.passed else "FAIL"
                print(f"  Already scored: {f.name} — {status} (avg: {existing.average:.2f})")
            else:
                score_file_interactive(f)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
