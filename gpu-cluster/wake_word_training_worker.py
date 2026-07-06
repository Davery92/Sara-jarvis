"""
Wake-word training worker (Desktop Jarvis Overhaul B3).

Polls voice-control jobs and executes `train_wake_word` jobs. Mirrors
speaker_training_worker.py's shape exactly (heartbeat + job-claim loop +
pluggable command + simulation fallback) so both training pipelines share
one operational pattern.

Execution modes:
1) Command mode (`WAKE_TRAIN_COMMAND`) — invokes an external trainer script
   (see train_wake_word.py in this directory for the openWakeWord recipe).
2) Simulation fallback (optional) — for exercising the job-queue/registry
   plumbing without a real dataset or GPU run.

Dataset location: Wake Word Lab recordings are synced to the JETSON (not
this GPU host) — see app/routes/sensory.py's _sync_wake_sample_to_jetson.
The training command is responsible for pulling the dataset from the
Jetson (scp/rsync) before training; WAKE_TRAIN_DATASET_SSH_TARGET is passed
through as an env var for that purpose.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Dict, Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("wake_word_training_worker")


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class WakeWordTrainingWorker:
    def __init__(self) -> None:
        self.backend_url = os.getenv("SARA_BACKEND_URL", "http://10.185.1.180:8000").rstrip("/")
        self.internal_service = os.getenv("VOICE_INTERNAL_SERVICE", "wake-word-training")
        self.internal_token = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "")
        self.poll_interval_seconds = int(os.getenv("TRAINING_POLL_INTERVAL_SECONDS", "6"))
        self.heartbeat_interval_seconds = int(os.getenv("TRAINING_HEARTBEAT_INTERVAL_SECONDS", "20"))
        self.auto_activate = _as_bool(os.getenv("WAKE_TRAINING_AUTO_ACTIVATE", "false"), False)
        self.version_prefix = os.getenv("WAKE_MODEL_VERSION_PREFIX", "hey_sara_v")
        self.training_command = os.getenv("WAKE_TRAIN_COMMAND", "").strip()
        self.training_timeout_seconds = int(os.getenv("WAKE_TRAIN_TIMEOUT_SECONDS", "3600"))
        self.dataset_ssh_target = os.getenv("WAKE_TRAIN_DATASET_SSH_TARGET", "david@jetson.local")
        self.jetson_dataset_root = os.getenv("JETSON_WAKE_DATASET_ROOT", "/home/david/data/wake-word-datasets")
        self.allow_simulation_fallback = _as_bool(
            os.getenv("WAKE_TRAIN_ALLOW_SIMULATION_FALLBACK", "true"),
            True,
        )

        self.http: Optional[httpx.AsyncClient] = None
        self.running = False

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "X-Internal-Service": self.internal_service,
            "X-Internal-Token": self.internal_token,
        }

    async def start(self) -> None:
        self.http = httpx.AsyncClient(timeout=30.0)
        self.running = True
        logger.info(
            "wake word training worker started (service=%s backend=%s command_configured=%s)",
            self.internal_service,
            self.backend_url,
            bool(self.training_command),
        )
        await asyncio.gather(self._heartbeat_loop(), self._job_loop())

    async def stop(self) -> None:
        self.running = False
        if self.http:
            await self.http.aclose()
            self.http = None

    async def _heartbeat_loop(self) -> None:
        assert self.http is not None
        while self.running:
            start = time.perf_counter()
            try:
                response = await self.http.post(
                    f"{self.backend_url}/api/voice-control/services/{self.internal_service}/heartbeat",
                    json={
                        "status": "healthy",
                        "version": "wake-word-training-v1",
                        "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
                        "details": {
                            "job_types": ["train_wake_word"],
                            "auto_activate": self.auto_activate,
                            "command_configured": bool(self.training_command),
                            "dataset_ssh_target": self.dataset_ssh_target,
                        },
                    },
                    headers=self.headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            await asyncio.sleep(self.heartbeat_interval_seconds)

    async def _job_loop(self) -> None:
        assert self.http is not None
        while self.running:
            try:
                claim_response = await self.http.post(
                    f"{self.backend_url}/api/voice-control/jobs/claim",
                    json={"job_types": ["train_wake_word"]},
                    headers=self.headers,
                )
                claim_response.raise_for_status()
                payload = claim_response.json()
                job = payload.get("job")
                if not job:
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue
                await self._run_training_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("job loop failure: %s", exc)
                await asyncio.sleep(self.poll_interval_seconds)

    @staticmethod
    def _extract_json_dict_from_output(output: str) -> Optional[Dict[str, Any]]:
        for line in reversed(output.splitlines()):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    async def _run_training_command(
        self,
        *,
        job_id: str,
        target_phrase: str,
        dataset_id: str,
    ) -> Dict[str, Any]:
        """Invoke the external trainer. Expected to print a single JSON line
        like {"onnx_path": "...", "metrics": {"far": 0.01, "frr": 0.04}} as
        its last stdout line — same "last JSON line wins" convention as the
        speaker trainer."""
        env = os.environ.copy()
        env.update(
            {
                "VOICE_JOB_ID": job_id,
                "WAKE_TARGET_PHRASE": target_phrase,
                "WAKE_DATASET_ID": dataset_id,
                "WAKE_DATASET_SSH_TARGET": self.dataset_ssh_target,
                "WAKE_DATASET_REMOTE_ROOT": self.jetson_dataset_root,
                "VOICE_INTERNAL_SERVICE": self.internal_service,
            }
        )
        process = await asyncio.create_subprocess_shell(
            self.training_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(),
                timeout=self.training_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("wake word training command timed out") from exc

        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")
        if process.returncode != 0:
            error_text = stderr.strip() or stdout.strip() or f"exit code {process.returncode}"
            raise RuntimeError(f"wake word training command failed: {error_text}")

        parsed = self._extract_json_dict_from_output(stdout)
        if not parsed:
            raise RuntimeError("wake word training command produced no parseable JSON result line")
        return parsed

    async def _run_training_job(self, job: Dict[str, Any]) -> None:
        assert self.http is not None
        job_id = str(job.get("job_id") or "")
        payload = job.get("payload") or {}
        target_phrase = str(payload.get("target_phrase") or "hey sara")
        dataset_id = str(payload.get("dataset_id") or "").strip()

        if not job_id:
            return

        try:
            running_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "running",
                    "notes": f"wake word training started for '{target_phrase}'"
                    + (f" dataset={dataset_id}" if dataset_id else ""),
                },
                headers=self.headers,
            )
            running_response.raise_for_status()

            run_mode = "command"
            metrics: Dict[str, Any] = {}

            if self.training_command:
                try:
                    result = await self._run_training_command(
                        job_id=job_id, target_phrase=target_phrase, dataset_id=dataset_id,
                    )
                    metrics = result.get("metrics") or {}
                    metrics.setdefault("simulated", False)
                except Exception as exc:
                    if not self.allow_simulation_fallback:
                        raise
                    logger.warning("wake word command failed, falling back to simulation: %s", exc)
                    run_mode = "simulation"
            else:
                run_mode = "simulation"

            if run_mode == "simulation":
                if not self.allow_simulation_fallback:
                    raise RuntimeError("no WAKE_TRAIN_COMMAND configured and simulation fallback disabled")
                await asyncio.sleep(random.uniform(3.0, 8.0))
                metrics = {
                    "simulated": True,
                    "false_accept_rate": round(random.uniform(0.005, 0.02), 4),
                    "false_reject_rate": round(random.uniform(0.02, 0.08), 4),
                    "held_out_samples": random.randint(60, 240),
                }

            version = f"{self.version_prefix}{int(time.time())}"
            metrics.setdefault("target_phrase", target_phrase)
            metrics.setdefault("dataset_id", dataset_id or None)

            register_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/models/wake_word/versions",
                json={
                    "version": version,
                    "status": "candidate",
                    "metrics": metrics,
                    "metadata": {
                        "job_id": job_id,
                        "target_phrase": target_phrase,
                        "dataset_id": dataset_id or None,
                        "mode": run_mode,
                    },
                },
                headers=self.headers,
            )
            register_response.raise_for_status()

            notes = f"wake word model {version} trained ({run_mode})"
            if self.auto_activate:
                activate_response = await self.http.post(
                    f"{self.backend_url}/api/voice-control/models/wake_word/activate-internal",
                    json={"version": version},
                    headers=self.headers,
                )
                activate_response.raise_for_status()
                notes = f"wake word model {version} trained and activated"

            complete_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "completed",
                    "notes": notes,
                    "result": {
                        "model_family": "wake_word",
                        "version": version,
                        "metrics": metrics,
                        "mode": run_mode,
                        "auto_activated": self.auto_activate,
                    },
                },
                headers=self.headers,
            )
            complete_response.raise_for_status()
            logger.info("wake word training job completed: %s -> %s", job_id, version)

        except Exception as exc:
            logger.error("wake word training job failed: %s", exc)
            failed_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "failed",
                    "notes": "wake word training failed",
                    "error": str(exc),
                },
                headers=self.headers,
            )
            failed_response.raise_for_status()


async def main() -> None:
    worker = WakeWordTrainingWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
