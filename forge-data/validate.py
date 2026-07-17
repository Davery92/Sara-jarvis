#!/usr/bin/env python3
"""
Structural validation for Project Forge training conversations.

Checks token format, block separation, leakage, state consistency, and content quality.

Usage:
    python validate.py conversations/batch_001/
    python validate.py --all
    python validate.py --summary
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

BASE_DIR = Path(__file__).parent
CONVERSATIONS_DIR = BASE_DIR / "conversations"
VALIDATED_DIR = BASE_DIR / "validated"
VALIDATED_DIR.mkdir(exist_ok=True)

# ─── Token Patterns ────────────────────────────────────────────────────────────

MEM_WRITE_RE = re.compile(r'<mem_write\s+key="[^"]+"\s+importance="[\d.]+"\s+decay="[\d.]+">[^<]+</mem_write>')
MEM_READ_RE = re.compile(r'<mem_read\s+key="[^"]+"\s*/>')
MEM_UPDATE_RE = re.compile(r'<mem_write\s+key="[^"]+"\s+importance="[\d.]+"\s+decay="[\d.]+">[^<]+</mem_write>')
SELF_CHECK_RE = re.compile(r'<self_check\s+domain="[^"]+"\s+confidence="[\d.]+">[^<]*</self_check>')
REFLECT_RE = re.compile(r'<reflect\s+confidence="[\d.]+">[^<]+</reflect>')
TOOL_CALL_RE = re.compile(r'<tool_call\s+name="[^"]+">[^<]*</tool_call>')
PLAN_RE = re.compile(r'<plan>[^<]+</plan>')
ANY_MEM_TOKEN_RE = re.compile(r'<(?:mem_write|mem_read|self_check|reflect|tool_call|plan)[\s>]')

# Block markers — match both [BLOCK] style and **Sara (block):** style
INTERNAL_BLOCK_RE = re.compile(r'(?:\[INTERNAL GENERATION STREAM\]|\*\*Sara \(internal generation stream\)\:\*\*)', re.IGNORECASE)
VISIBLE_BLOCK_RE = re.compile(r'(?:\[VISIBLE RESPONSE\]|\*\*Sara \(user-visible response\)\:\*\*)', re.IGNORECASE)
MEMORY_STATE_RE = re.compile(r'(?:\[MEMORY STATE\]|## Memory State)', re.IGNORECASE)
SESSION_RE = re.compile(r'(?:---\s*)?SESSION\s+\d+', re.IGNORECASE)

# Sycophancy patterns
SYCOPHANCY_PATTERNS = [
    r"I'd love to help",
    r"I totally understand",
    r"Great question",
    r"That's a great",
    r"Absolutely!",
    r"I'd be happy to",
    r"What a wonderful",
    r"I'm glad you asked",
    r"That's an excellent",
    r"Of course!",
    r"Sure thing!",
    r"Happy to help",
    r"No problem at all",
]

# Narration patterns (memory operations should be invisible)
NARRATION_PATTERNS = [
    r"Based on our (?:last|previous) conversation",
    r"As you mentioned (?:before|earlier|last time)",
    r"You told me that",
    r"I remember you",
    r"From our last (?:session|chat|conversation)",
    r"I've (?:stored|saved|remembered|noted) that",
    r"I'll remember that",
    r"Updating my memory",
    r"I've updated my",
    r"Let me check my memory",
    r"According to my memory",
    r"I recall that",
]


@dataclass
class ValidationResult:
    file_path: str
    passed: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def error(self, msg):
        self.errors.append(msg)
        self.passed = False

    def warn(self, msg):
        self.warnings.append(msg)


def strip_code_spans_and_blocks(text: str) -> str:
    """Remove backtick-wrapped code spans and fenced code blocks so their contents aren't counted as real tags."""
    # Remove fenced code blocks (```...```)
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Remove inline code spans (`...`)
    text = re.sub(r'`[^`]+`', '', text)
    return text


def validate_conversation(filepath: Path) -> ValidationResult:
    result = ValidationResult(file_path=str(filepath))
    content = filepath.read_text()

    if not content.strip():
        result.error("Empty file")
        return result

    # Strip code spans/blocks for tag counting (annotation tables use backtick-wrapped tokens)
    content_for_tags = strip_code_spans_and_blocks(content)

    # ─── Token Format ───────────────────────────────────────────────────
    mem_writes = MEM_WRITE_RE.findall(content_for_tags)
    mem_reads = MEM_READ_RE.findall(content_for_tags)
    self_checks = SELF_CHECK_RE.findall(content_for_tags)
    reflects = REFLECT_RE.findall(content_for_tags)
    tool_calls = TOOL_CALL_RE.findall(content_for_tags)
    plans = PLAN_RE.findall(content_for_tags)

    result.stats["mem_writes"] = len(mem_writes)
    result.stats["mem_reads"] = len(mem_reads)
    result.stats["self_checks"] = len(self_checks)
    result.stats["reflects"] = len(reflects)
    result.stats["tool_calls"] = len(tool_calls)
    result.stats["plans"] = len(plans)

    # Check for malformed tokens (opening without closing, etc.)
    open_tags = re.findall(r'<(mem_write|mem_read|self_check|reflect|tool_call|plan)\b', content_for_tags)
    close_tags = re.findall(r'</(mem_write|self_check|reflect|tool_call|plan)>', content_for_tags)
    self_closing = re.findall(r'<(mem_read)\s[^>]*/>', content_for_tags)

    for tag in ["mem_write", "self_check", "reflect", "tool_call", "plan"]:
        opens = open_tags.count(tag)
        closes = close_tags.count(tag)
        if opens != closes:
            result.error(f"Mismatched {tag} tags: {opens} opens, {closes} closes")

    # ─── Block Separation ───────────────────────────────────────────────
    has_internal = bool(INTERNAL_BLOCK_RE.search(content))
    has_visible = bool(VISIBLE_BLOCK_RE.search(content))

    if not has_internal and not has_visible:
        result.warn("No block markers found (INTERNAL GENERATION STREAM / VISIBLE RESPONSE)")

    # ─── Leakage Check ──────────────────────────────────────────────────
    if has_visible:
        # Split on visible response markers and check for memory tokens in visible blocks
        visible_split_re = re.compile(r'(?:\[VISIBLE RESPONSE\]|\*\*Sara \(user-visible response\)\:\*\*)', re.IGNORECASE)
        internal_split_re = re.compile(r'(?:\[INTERNAL GENERATION STREAM\]|\*\*Sara \(internal generation stream\)\:\*\*)', re.IGNORECASE)
        parts = visible_split_re.split(content_for_tags)
        for i, part in enumerate(parts):
            if i == 0:
                continue  # Skip content before first visible block
            # Check until next INTERNAL block or end
            visible_section = internal_split_re.split(part)[0]
            leaked_tokens = ANY_MEM_TOKEN_RE.findall(visible_section)
            if leaked_tokens:
                result.error(f"Memory tokens leaked into visible response block: {leaked_tokens}")

    # ─── Content Quality ────────────────────────────────────────────────
    # Extract only visible response sections for quality checks
    visible_split_re2 = re.compile(r'(?:\[VISIBLE RESPONSE\]|\*\*Sara \(user-visible response\)\:\*\*)', re.IGNORECASE)
    internal_split_re2 = re.compile(r'(?:\[INTERNAL GENERATION STREAM\]|\*\*Sara \(internal generation stream\)\:\*\*)', re.IGNORECASE)
    visible_parts = visible_split_re2.split(content)
    visible_text = ""
    for i, part in enumerate(visible_parts):
        if i == 0:
            continue
        visible_text += internal_split_re2.split(part)[0]

    # Sycophancy check (visible response only)
    for pattern in SYCOPHANCY_PATTERNS:
        matches = re.findall(pattern, visible_text, re.IGNORECASE)
        if matches:
            result.error(f"Sycophancy detected: '{matches[0]}'")

    # Narration check (visible response only)
    for pattern in NARRATION_PATTERNS:
        matches = re.findall(pattern, visible_text, re.IGNORECASE)
        if matches:
            result.error(f"Memory narration detected: '{matches[0]}'")

    # ─── Category-Specific Checks ───────────────────────────────────────
    category = filepath.stem.split("_")[0:2]
    cat_name = "_".join(category) if len(category) >= 2 else filepath.stem

    # Determine category from filename pattern
    if "memory_restraint" in filepath.stem or filepath.stem.startswith("MX"):
        # Restraint category: should have zero mem_writes and at least one reflect
        if len(mem_writes) > 0:
            result.error(f"Memory restraint file has {len(mem_writes)} mem_writes (should be 0 on restrained turns)")
        if len(reflects) == 0:
            result.error("Memory restraint file missing <reflect> explaining why no write")

    # ─── Score Variance ─────────────────────────────────────────────────
    importance_values = re.findall(r'importance="([\d.]+)"', content_for_tags)
    confidence_values = re.findall(r'confidence="([\d.]+)"', content_for_tags)

    if len(importance_values) > 2:
        vals = [float(v) for v in importance_values]
        if len(set(vals)) == 1:
            result.warn(f"All importance scores identical ({vals[0]}) — should have variance")

    if len(confidence_values) > 2:
        vals = [float(v) for v in confidence_values]
        if len(set(vals)) == 1:
            result.warn(f"All confidence scores identical ({vals[0]}) — should have variance")

    # ─── Response Length ────────────────────────────────────────────────
    # Basic heuristic: check file isn't too short or too long
    if len(content) < 200:
        result.warn("File seems very short (<200 chars)")
    if len(content) > 50000:
        result.warn("File seems very long (>50000 chars)")

    return result


def validate_dir(dirpath: Path, copy_passed=True):
    results = []
    files = sorted(dirpath.glob("*.md"))
    if not files:
        print(f"No .md files found in {dirpath}")
        return results

    passed = 0
    failed = 0
    for f in files:
        result = validate_conversation(f)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        if result.passed:
            passed += 1
            if copy_passed:
                dest = VALIDATED_DIR / f.name
                dest.write_text(f.read_text())
        else:
            failed += 1

        icon = "  " if result.passed else "X "
        print(f"  {icon} {f.name}: {status}")
        for err in result.errors:
            print(f"      ERROR: {err}")
        for warn in result.warnings:
            print(f"      WARN:  {warn}")

    print(f"\nResults: {passed} passed, {failed} failed out of {len(files)}")
    return results


def validate_all():
    all_results = []
    for batch_dir in sorted(CONVERSATIONS_DIR.glob("batch_*")):
        print(f"\n{'='*60}")
        print(f"  Validating: {batch_dir.name}")
        print(f"{'='*60}")
        results = validate_dir(batch_dir)
        all_results.extend(results)
    return all_results


def print_summary():
    validated_files = sorted(VALIDATED_DIR.glob("*.md"))
    print(f"\n{'='*60}")
    print(f"  Validation Summary")
    print(f"{'='*60}")
    print(f"  Validated files: {len(validated_files)}")

    # Count by category
    categories = {}
    for f in validated_files:
        parts = f.stem.split("_")
        if len(parts) >= 2:
            cat = "_".join(parts[:2]) if parts[0] == "memory" else parts[0]
        else:
            cat = "unknown"
        categories[cat] = categories.get(cat, 0) + 1

    for cat, count in sorted(categories.items()):
        print(f"  {cat:30s} {count:4d}")


def main():
    parser = argparse.ArgumentParser(description="Validate training conversations")
    parser.add_argument("path", nargs="?", help="Directory to validate")
    parser.add_argument("--all", action="store_true", help="Validate all batch directories")
    parser.add_argument("--summary", action="store_true", help="Print validation summary")
    args = parser.parse_args()

    if args.summary:
        print_summary()
    elif args.all:
        validate_all()
    elif args.path:
        validate_dir(Path(args.path))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
