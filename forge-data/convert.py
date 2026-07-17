#!/usr/bin/env python3
"""
Convert scored conversations to QLoRA-ready JSONL training format.

Usage:
    python convert.py scored/ --output final/
    python convert.py --stats
    python convert.py --validate-jsonl
"""

import argparse
import json
import re
import random
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
SCORED_DIR = BASE_DIR / "scored"
VALIDATED_DIR = BASE_DIR / "validated"
FINAL_DIR = BASE_DIR / "final"
FINAL_DIR.mkdir(exist_ok=True)

PASSING_THRESHOLD = 3.5
SPLIT_RATIOS = {"train": 0.90, "val": 0.02, "test": 0.04, "reserve": 0.04}

random.seed(42)

# ─── Parsing ───────────────────────────────────────────────────────────────────

SESSION_BOUNDARY_RE = re.compile(r'(?:---\s*)?SESSION\s+(\d+)', re.IGNORECASE)
MEMORY_STATE_START_RE = re.compile(r'\[MEMORY STATE\]', re.IGNORECASE)
MEMORY_STATE_END_RE = re.compile(r'\[/MEMORY STATE\]', re.IGNORECASE)
INTERNAL_RE = re.compile(r'\[INTERNAL GENERATION STREAM\]', re.IGNORECASE)
VISIBLE_RE = re.compile(r'\[VISIBLE RESPONSE\]', re.IGNORECASE)
USER_RE = re.compile(r'^(?:David|User|DAVID|USER)\s*:', re.MULTILINE)
ASSISTANT_RE = re.compile(r'^(?:Sara|Assistant|SARA|ASSISTANT)\s*:', re.MULTILINE)

SYSTEM_PROMPT_TEMPLATE = """You are Sara, a cognitive AI assistant with persistent memory for David. You have native memory operations that execute as part of your generation stream. You are direct, technical, and steady. You don't narrate your memory operations in your visible responses.

{memory_state}"""


def parse_sessions(content: str) -> list:
    """Parse a conversation file into sessions."""
    session_splits = SESSION_BOUNDARY_RE.split(content)

    if len(session_splits) <= 1:
        # No session markers — treat entire content as one session
        return [{"number": 1, "content": content}]

    sessions = []
    # session_splits: [pre-content, "1", session1_content, "2", session2_content, ...]
    for i in range(1, len(session_splits), 2):
        num = int(session_splits[i])
        sess_content = session_splits[i + 1] if i + 1 < len(session_splits) else ""
        sessions.append({"number": num, "content": sess_content})

    return sessions


def extract_memory_state(content: str) -> str:
    """Extract the memory state block from session content."""
    start = MEMORY_STATE_START_RE.search(content)
    end = MEMORY_STATE_END_RE.search(content)
    if start and end:
        return content[start.start():end.end()]
    return "[MEMORY STATE]\n(empty)\n[/MEMORY STATE]"


def parse_turns(session_content: str) -> list:
    """Parse a session into user/assistant turns."""
    turns = []

    # Find all user and assistant markers
    user_matches = list(USER_RE.finditer(session_content))
    assistant_matches = list(ASSISTANT_RE.finditer(session_content))

    # Combine and sort by position
    all_markers = [(m.start(), m.end(), "user") for m in user_matches]
    all_markers += [(m.start(), m.end(), "assistant") for m in assistant_matches]
    all_markers.sort(key=lambda x: x[0])

    for i, (start, end, role) in enumerate(all_markers):
        # Content goes until the next marker or end of string
        next_start = all_markers[i + 1][0] if i + 1 < len(all_markers) else len(session_content)
        content = session_content[end:next_start].strip()

        if role == "assistant":
            # For assistant turns, combine internal stream + visible response
            # The training format includes memory tokens as part of the assistant message
            turns.append({"role": "assistant", "content": content})
        else:
            turns.append({"role": "user", "content": content})

    return turns


def format_assistant_turn(content: str) -> str:
    """
    Format an assistant turn for training: memory tokens + visible response.
    Internal stream tokens become part of the assistant message.
    Visible response follows after a blank line.
    """
    # Extract internal stream tokens
    internal_match = INTERNAL_RE.search(content)
    visible_match = VISIBLE_RE.search(content)

    if internal_match and visible_match:
        internal_content = content[internal_match.end():visible_match.start()].strip()
        visible_content = content[visible_match.end():].strip()
        if internal_content:
            return f"{internal_content}\n\n{visible_content}"
        return visible_content

    return content


def conversation_to_examples(filepath: Path) -> list:
    """Convert a conversation file to training examples (one per session)."""
    content = filepath.read_text()
    sessions = parse_sessions(content)
    examples = []

    for session in sessions:
        memory_state = extract_memory_state(session["content"])
        turns = parse_turns(session["content"])

        if not turns:
            continue

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(memory_state=memory_state)}
        ]

        for turn in turns:
            if turn["role"] == "assistant":
                messages.append({"role": "assistant", "content": format_assistant_turn(turn["content"])})
            else:
                messages.append(turn)

        # Only include if we have at least one user + one assistant turn
        user_turns = [m for m in messages if m["role"] == "user"]
        asst_turns = [m for m in messages if m["role"] == "assistant"]
        if user_turns and asst_turns:
            examples.append({"messages": messages})

    return examples


def get_passing_scores() -> list:
    """Get all scored files that passed the threshold."""
    passing = []
    for score_file in sorted(SCORED_DIR.glob("*.json")):
        with open(score_file) as f:
            data = json.load(f)
            if data.get("average", 0) >= PASSING_THRESHOLD:
                passing.append(data)
    return passing


def split_examples(examples: list) -> dict:
    """Stratified split into train/val/test/reserve."""
    random.shuffle(examples)
    n = len(examples)

    splits = {}
    idx = 0
    for split_name, ratio in SPLIT_RATIOS.items():
        count = max(1, int(n * ratio)) if split_name != "train" else 0
        splits[split_name] = count

    # Train gets the remainder
    splits["train"] = n - sum(splits.values())

    result = {}
    for split_name in ["train", "val", "test", "reserve"]:
        count = splits[split_name]
        result[split_name] = examples[idx:idx + count]
        idx += count

    return result


def write_jsonl(examples: list, filepath: Path):
    with open(filepath, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")


def validate_jsonl():
    """Validate the generated JSONL files."""
    for split_name in ["train", "val", "test", "reserve"]:
        filepath = FINAL_DIR / f"{split_name}.jsonl"
        if not filepath.exists():
            print(f"  {split_name}.jsonl: NOT FOUND")
            continue

        count = 0
        errors = 0
        with open(filepath) as f:
            for i, line in enumerate(f, 1):
                try:
                    data = json.loads(line)
                    if "messages" not in data:
                        print(f"    Line {i}: missing 'messages' key")
                        errors += 1
                    else:
                        roles = [m["role"] for m in data["messages"]]
                        if roles[0] != "system":
                            print(f"    Line {i}: first message not system")
                            errors += 1
                        if "user" not in roles:
                            print(f"    Line {i}: no user messages")
                            errors += 1
                        if "assistant" not in roles:
                            print(f"    Line {i}: no assistant messages")
                            errors += 1
                    count += 1
                except json.JSONDecodeError:
                    print(f"    Line {i}: invalid JSON")
                    errors += 1

        status = "OK" if errors == 0 else f"{errors} ERRORS"
        print(f"  {split_name}.jsonl: {count} examples — {status}")


def print_stats():
    """Print statistics about the final dataset."""
    print(f"\n{'='*70}")
    print(f"  Final Dataset Statistics")
    print(f"{'='*70}")

    total = 0
    for split_name in ["train", "val", "test", "reserve"]:
        filepath = FINAL_DIR / f"{split_name}.jsonl"
        if not filepath.exists():
            print(f"  {split_name:10s}: not generated yet")
            continue

        count = sum(1 for _ in open(filepath))
        total += count

        # Sample lengths
        lengths = []
        with open(filepath) as f:
            for line in f:
                data = json.loads(line)
                total_chars = sum(len(m["content"]) for m in data["messages"])
                lengths.append(total_chars)

        avg_len = sum(lengths) / len(lengths) if lengths else 0
        print(f"  {split_name:10s}: {count:6d} examples  (avg {avg_len:.0f} chars)")

    print(f"  {'─'*50}")
    print(f"  {'total':10s}: {total:6d} examples")


def main():
    parser = argparse.ArgumentParser(description="Convert to training JSONL")
    parser.add_argument("path", nargs="?", help="Directory of scored files")
    parser.add_argument("--output", default="final/", help="Output directory")
    parser.add_argument("--stats", action="store_true", help="Print dataset statistics")
    parser.add_argument("--validate-jsonl", action="store_true", help="Validate JSONL format")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.validate_jsonl:
        validate_jsonl()
        return

    if not args.path:
        parser.print_help()
        return

    # Get passing conversations
    passing = get_passing_scores()
    if not passing:
        print("No scored conversations passing threshold found.")
        return

    print(f"Found {len(passing)} passing conversations")

    # Convert each to training examples
    all_examples = []
    for score_data in passing:
        stem = Path(score_data["file_path"]).stem
        conv_file = VALIDATED_DIR / f"{stem}.md"
        if not conv_file.exists():
            print(f"  Warning: {conv_file} not found, skipping")
            continue

        examples = conversation_to_examples(conv_file)
        all_examples.extend(examples)
        print(f"  {stem}: {len(examples)} training examples")

    print(f"\nTotal training examples: {len(all_examples)}")

    # Split
    splits = split_examples(all_examples)
    output_dir = Path(args.output) if not Path(args.output).is_absolute() else Path(args.output)
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for split_name, examples in splits.items():
        outfile = output_dir / f"{split_name}.jsonl"
        write_jsonl(examples, outfile)
        print(f"  {split_name}.jsonl: {len(examples)} examples")

    print(f"\nDone! Files written to {output_dir}")


if __name__ == "__main__":
    main()
