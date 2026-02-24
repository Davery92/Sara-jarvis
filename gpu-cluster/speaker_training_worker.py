"""
Speaker training worker scaffold.

Polls voice-control jobs and executes `train_speakers` jobs with
simulated outputs until the real registry retraining path is wired.
"""

from __future__ import annotations

import asyncio
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
logger = logging.getLogger("speaker_training_worker")


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SpeakerTrainingWorker:
    def __init__(self) -> None:
        self.backend_url = os.getenv("SARA_BACKEND_URL", "http://10.185.1.180:8000").rstrip("/")
        self.internal_service = os.getenv("VOICE_INTERNAL_SERVICE", "speaker-registry")
        self.internal_token = os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", "")
        self.poll_interval_seconds = int(os.getenv("TRAINING_POLL_INTERVAL_SECONDS", "6"))
        self.heartbeat_interval_seconds = int(os.getenv("TRAINING_HEARTBEAT_INTERVAL_SECONDS", "20"))
        self.auto_activate = _as_bool(os.getenv("SPEAKER_TRAINING_AUTO_ACTIVATE", "false"), False)
        self.version_prefix = os.getenv("SPEAKER_MODEL_VERSION_PREFIX", "speaker_profiles_v")

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
                        "details": {"job_types": ["train_speakers"], "auto_activate": self.auto_activate},
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

    async def _run_training_job(self, job: Dict[str, Any]) -> None:
        assert self.http is not None
        job_id = str(job.get("job_id") or "")
        payload = job.get("payload") or {}
        speaker_ids = [str(item).strip().lower() for item in payload.get("speaker_ids", []) if str(item).strip()]

        if not job_id:
            return

        try:
            running_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/jobs/{job_id}/status",
                json={
                    "status": "running",
                    "notes": f"speaker training started for {len(speaker_ids)} speaker(s)",
                },
                headers=self.headers,
            )
            running_response.raise_for_status()

            await asyncio.sleep(random.uniform(2.0, 5.0))

            version = f"{self.version_prefix}{int(time.time())}"
            metrics = {
                "simulated": True,
                "speaker_count": len(speaker_ids),
                "equal_error_rate": round(random.uniform(0.03, 0.08), 4),
                "validation_samples": random.randint(40, 180),
            }

            register_response = await self.http.post(
                f"{self.backend_url}/api/voice-control/models/speakers/versions",
                json={
                    "version": version,
                    "status": "candidate",
                    "metrics": metrics,
                    "metadata": {"job_id": job_id, "speaker_ids": speaker_ids},
                },
                headers=self.headers,
            )
            register_response.raise_for_status()

            notes = f"speaker model {version} trained (candidate)"
            if self.auto_activate:
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
                        "speaker_ids": speaker_ids,
                        "auto_activated": self.auto_activate,
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
