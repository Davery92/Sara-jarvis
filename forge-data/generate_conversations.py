#!/usr/bin/env python3
"""
Generate training conversations for Project Forge.

This script orchestrates conversation generation. Since Claude Code IS the model,
the actual generation happens when Claude Code reads a seed and writes the conversation
file. This script handles tracking, progress, and batch management.

Usage:
    python generate_conversations.py --batch-size 10 --category memory_write
    python generate_conversations.py --batch-size 10 --all
    python generate_conversations.py --resume
    python generate_conversations.py --status
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
SEEDS_DIR = BASE_DIR / "seeds"
CONVERSATIONS_DIR = BASE_DIR / "conversations"
PROGRESS_FILE = BASE_DIR / "progress.json"
MASTER_PROMPT_FILE = BASE_DIR / "master_prompt.md"


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": {}, "failed": {}, "in_progress": {}, "started_at": datetime.now().isoformat()}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def load_seeds(category=None):
    seeds = {}
    if category:
        files = [SEEDS_DIR / f"{category}.jsonl"]
    else:
        files = sorted(SEEDS_DIR.glob("*.jsonl"))

    for f in files:
        if not f.exists():
            print(f"Warning: {f} not found")
            continue
        cat = f.stem
        seeds[cat] = []
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    seeds[cat].append(json.loads(line))
    return seeds


def get_batch_dir():
    """Get the next batch directory number."""
    existing = sorted(CONVERSATIONS_DIR.glob("batch_*"))
    if not existing:
        return CONVERSATIONS_DIR / "batch_001"
    last_num = int(existing[-1].name.split("_")[1])
    return CONVERSATIONS_DIR / f"batch_{last_num + 1:03d}"


def get_uncompleted_seeds(seeds, progress):
    """Return seeds that haven't been completed yet."""
    uncompleted = {}
    for cat, seed_list in seeds.items():
        completed_ids = set(progress.get("completed", {}).get(cat, []))
        remaining = [s for s in seed_list if s["id"] not in completed_ids]
        if remaining:
            uncompleted[cat] = remaining
    return uncompleted


def select_batch(uncompleted, batch_size, category=None, round_robin=False):
    """Select the next batch of seeds to generate."""
    batch = []

    if category and category in uncompleted:
        batch = uncompleted[category][:batch_size]
    elif round_robin:
        # Round-robin across categories with fewest completed
        cats = sorted(uncompleted.keys(), key=lambda c: len(uncompleted[c]), reverse=True)
        idx = 0
        while len(batch) < batch_size and any(uncompleted.values()):
            cat = cats[idx % len(cats)]
            if uncompleted[cat]:
                batch.append(uncompleted[cat].pop(0))
            idx += 1
            if idx > batch_size * len(cats):
                break
    else:
        # Take from the category with most remaining
        cat = max(uncompleted.keys(), key=lambda c: len(uncompleted[c]))
        batch = uncompleted[cat][:batch_size]

    return batch


def mark_completed(progress, seed):
    cat = seed["category"]
    if cat not in progress["completed"]:
        progress["completed"][cat] = []
    progress["completed"][cat].append(seed["id"])
    save_progress(progress)


def print_status(seeds, progress):
    print(f"\n{'='*70}")
    print(f"  Project Forge — Generation Progress")
    print(f"{'='*70}")
    total_seeds = 0
    total_completed = 0
    for cat in sorted(seeds.keys()):
        count = len(seeds[cat])
        completed = len(progress.get("completed", {}).get(cat, []))
        total_seeds += count
        total_completed += completed
        pct = (completed / count * 100) if count > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {cat:30s} {completed:4d}/{count:4d} [{bar}] {pct:5.1f}%")
    print(f"  {'─'*66}")
    pct = (total_completed / total_seeds * 100) if total_seeds > 0 else 0
    print(f"  {'TOTAL':30s} {total_completed:4d}/{total_seeds:4d}  {pct:.1f}%")
    print(f"  Remaining: {total_seeds - total_completed}")
    if progress.get("started_at"):
        print(f"  Started: {progress['started_at']}")
    print(f"{'='*70}\n")


def print_batch_instructions(batch, batch_dir):
    """Print instructions for Claude Code to generate the conversations."""
    print(f"\n{'='*70}")
    print(f"  Batch ready: {len(batch)} conversations to generate")
    print(f"  Output dir: {batch_dir}")
    print(f"{'='*70}")
    print()
    print("Seeds in this batch:")
    for seed in batch:
        print(f"  - {seed['id']} ({seed['category']}): {seed['setup'][:80]}...")
    print()
    print("Claude Code: For each seed above, generate a full training conversation")
    print("following the master prompt format. Save each to:")
    print(f"  {batch_dir}/{{category}}_{{id}}.md")
    print()
    print("After generating each conversation, run:")
    print(f"  python generate_conversations.py --mark-done <seed_id> <category>")
    print()


def main():
    parser = argparse.ArgumentParser(description="Generate training conversations")
    parser.add_argument("--batch-size", type=int, default=10, help="Conversations per batch")
    parser.add_argument("--category", type=str, help="Specific category to generate")
    parser.add_argument("--all", action="store_true", help="Round-robin across all categories")
    parser.add_argument("--resume", action="store_true", help="Resume from progress.json")
    parser.add_argument("--status", action="store_true", help="Print progress status")
    parser.add_argument("--mark-done", nargs=2, metavar=("SEED_ID", "CATEGORY"), help="Mark a seed as completed")
    parser.add_argument("--next-batch", action="store_true", help="Prepare the next batch")
    args = parser.parse_args()

    progress = load_progress()
    seeds = load_seeds(args.category if args.category else None)

    if args.status:
        all_seeds = load_seeds()
        print_status(all_seeds, progress)
        return

    if args.mark_done:
        seed_id, category = args.mark_done
        if category not in progress.get("completed", {}):
            progress.setdefault("completed", {})[category] = []
        if seed_id not in progress["completed"][category]:
            progress["completed"][category].append(seed_id)
            save_progress(progress)
            print(f"Marked {seed_id} ({category}) as completed.")
        else:
            print(f"{seed_id} ({category}) already marked as completed.")
        return

    # Check master prompt exists
    if not MASTER_PROMPT_FILE.exists():
        print("ERROR: master_prompt.md not found!")
        print("Please paste the master prompt into forge-data/master_prompt.md first.")
        sys.exit(1)

    uncompleted = get_uncompleted_seeds(seeds, progress)
    if not uncompleted:
        print("All seeds completed! Nothing to generate.")
        return

    batch = select_batch(
        uncompleted,
        args.batch_size,
        category=args.category,
        round_robin=args.all
    )

    if not batch:
        print("No seeds available for the selected criteria.")
        return

    batch_dir = get_batch_dir()
    batch_dir.mkdir(parents=True, exist_ok=True)

    # Write batch manifest
    manifest = {
        "batch_dir": str(batch_dir),
        "created_at": datetime.now().isoformat(),
        "seeds": batch
    }
    with open(batch_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print_batch_instructions(batch, batch_dir)


if __name__ == "__main__":
    main()
