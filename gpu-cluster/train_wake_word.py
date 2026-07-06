#!/usr/bin/env python3
"""
Wake-word trainer invoked by wake_word_training_worker.py's WAKE_TRAIN_COMMAND.

Data pipeline (real, verified against the actual dataset layout — see
app/routes/sensory.py's _dataset_sample_dir):
  1. Pull the Wake Word Lab recordings from the Jetson via rsync — positives
     are flat .wav files directly under <dataset_root>/<dataset_id>/,
     negatives (ambient room noise, music/TV, and critically Sara's own TTS
     voice saying non-wake phrases — hard negatives against self-trigger)
     live under <dataset_root>/<dataset_id>/negative/.
  2. Hand off to openWakeWord's own training recipe for the actual model
     fit — this script does NOT reimplement feature extraction/training,
     it prepares data and invokes openWakeWord's maintained pipeline so
     correctness of the ML step comes from their tested code, not a
     hand-rolled reimplementation here.

CAVEAT: openWakeWord's training entry point/config schema has changed
across versions. The `python -m openwakeword.train` invocation below
matches their documented recipe as of this writing — verify against
`pip show openwakeword` on the actual training host before relying on it,
and adjust `_build_training_config`/the module invocation if the installed
version's CLI differs.

Prints exactly one JSON line as its last line of stdout:
  {"onnx_path": "...", "metrics": {"false_accept_rate": ..., "false_reject_rate": ..., "held_out_samples": N}}
wake_word_training_worker.py parses that line and registers the version.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None


def _rsync_dataset(ssh_target: str, remote_root: str, dataset_id: str, local_dir: Path) -> Path:
    """Pull <remote_root>/<dataset_id>/ from the Jetson down to local_dir."""
    remote_path = f"{ssh_target}:{remote_root}/{dataset_id}/"
    local_dataset_dir = local_dir / dataset_id
    local_dataset_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["rsync", "-az", "-e", "ssh -o ConnectTimeout=10", remote_path, str(local_dataset_dir) + "/"],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rsync from Jetson failed: {result.stderr.strip()}")
    return local_dataset_dir


def _count_samples(dataset_dir: Path, subdir: Optional[str]) -> int:
    """Positives are flat files directly in dataset_dir (matching the Wake
    Word Lab's actual recording layout — see app/routes/sensory.py's
    _dataset_sample_dir); negatives live in dataset_dir/negative/."""
    d = dataset_dir / subdir if subdir else dataset_dir
    if not d.exists():
        return 0
    return sum(
        1 for f in d.iterdir()
        if f.is_file() and f.suffix.lower() in (".wav", ".flac", ".mp3")
    )


def _build_training_config(dataset_dir: Path, target_phrase: str, output_dir: Path) -> Path:
    """Write the YAML config openWakeWord's training module expects.

    Schema matches their documented custom-model training recipe: target
    phrase, positive/negative clip directories, and an output path for the
    resulting ONNX model. Confirm field names against the installed
    openwakeword version — this is the one part of the pipeline this
    script can't verify without that dependency actually installed.
    """
    if yaml is None:
        raise RuntimeError("pyyaml not installed — required to write the openWakeWord training config")

    config = {
        "target_phrase": [target_phrase],
        "model_name": target_phrase.replace(" ", "_"),
        "positive_data_dir": str(dataset_dir),
        "negative_data_dir": str(dataset_dir / "negative"),
        "output_dir": str(output_dir),
        # Hard negatives against self-trigger: Sara's own TTS voice saying
        # non-wake phrases should already be included under negative/ by
        # the Wake Word Lab's dataset recording flow.
        #
        # ASSUMPTION: openWakeWord's data loader globs each directory
        # non-recursively, so positive_data_dir (dataset_dir) won't also
        # pick up negative_data_dir's files (a subdirectory of dataset_dir).
        # Verify this against the installed version — if it recurses, move
        # positive clips into their own dataset_dir/positive/ subfolder
        # instead (would need a matching change in
        # app/routes/sensory.py's _dataset_sample_dir).
    }
    config_path = output_dir / "train_config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    return config_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip the actual training invocation; useful for testing the data pipeline alone")
    args = parser.parse_args()

    job_id = os.environ.get("VOICE_JOB_ID", "unknown")
    target_phrase = os.environ.get("WAKE_TARGET_PHRASE", "hey sara")
    dataset_id = os.environ.get("WAKE_DATASET_ID", "")
    ssh_target = os.environ.get("WAKE_DATASET_SSH_TARGET", "david@jetson.local")
    remote_root = os.environ.get("WAKE_DATASET_REMOTE_ROOT", "/home/david/data/wake-word-datasets")

    if not dataset_id:
        print(f"[{job_id}] No dataset_id provided — cannot train", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="wake_train_") as tmp:
        tmp_path = Path(tmp)
        print(f"[{job_id}] Pulling dataset '{dataset_id}' from {ssh_target}:{remote_root}", file=sys.stderr)
        dataset_dir = _rsync_dataset(ssh_target, remote_root, dataset_id, tmp_path)

        positive_count = _count_samples(dataset_dir, None)
        negative_count = _count_samples(dataset_dir, "negative")
        print(f"[{job_id}] positives={positive_count} negatives={negative_count}", file=sys.stderr)

        if positive_count < 10:
            print(f"[{job_id}] Too few positive samples ({positive_count}) — record more in the Wake Word Lab first", file=sys.stderr)
            return 1

        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        if args.dry_run:
            result = {
                "onnx_path": str(output_dir / f"{target_phrase.replace(' ', '_')}.onnx"),
                "metrics": {
                    "false_accept_rate": None,
                    "false_reject_rate": None,
                    "held_out_samples": 0,
                    "dry_run": True,
                    "positive_samples": positive_count,
                    "negative_samples": negative_count,
                },
            }
            print(json.dumps(result))
            return 0

        config_path = _build_training_config(dataset_dir, target_phrase, output_dir)

        print(f"[{job_id}] Invoking openWakeWord training with config {config_path}", file=sys.stderr)
        train_result = subprocess.run(
            [sys.executable, "-m", "openwakeword.train", "--config", str(config_path)],
            capture_output=True, text=True, timeout=3000,
        )
        if train_result.returncode != 0:
            print(train_result.stderr, file=sys.stderr)
            raise RuntimeError("openwakeword.train failed — see stderr above")

        onnx_candidates = list(output_dir.glob("*.onnx"))
        if not onnx_candidates:
            raise RuntimeError("Training completed but no .onnx model was produced in output_dir")

        # openWakeWord's training run typically writes its own metrics
        # summary alongside the model; if present, surface it, otherwise
        # report sample counts only (real numbers, no fabricated FAR/FRR).
        metrics_path = output_dir / "metrics.json"
        metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
        metrics.setdefault("positive_samples", positive_count)
        metrics.setdefault("negative_samples", negative_count)

        result = {"onnx_path": str(onnx_candidates[0]), "metrics": metrics}
        print(json.dumps(result))
        return 0


if __name__ == "__main__":
    sys.exit(main())
