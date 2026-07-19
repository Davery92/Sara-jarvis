"""ACS daemon — Sara's continuous mind, resident in the Sara VM.

Phase 2: ambient self-context. The daemon now thinks.

Cadence:
  • TICK (every TICK_INTERVAL seconds): cheap, just heartbeat.
  • THINK (every TICKS_PER_THINK ticks): one short LLM call. Builds a prompt
    from the recent activity tail + current focus, gets a thought, appends it
    to the activity log. May change focus.
  • REFLECT (every THINKS_PER_REFLECT thinks): one longer LLM call. Honest
    self-assessment — productive / looping / drifting / idle. May change focus
    or request a quiet period.

If a reflection sets `should_quiet_minutes`, thinking is paused for that long.
Heartbeats keep flowing so the backend still sees her alive.

No tools yet; pure cognition. Phase 3 adds notify_david. Phase 4 adds the
inbox + David-queued items.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend_client import BackendClient
from config import config
from llm import LLMClient
from mind import Mind

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("acs-daemon")


VERSION = "0.9.0"  # Brain Alignment ACS1+ACS2: world_delta senses + adaptive sleep pressure


class Daemon:
    def __init__(self) -> None:
        self.running = False
        self.started_at = datetime.now(timezone.utc)
        self.pid = os.getpid()
        self.hostname = socket.gethostname()
        self.state = "boot"
        self.last_tick_summary: Optional[str] = None

        self.tick_count = 0
        self.think_count = 0
        self.quiet_until: Optional[datetime] = None

        # ACS2 (Brain Alignment): adaptive sleep pressure. The interval between
        # thinks doubles after each no-op think (5→10→20→40→80→120 min) and
        # resets the moment the world moves. An event-driven mind, not a poller.
        self._base_think_ticks = max(1, config.ticks_per_think)
        secs = max(1, config.tick_interval_seconds)
        self._max_think_ticks = max(self._base_think_ticks, int(120 * 60 / secs))  # ≤120 min
        self._floor_ticks = max(1, int(120 * 60 / secs))  # guaranteed think ≥ every 2h
        self.think_interval_ticks = self._base_think_ticks
        self.ticks_since_think = 0

        self.backend: Optional[BackendClient] = None
        self.llm: Optional[LLMClient] = None
        self.mind: Optional[Mind] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        logger.info("=" * 60)
        logger.info("Sara ACS daemon — booting")
        logger.info("  version:        %s", VERSION)
        logger.info("  pid:            %s", self.pid)
        logger.info("  hostname:       %s", self.hostname)
        logger.info("  backend:        %s", config.backend_url)
        logger.info("  llm:            %s (%s)", config.llm_url, config.llm_model)
        logger.info("  tick:           %ss", config.tick_interval_seconds)
        logger.info("  think every:    %s ticks  (~%ss)",
                    config.ticks_per_think, config.tick_interval_seconds * config.ticks_per_think)
        logger.info("  reflect every:  %s thinks (~%ss)",
                    config.thinks_per_reflect,
                    config.tick_interval_seconds * config.ticks_per_think * config.thinks_per_reflect)
        logger.info("=" * 60)

        self.backend = BackendClient(config.backend_url, config.daemon_token)
        self.llm = LLMClient(config.llm_url, config.llm_model)
        self.mind = Mind(self.backend, self.llm, started_at=self.started_at)
        self.running = True
        self.state = "idle"

        # Boot heartbeat + boot activity entry.
        await self._heartbeat(summary="boot")
        await self.backend.append_activity(
            kind="boot",
            summary=f"daemon booted (v{VERSION}) on {self.hostname}",
            metadata={"pid": self.pid, "version": VERSION},
        )

        try:
            await self._main_loop()
        finally:
            await self._shutdown()

    async def _main_loop(self) -> None:
        while self.running:
            self.tick_count += 1
            try:
                await self._tick()
            except Exception:
                logger.exception("tick failed")
                self.state = "error"

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=config.tick_interval_seconds,
                )
                break  # stop_event fired
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        """Heartbeat every tick. Maybe think (event-driven, adaptive cadence)."""
        self.ticks_since_think += 1

        # Is this a candidate think tick, or are we past the 2h floor?
        candidate = self.ticks_since_think >= self.think_interval_ticks
        past_floor = self.ticks_since_think >= self._floor_ticks
        want_delta = bool(candidate or past_floor)

        # 1. heartbeat (cheap, always). On a think candidate, also consume the
        #    world_delta — the ONLY channel by which David's world reaches her.
        self.last_tick_summary = self._compose_summary()
        hb = await self._heartbeat(summary=self.last_tick_summary, want_delta=want_delta)
        world_delta = hb.get("world_delta") or [] if isinstance(hb, dict) else []

        # ACS2: any world movement resets sleep pressure to base immediately.
        if world_delta:
            self._reset_backoff()
            candidate = True

        # 2. quiet-period gate (legacy reflection directive — still honored)
        if self.quiet_until and datetime.now(timezone.utc) < self.quiet_until and not world_delta:
            return

        # 3. not time to think yet?
        if not candidate and not past_floor:
            return

        # 4. ACS1: skip the think entirely if there's genuinely nothing to think
        #    about — empty delta, empty inbox, no goals, no interests — unless
        #    we've hit the 2h floor.
        self.ticks_since_think = 0
        if not world_delta and not past_floor:
            if await self._world_is_empty():
                self._backoff()
                logger.info("skipped think — empty world (interval now %s ticks)",
                            self.think_interval_ticks)
                await self.backend.append_activity(
                    kind="idle_skip",
                    summary=f"nothing to think about; sleeping {self.think_interval_ticks} ticks",
                    metadata={"interval_ticks": self.think_interval_ticks},
                )
                return

        # 5. think (or reflect, on the Mth think)
        self.think_count += 1
        is_reflect = (self.think_count % max(1, config.thinks_per_reflect) == 0)
        try:
            self.state = "thinking" if not is_reflect else "reflecting"
            if is_reflect:
                logger.info("reflect turn (think #%s)", self.think_count)
                result = await self.mind.reflect(world_delta=world_delta)
                self._apply_quiet_directive(result)
                # ACS2: an honest "looping" verdict forces sleep pressure up two steps.
                if isinstance(result, dict) and result.get("verdict") == "looping":
                    self._backoff(steps=2)
                else:
                    self._adjust_after_turn(result)
            else:
                logger.info("think turn #%s", self.think_count)
                result = await self.mind.think(world_delta=world_delta)
                self._adjust_after_turn(result)
        except Exception:
            logger.exception("cognitive turn failed")
            await self.backend.append_activity(
                kind="error", summary=f"{'reflect' if is_reflect else 'think'} turn raised",
                metadata={"think_count": self.think_count},
            )
        finally:
            self.state = "idle"

    async def _world_is_empty(self) -> bool:
        """True when there's no inbox work, no goals, and no interests pulling —
        the daemon has nothing to think about this tick."""
        try:
            inbox = await self.backend.list_inbox(limit=5)
            if any((it.get("status") == "queued") for it in inbox):
                return False
            goals = await self.backend.list_goals(status="open")
            if goals:
                return False
            interests = await self.backend.list_interests(limit=3)
            if interests:
                return False
        except Exception as e:
            logger.debug("world_is_empty check failed (assuming not empty): %s", e)
            return False
        return True

    def _adjust_after_turn(self, result: Optional[dict]) -> None:
        """ACS2: a productive think (tool call, focus change, or notify) resets
        sleep pressure; a no-op think increases it."""
        produced = isinstance(result, dict) and (
            result.get("tool_calls") or result.get("focus_change") or result.get("notify_david")
        )
        if produced:
            self._reset_backoff()
        else:
            self._backoff()

    def _reset_backoff(self) -> None:
        self.think_interval_ticks = self._base_think_ticks

    def _backoff(self, steps: int = 1) -> None:
        for _ in range(max(1, steps)):
            self.think_interval_ticks = min(self._max_think_ticks, self.think_interval_ticks * 2)

    def _compose_summary(self) -> str:
        if self.quiet_until and datetime.now(timezone.utc) < self.quiet_until:
            return f"quiet (until {self.quiet_until.strftime('%H:%M')})"
        return f"idle (tick #{self.tick_count}, think #{self.think_count})"

    def _apply_quiet_directive(self, parsed: Optional[dict]) -> None:
        if not isinstance(parsed, dict):
            return
        minutes = parsed.get("should_quiet_minutes")
        if isinstance(minutes, (int, float)) and 1 <= int(minutes) <= 240:
            self.quiet_until = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
            logger.info("reflection asked for quiet period: %sm (until %s)",
                        int(minutes), self.quiet_until.isoformat())

    async def _heartbeat(self, *, summary: Optional[str], want_delta: bool = False) -> dict:
        if not self.backend:
            return {}
        try:
            return await self.backend.heartbeat(
                state=self.state, version=VERSION, pid=self.pid, hostname=self.hostname,
                started_at=self.started_at, last_tick_summary=summary,
                want_delta=want_delta,
            )
        except Exception as e:
            # Heartbeat errors don't kill the daemon — backend may be transiently down.
            logger.warning("heartbeat error (will retry next tick): %s", e)
            return {}

    async def _shutdown(self) -> None:
        logger.info("ACS daemon — shutting down")
        self.state = "sleeping"
        self.running = False
        try:
            if self.backend:
                await self._heartbeat(summary="shutdown")
                await self.backend.append_activity(
                    kind="shutdown", summary="daemon shutting down",
                    metadata={"ticks": self.tick_count, "thinks": self.think_count},
                )
        except Exception:
            pass
        if self.backend:
            await self.backend.aclose()
        if self.llm:
            await self.llm.aclose()
        logger.info("ACS daemon — stopped")

    def request_stop(self) -> None:
        logger.info("stop requested")
        self.running = False
        self._stop_event.set()


async def main() -> None:
    daemon = Daemon()
    loop = asyncio.get_running_loop()

    def handle_signal(signame: str) -> None:
        logger.info("received %s", signame)
        daemon.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal, sig.name)
        except NotImplementedError:
            pass

    try:
        await daemon.start()
    except Exception:
        logger.exception("fatal daemon error")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
