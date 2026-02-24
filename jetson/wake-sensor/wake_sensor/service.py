"""Wake sensor service runtime scaffold."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Optional

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
        self._base_wake_threshold = config.wake_threshold
        self._base_vad_threshold = config.vad_threshold
        self._runtime_wake_threshold = config.wake_threshold
        self._runtime_vad_threshold = config.vad_threshold
        self._runtime_keyword = config.keyword
        self._ambient_noise_floor_db = -52.0
        self._ambient_reference_noise_floor_db = -52.0
        self._ambient_auto_adjust_wake = True
        self._ambient_auto_adjust_vad = True

    async def start(self) -> None:
        self._running = True
        await self.client.start()
        logger.info("wake-sensor starting (simulate=%s)", self.config.simulate)
        self._tasks.append(asyncio.create_task(self._config_sync_loop()))
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

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def _coerce_bool(value: object, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    def _apply_control_config(self, control_config: dict) -> None:
        wake = control_config.get("wake_word") if isinstance(control_config.get("wake_word"), dict) else {}
        vad = control_config.get("vad") if isinstance(control_config.get("vad"), dict) else {}
        ambient = control_config.get("ambient") if isinstance(control_config.get("ambient"), dict) else {}

        wake_threshold = wake.get("threshold")
        vad_threshold = vad.get("speech_threshold")
        wake_keyword = wake.get("keyword")
        ambient_noise_floor = ambient.get("noise_floor_db")

        if isinstance(wake_threshold, (int, float)):
            self._base_wake_threshold = float(wake_threshold)
            self._runtime_wake_threshold = float(wake_threshold)
        if isinstance(wake_keyword, str) and wake_keyword.strip():
            self._runtime_keyword = wake_keyword.strip().lower()
        if isinstance(vad_threshold, (int, float)):
            self._base_vad_threshold = float(vad_threshold)
            self._runtime_vad_threshold = float(vad_threshold)
        if isinstance(ambient_noise_floor, (int, float)):
            self._ambient_reference_noise_floor_db = float(ambient_noise_floor)
        self._ambient_auto_adjust_wake = self._coerce_bool(
            ambient.get("auto_adjust_wake_threshold"),
            True,
        )
        self._ambient_auto_adjust_vad = self._coerce_bool(ambient.get("auto_adjust_vad"), True)

    async def _config_sync_loop(self) -> None:
        while self._running:
            try:
                control_config = await self.client.get_config()
                self._apply_control_config(control_config)
            except Exception as exc:
                logger.warning("config sync failed: %s", exc)
            await asyncio.sleep(self.config.config_sync_interval_seconds)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            start = time.perf_counter()
            try:
                await self.client.report_heartbeat(
                    status="healthy",
                    latency_ms=round((time.perf_counter() - start) * 1000.0, 2),
                    details={
                        "simulate": self.config.simulate,
                        "keyword": self._runtime_keyword,
                        "wake_threshold": self._runtime_wake_threshold,
                        "vad_threshold": self._runtime_vad_threshold,
                        "base_wake_threshold": self._base_wake_threshold,
                        "base_vad_threshold": self._base_vad_threshold,
                        "ambient_noise_floor_db": self._ambient_noise_floor_db,
                        "ambient_reference_noise_floor_db": self._ambient_reference_noise_floor_db,
                        "ambient_auto_adjust_wake": self._ambient_auto_adjust_wake,
                        "ambient_auto_adjust_vad": self._ambient_auto_adjust_vad,
                        "training_enabled": self.config.training_enabled,
                        "wake_train_command_configured": bool(self.config.wake_train_command),
                    },
                )
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def _ambient_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.config.ambient_sample_interval_seconds)
            simulated_noise_floor = self._ambient_reference_noise_floor_db + random.uniform(-4.0, 4.0)
            noise_delta = simulated_noise_floor - self._ambient_reference_noise_floor_db

            wake_threshold = self._base_wake_threshold
            vad_threshold = self._base_vad_threshold
            if self._ambient_auto_adjust_wake:
                wake_threshold = self._clamp(self._base_wake_threshold + (noise_delta * 0.006), 0.35, 0.9)
            if self._ambient_auto_adjust_vad:
                vad_threshold = self._clamp(self._base_vad_threshold + (noise_delta * 0.007), 0.2, 0.9)

            self._ambient_noise_floor_db = round(simulated_noise_floor, 2)
            self._runtime_wake_threshold = round(wake_threshold, 3)
            self._runtime_vad_threshold = round(vad_threshold, 3)
            try:
                await self.client.publish_event(
                    VoiceEvent(
                        event_type="playback.state",
                        source=self.config.internal_service,
                        payload={
                            "state": "ambient_profile",
                            "noise_floor_db": self._ambient_noise_floor_db,
                            "noise_delta_db": round(noise_delta, 2),
                            "base_wake_threshold": self._base_wake_threshold,
                            "base_vad_threshold": self._base_vad_threshold,
                            "wake_threshold": self._runtime_wake_threshold,
                            "vad_threshold": self._runtime_vad_threshold,
                            "auto_adjust_wake": self._ambient_auto_adjust_wake,
                            "auto_adjust_vad": self._ambient_auto_adjust_vad,
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

    async def _run_wake_training_command(
        self,
        *,
        job_id: str,
        target_phrase: str,
        dataset_id: str,
        notes: str,
    ) -> dict[str, Any]:
        env = os.environ.copy()
        env.update(
            {
                "VOICE_JOB_ID": job_id,
                "VOICE_TARGET_PHRASE": target_phrase,
                "VOICE_DATASET_ID": dataset_id,
                "VOICE_JOB_NOTES": notes,
                "VOICE_INTERNAL_SERVICE": self.config.internal_service,
            }
        )
        process = await asyncio.create_subprocess_shell(
            self.config.wake_train_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.wake_train_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("wake training command timed out") from exc

        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")
        if process.returncode != 0:
            error_text = stderr.strip() or stdout.strip() or f"exit code {process.returncode}"
            raise RuntimeError(f"wake training command failed: {error_text}")

        parsed = self._extract_json_dict_from_output(stdout) or {}
        parsed["mode"] = "command"
        parsed["stdout"] = stdout.strip()
        parsed["stderr"] = stderr.strip()
        return parsed

    async def _run_wake_word_training(self, job: dict) -> None:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return

        payload = job.get("payload") or {}
        target_phrase = str(payload.get("target_phrase") or self._runtime_keyword).strip().lower()
        target_token = "_".join(target_phrase.split()) or "hey_sara"
        dataset_id = str(payload.get("dataset_id") or "").strip()
        job_notes = str(payload.get("notes") or "").strip()

        try:
            await self.client.update_job_status(
                job_id,
                status="running",
                notes=f"wake-word training started for '{target_phrase}'",
            )

            run_mode = "simulation"
            command_result: Optional[dict[str, Any]] = None
            if self.config.wake_train_command:
                try:
                    command_result = await self._run_wake_training_command(
                        job_id=job_id,
                        target_phrase=target_phrase,
                        dataset_id=dataset_id,
                        notes=job_notes,
                    )
                    run_mode = "command"
                except Exception as exc:
                    if not self.config.wake_train_allow_simulation_fallback:
                        raise
                    logger.warning("wake command failed, falling back to simulation: %s", exc)
                    await self.client.update_job_status(
                        job_id,
                        status="running",
                        notes=f"command failed; using simulation fallback ({exc})",
                    )

            if run_mode == "command" and command_result is not None:
                version = str(command_result.get("version") or f"{target_token}_v{int(time.time())}")
                metrics_payload = command_result.get("metrics")
                metrics = metrics_payload if isinstance(metrics_payload, dict) else {}
                if "simulated" not in metrics:
                    metrics["simulated"] = False
                metrics.setdefault("target_phrase", target_phrase)
                metrics.setdefault("wake_threshold", self._runtime_wake_threshold)
                metrics.setdefault("vad_threshold", self._runtime_vad_threshold)
                auto_activate = self._coerce_bool(
                    command_result.get("auto_activate"),
                    self.config.auto_activate_trained_model,
                )
            else:
                await asyncio.sleep(random.uniform(2.0, 4.0))
                version = f"{target_token}_v{int(time.time())}"
                metrics = {
                    "simulated": True,
                    "target_phrase": target_phrase,
                    "wake_threshold": self._runtime_wake_threshold,
                    "vad_threshold": self._runtime_vad_threshold,
                    "false_accept_rate": round(random.uniform(0.004, 0.018), 4),
                    "miss_rate": round(random.uniform(0.015, 0.045), 4),
                    "eval_samples": random.randint(180, 420),
                }
                auto_activate = self.config.auto_activate_trained_model

            await self.client.register_model_version(
                model_family="wake_word",
                version=version,
                status="candidate",
                metrics=metrics,
                metadata={
                    "job_id": job_id,
                    "source": "wake-sensor",
                    "dataset_id": dataset_id or None,
                    "mode": run_mode,
                },
            )

            notes = f"wake-word model {version} trained ({run_mode})"
            if auto_activate:
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
                    "dataset_id": dataset_id or None,
                    "mode": run_mode,
                    "auto_activated": auto_activate,
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
                    "keyword": self._runtime_keyword,
                    "confidence": round(random.uniform(0.82, 0.97), 3),
                    "threshold": self._runtime_wake_threshold,
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
