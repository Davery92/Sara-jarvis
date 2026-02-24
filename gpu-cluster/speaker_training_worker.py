"""
Speaker training worker scaffold.

Polls voice-control jobs and executes `train_speakers` jobs.

Execution modes:
1) Command mode (`SPEAKER_TRAIN_COMMAND`) for custom trainer pipelines
2) Enrollment mode using speaker sample directories + enrollment service
3) Simulation fallback (optional)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("speaker_training_worker")


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


class SpeakerTrainingWorker:
    def __init__(self) -> None:
        self.backend_url = os.getenv("SARA_BACKEND_URL", "http://10.185.1.180:8000").rstrip("/")
        self.internal_service = os.getenv("VOICE_INTERNAL_SERVICE", "speaker-registry")
        self.internal_token = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "")
        self.poll_interval_seconds = int(os.getenv("TRAINING_POLL_INTERVAL_SECONDS", "6"))
        self.heartbeat_interval_seconds = int(os.getenv("TRAINING_HEARTBEAT_INTERVAL_SECONDS", "20"))
        self.auto_activate = _as_bool(os.getenv("SPEAKER_TRAINING_AUTO_ACTIVATE", "false"), False)
        self.version_prefix = os.getenv("SPEAKER_MODEL_VERSION_PREFIX", "speaker_profiles_v")
        self.enrollment_url = os.getenv("SPEAKER_ENROLLMENT_URL", "http://speaker-enrollment:8003").rstrip("/")
        self.dataset_root = Path(os.getenv("SPEAKER_TRAIN_DATASET_ROOT", "/data/enrollment-samples"))
        self.training_command = os.getenv("SPEAKER_TRAIN_COMMAND", "").strip()
        self.training_timeout_seconds = int(os.getenv("SPEAKER_TRAIN_TIMEOUT_SECONDS", "1800"))
        self.allow_simulation_fallback = _as_bool(
            os.getenv("SPEAKER_TRAIN_ALLOW_SIMULATION_FALLBACK", "true"),
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
            "speaker training worker started (service=%s backend=%s)",
            self.internal_service,
            self.backend_url,
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
                        "version": "speaker-training-scaffold-v1",
                        "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
                        "details": {
                            "job_types": ["train_speakers"],
                            "auto_activate": self.auto_activate,
                            "command_configured": bool(self.training_command),
                            "dataset_root": str(self.dataset_root),
                            "enrollment_url": self.enrollment_url,
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
                    json={"job_types": ["train_speakers"]},
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
    def _extract_json_dict_from_output(output: str) -> Optional[dict[str, Any]]:
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
        dataset_id: str,
        speaker_ids: list[str],
    ) -> dict[str, Any]:
        env = os.environ.copy()
        env.update(
            {
                "VOICE_JOB_ID": job_id,
                "VOICE_DATASET_ID": dataset_id,
                "VOICE_SPEAKER_IDS": ",".join(speaker_ids),
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
            raise RuntimeError("speaker training command timed out") from exc

        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")
        if process.returncode != 0:
            error_text = stderr.strip() or stdout.strip() or f"exit code {process.returncode}"
            raise RuntimeError(f"speaker training command failed: {error_text}")

        parsed = self._extract_json_dict_from_output(stdout) or {}
        parsed["mode"] = "command"
        return parsed

    def _dataset_bases(self, dataset_id: str) -> list[Path]:
        if dataset_id:
            return [self.dataset_root / dataset_id, self.dataset_root]
        return [self.dataset_root]

    def _discover_speaker_ids(self, requested: list[str], dataset_id: str) -> list[str]:
        if requested:
            return requested
        discovered: list[str] = []
        for base in self._dataset_bases(dataset_id):
            if not base.exists() or not base.is_dir():
                continue
            for item in sorted(base.iterdir()):
                if item.is_dir():
                    discovered.append(item.name.lower())
            if discovered:
                return sorted(set(discovered))
        return []

    def _speaker_samples(self, speaker_id: str, dataset_id: str) -> list[Path]:
        for base in self._dataset_bases(dataset_id):
            candidate = base / speaker_id
            if not candidate.exists() or not candidate.is_dir():
                continue
            samples = sorted(
                path
                for path in candidate.iterdir()
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
            )
            if samples:
                return samples
        return []

    async def _enroll_speaker(self, speaker_id: str, sample_paths: list[Path]) -> dict[str, Any]:
        assert self.http is not None
        files = []
        for idx, path in enumerate(sample_paths):
            with open(path, "rb") as file_handle:
                content = file_handle.read()
            files.append(("files", (f"sample_{idx}{path.suffix.lower()}", content, "audio/wav")))

        response = await self.http.post(
            f"{self.enrollment_url}/enroll/{speaker_id}",
            files=files,
            data={"display_name": speaker_id.replace("_", " ").title()},
        )
        response.raise_for_status()
        return response.json()

    async def _run_training_job(self, job: Dict[str, Any]) -> None:
        assert self.http is not None
        job_id = str(job.get("job_id") or "")
        payload = job.get("payload") or {}
        requested_speaker_ids = [
            str(item).strip().lower()
            for item in payload.get("speaker_ids", [])
            if str(item).strip()
        ]
        dataset_id = str(payload.get("dataset_id") or "").strip()

        if not job_id:
            return

        try:
            speaker_ids = self._discover_speaker_ids(requested_speaker_ids, dataset_id)
            running_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "running",
                    "notes": (
                        f"speaker training started for {len(speaker_ids)} speaker(s)"
                        + (f" dataset={dataset_id}" if dataset_id else "")
                    ),
                },
                headers=self.headers,
            )
            running_response.raise_for_status()

            run_mode = "enrollment"
            command_result: Optional[dict[str, Any]] = None
            enrolled_speakers: list[str] = []
            total_samples = 0

            if self.training_command:
                try:
                    command_result = await self._run_training_command(
                        job_id=job_id,
                        dataset_id=dataset_id,
                        speaker_ids=speaker_ids,
                    )
                    run_mode = "command"
                except Exception as exc:
                    if not self.allow_simulation_fallback:
                        raise
                    logger.warning("speaker command failed, falling back: %s", exc)
                    await self.http.post(
                        f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                        json={
                            "status": "running",
                            "notes": f"command failed; fallback path active ({exc})",
                        },
                        headers=self.headers,
                    )

            if run_mode == "command" and command_result is not None:
                version = str(command_result.get("version") or f"{self.version_prefix}{int(time.time())}")
                speakers_payload = command_result.get("enrolled_speakers")
                if isinstance(speakers_payload, list):
                    enrolled_speakers = [str(item) for item in speakers_payload if str(item).strip()]
                else:
                    enrolled_speakers = speaker_ids
                metrics_payload = command_result.get("metrics")
                metrics = metrics_payload if isinstance(metrics_payload, dict) else {}
                if "simulated" not in metrics:
                    metrics["simulated"] = False
                metrics.setdefault("speaker_count", len(enrolled_speakers))
                metrics.setdefault("dataset_id", dataset_id or None)
                auto_activate = _as_bool(
                    str(command_result.get("auto_activate", self.auto_activate)),
                    self.auto_activate,
                )
            else:
                for speaker_id in speaker_ids:
                    samples = self._speaker_samples(speaker_id, dataset_id)
                    if not samples:
                        continue
                    await self._enroll_speaker(speaker_id, samples)
                    enrolled_speakers.append(speaker_id)
                    total_samples += len(samples)

                if enrolled_speakers:
                    version = f"{self.version_prefix}{int(time.time())}"
                    metrics = {
                        "simulated": False,
                        "speaker_count": len(enrolled_speakers),
                        "total_samples": total_samples,
                        "dataset_id": dataset_id or None,
                    }
                    auto_activate = self.auto_activate
                else:
                    if not self.allow_simulation_fallback:
                        raise RuntimeError("no speaker samples discovered for requested training job")
                    run_mode = "simulation"
                    await asyncio.sleep(random.uniform(2.0, 5.0))
                    version = f"{self.version_prefix}{int(time.time())}"
                    metrics = {
                        "simulated": True,
                        "speaker_count": len(speaker_ids),
                        "equal_error_rate": round(random.uniform(0.03, 0.08), 4),
                        "validation_samples": random.randint(40, 180),
                        "dataset_id": dataset_id or None,
                    }
                    enrolled_speakers = speaker_ids
                    auto_activate = self.auto_activate

            register_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/models/speakers/versions",
                json={
                    "version": version,
                    "status": "candidate",
                    "metrics": metrics,
                    "metadata": {
                        "job_id": job_id,
                        "speaker_ids": enrolled_speakers,
                        "dataset_id": dataset_id or None,
                        "mode": run_mode,
                    },
                },
                headers=self.headers,
            )
            register_response.raise_for_status()

            notes = f"speaker model {version} trained ({run_mode})"
            if auto_activate:
                activate_response = await self.http.post(
                    f"{self.backend_url}/api/voice-control/models/speakers/activate-internal",
                    json={"version": version},
                    headers=self.headers,
                )
                activate_response.raise_for_status()
                notes = f"speaker model {version} trained and activated"

            complete_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "completed",
                    "notes": notes,
                    "result": {
                        "model_family": "speakers",
                        "version": version,
                        "metrics": metrics,
                        "speaker_ids": enrolled_speakers,
                        "dataset_id": dataset_id or None,
                        "mode": run_mode,
                        "auto_activated": auto_activate,
                    },
                },
                headers=self.headers,
            )
            complete_response.raise_for_status()
            logger.info("speaker training job completed: %s -> %s", job_id, version)

        except Exception as exc:
            logger.error("speaker training job failed: %s", exc)
            failed_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "failed",
                    "notes": "speaker training failed",
                    "error": str(exc),
                },
                headers=self.headers,
            )
            failed_response.raise_for_status()


async def main() -> None:
    worker = SpeakerTrainingWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
