"""Wake sensor service runtime scaffold."""

from __future__ import annotations

import asyncio
import logging
import random
import time

from .config import WakeSensorConfig
from .contracts import TurnContext, VoiceEvent
from .control_plane_client import VoiceControlClient

logger = logging.getLogger("wake_sensor")


class WakeSensorService:
    def __init__(self, config: WakeSensorConfig):
        self.config = config
        self.client = VoiceControlClient(config)
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._running = True
        await self.client.start()
        logger.info("wake-sensor starting (simulate=%s)", self.config.simulate)
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._ambient_loop()))
        if self.config.training_enabled:
            self._tasks.append(asyncio.create_task(self._training_loop()))

        if self.config.simulate:
            self._tasks.append(asyncio.create_task(self._simulation_loop()))
        else:
            self._tasks.append(asyncio.create_task(self._live_audio_loop()))

        await asyncio.gather(*self._tasks)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await self.client.stop()

    async def _heartbeat_loop(self) -> None:
        while self._running:
            start = time.perf_counter()
            try:
                await self.client.report_heartbeat(
                    status="healthy",
                    latency_ms=round((time.perf_counter() - start) * 1000.0, 2),
                    details={
                        "simulate": self.config.simulate,
                        "wake_threshold": self.config.wake_threshold,
                        "vad_threshold": self.config.vad_threshold,
                        "training_enabled": self.config.training_enabled,
                    },
                )
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def _ambient_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.config.ambient_sample_interval_seconds)
            simulated_noise_floor = -52.0 + random.uniform(-4.0, 4.0)
            try:
                await self.client.publish_event(
                    VoiceEvent(
                        event_type="playback.state",
                        source=self.config.internal_service,
                        payload={
                            "state": "ambient_profile",
                            "noise_floor_db": round(simulated_noise_floor, 2),
                            "auto_adjust_enabled": True,
                        },
                    )
                )
            except Exception as exc:
                logger.warning("ambient profile publish failed: %s", exc)

    async def _simulation_loop(self) -> None:
        while self._running:
            context = TurnContext(speaker_id="david")
            try:
                await self._emit_simulated_turn(context)
            except Exception as exc:
                logger.warning("simulation turn failed: %s", exc)
            await asyncio.sleep(self.config.simulation_interval_seconds)

    async def _training_loop(self) -> None:
        while self._running:
            try:
                job = await self.client.claim_job(job_types=["train_wake_word"])
                if not job:
                    await asyncio.sleep(self.config.training_poll_interval_seconds)
                    continue
                await self._run_wake_word_training(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("training loop failure: %s", exc)
                await asyncio.sleep(self.config.training_poll_interval_seconds)

    async def _run_wake_word_training(self, job: dict) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return

        payload = job.get("payload") or {}
        target_phrase = str(payload.get("target_phrase") or self.config.keyword).strip().lower()
        target_token = "_".join(target_phrase.split()) or "hey_sara"

        try:
            await self.client.update_job_status(
                job_id,
                status="running",
                notes=f"wake-word training started for '{target_phrase}'",
            )

            # Placeholder duration while the real openWakeWord training pipeline is integrated.
            await asyncio.sleep(random.uniform(2.0, 4.0))
            version = f"{target_token}_v{int(time.time())}"
            metrics = {
                "simulated": True,
                "target_phrase": target_phrase,
                "false_accept_rate": round(random.uniform(0.004, 0.018), 4),
                "miss_rate": round(random.uniform(0.015, 0.045), 4),
                "eval_samples": random.randint(180, 420),
            }

            await self.client.register_model_version(
                model_family="wake_word",
                version=version,
                status="candidate",
                metrics=metrics,
                metadata={"job_id": job_id, "source": "wake-sensor"},
            )

            notes = f"wake-word model {version} trained (candidate)"
            if self.config.auto_activate_trained_model:
                await self.client.activate_model_version(model_family="wake_word", version=version)
                notes = f"wake-word model {version} trained and activated"

            await self.client.update_job_status(
                job_id,
                status="completed",
                notes=notes,
                result={
                    "model_family": "wake_word",
                    "version": version,
                    "metrics": metrics,
                    "auto_activated": self.config.auto_activate_trained_model,
                },
            )
            logger.info("wake-word training job completed: %s -> %s", job_id, version)
        except Exception as exc:
            logger.error("wake-word training job failed: %s", exc)
            await self.client.update_job_status(
                job_id,
                status="failed",
                error=str(exc),
                notes="wake-word training failed",
            )

    async def _emit_simulated_turn(self, context: TurnContext) -> None:
        await self.client.publish_event(
            VoiceEvent(
                event_type="wake.detected",
                source=self.config.internal_service,
                trace_id=context.trace_id,
                payload={
                    "keyword": self.config.keyword,
                    "confidence": round(random.uniform(0.82, 0.97), 3),
                    "threshold": self.config.wake_threshold,
                },
            )
        )

        await self.client.publish_event(
            VoiceEvent(
                event_type="utterance.started",
                source=self.config.internal_service,
                trace_id=context.trace_id,
                payload={"speaker_id": context.speaker_id},
            )
        )

        await asyncio.sleep(0.7)

        await self.client.publish_event(
            VoiceEvent(
                event_type="utterance.ended",
                source=self.config.internal_service,
                trace_id=context.trace_id,
                payload={"duration_ms": random.randint(1200, 2600)},
            )
        )
        logger.info("simulated turn emitted: trace_id=%s", context.trace_id)

    async def _live_audio_loop(self) -> None:
        """
        Placeholder for extracted live audio path.

        Planned wiring:
        - mic capture frames
        - openWakeWord infer
        - VAD segmentation
        - emit wake/utterance events with trace_id
        """
        logger.info("live audio mode selected; capture pipeline not yet wired")
        while self._running:
            await asyncio.sleep(5)
