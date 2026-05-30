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


VERSION = "0.8.0"


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
        """Heartbeat every tick. Maybe think. Maybe reflect."""
        # 1. heartbeat (cheap, always)
        self.last_tick_summary = self._compose_summary()
        await self._heartbeat(summary=self.last_tick_summary)

        # 2. quiet-period gate
        if self.quiet_until and datetime.now(timezone.utc) < self.quiet_until:
            logger.debug("tick %s — quiet until %s", self.tick_count, self.quiet_until.isoformat())
            return

        # 3. is this a think tick?
        if self.tick_count % max(1, config.ticks_per_think) != 0:
            return

        # 4. think (or reflect, on the Mth think)
        self.think_count += 1
        is_reflect = (self.think_count % max(1, config.thinks_per_reflect) == 0)
        try:
            self.state = "thinking" if not is_reflect else "reflecting"
            if is_reflect:
                logger.info("reflect turn (think #%s)", self.think_count)
                result = await self.mind.reflect()
                self._apply_quiet_directive(result)
            else:
                logger.info("think turn #%s", self.think_count)
                await self.mind.think()
        except Exception:
            logger.exception("cognitive turn failed")
            await self.backend.append_activity(
                kind="error", summary=f"{'reflect' if is_reflect else 'think'} turn raised",
                metadata={"think_count": self.think_count},
            )
        finally:
            self.state = "idle"

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

    async def _heartbeat(self, *, summary: Optional[str]) -> None:
        if not self.backend:
            return
        try:
            await self.backend.heartbeat(
                state=self.state, version=VERSION, pid=self.pid, hostname=self.hostname,
                started_at=self.started_at, last_tick_summary=summary,
            )
        except Exception as e:
            # Heartbeat errors don't kill the daemon — backend may be transiently down.
            logger.warning("heartbeat error (will retry next tick): %s", e)

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
