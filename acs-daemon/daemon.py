"""ACS daemon — Sara's continuous mind, resident in the Sara VM.

selves=1 cutover (ONE_MIND §3.3/§3.4b, 2026-07-30): the daemon keeps systemd
resilience and local hands, but no longer runs its own think()/reflect()
prompt-identity (formerly `mind.py`/`prompt.py`, 705+579 lines). Its tick now
proxies to the backend's kernel: `POST /api/acs/v2/ambient-turn` runs
`kernel.ambient_turn(wake_reason=DAEMON_PROXY)` — the same single mind every
other background wake (deliberation, check-ins, anticipation) already runs
through, instead of a second, parallel self.

Cadence:
  • TICK (every TICK_INTERVAL seconds): cheap, just heartbeat.
  • AMBIENT TURN (every TICKS_PER_THINK ticks, adaptive): one proxied kernel
    turn. The old THINK/REFLECT cadence split is gone — the kernel's
    ambient_turn has one shape regardless of which tick triggered it.

Two behavioral gaps closed in this cutover (see the sign-off package,
ARC_SIGNOFF_PACKAGE_2026_07_29.md, for the full resolution rationale):
  • Gap A: sleep-pressure backoff now reads the kernel's honest `produced`
    bool instead of Mind's old tool_calls/focus_change/notify_david shape.
  • Gap B: the quiet-directive mechanism (`should_quiet_minutes`) is dropped,
    not rebuilt — the kernel's own gates (salience rate-limit, heavy_llm
    lock, delivery-side cooldowns) already cover the same "don't re-trigger
    right after a no-op turn" need.

Kernel-hands (work-order item 11, 2026-07-30 — resolves the gap this
cutover originally flagged): Mind's old think() loop could call 15 tools
inline mid-turn (web_search, write_note, goal/interest CRUD, Proxmox
container provisioning — real, actively-used capability, 1200+ historical
calls). That capability now lives kernel-side instead: `Flag.KERNEL_HANDS`
(default off) adds one optional tool_call per deliberation turn, lane-
routed by trust (backend `app/services/kernel_hands.py`) — read-only and
reversible-write tools execute in-process against the same real backend
implementations Mind used to call over HTTP; irreversible/resource-
creating tools (provision_container, exec_in_container) never auto-
execute, they become a proposal David approves separately. Not a full
multi-round agentic loop like Mind's old MAX_TOOL_ITERATIONS=8 — one
tool call per turn, same "single structured decision" shape as every
other field the kernel already outputs. `mind.py`/`prompt.py`/`llm.py`
are deleted — 1507 lines, zero remaining callers confirmed before
deletion, no flag routes back to them (unlike the sender/context
write-freezes elsewhere in this plan, there's no "flip it back off"
path here; the daemon's own tick physically stopped calling them the
moment this cutover shipped).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timezone
from typing import Optional

from backend_client import BackendClient
from config import config

# Reported to the backend heartbeat as this body's tool capabilities
# (feeds body_capability, not a live call path — mind.py/prompt.py are
# retired as of the KERNEL_HANDS cutover, work-order item 11, 2026-07-30:
# the kernel now executes these same 15 tools itself, lane-routed by trust,
# see backend app/services/kernel_hands.py. destroy_container and
# bump_interest are NOT listed — they were retired outright (zero calls
# ever) rather than migrated. Kept as a local constant, not imported, since
# the daemon and backend are separate deployments with no shared package.
ALLOWED_TOOLS = frozenset({
    "web_search", "web_fetch", "write_note", "search_notes", "search_memory",
    "provision_container", "list_containers", "exec_in_container", "node_status",
    "list_interests", "add_interest", "touch_interest",
    "list_goals", "create_goal", "update_goal",
})

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("acs-daemon")


VERSION = "0.11.0"  # kernel-hands: mind.py/prompt.py/llm.py retired, capability moved kernel-side


def _code_sha() -> str:
    """Deployed git SHA, written to VERSION next to the daemon by deploy/deploy.sh.
    Lets the backend self-check detect daemon-vs-backend drift (Phase 7)."""
    import os
    for path in (os.path.join(os.path.dirname(__file__), "VERSION"),
                 "/opt/acs-daemon/VERSION"):
        try:
            with open(path) as f:
                return f.read().strip().split()[0][:8]
        except Exception:
            continue
    return "unknown"


# Reported to the backend heartbeat as "<semver>+<sha8>" so drift is detectable
# without a schema change to the heartbeat payload.
REPORTED_VERSION = f"{VERSION}+{_code_sha()}"


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
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        logger.info("=" * 60)
        logger.info("Sara ACS daemon — booting")
        logger.info("  version:        %s", VERSION)
        logger.info("  pid:            %s", self.pid)
        logger.info("  hostname:       %s", self.hostname)
        logger.info("  backend:        %s", config.backend_url)
        logger.info("  cognition:      proxied to kernel.ambient_turn (selves=1)")
        logger.info("  tick:           %ss", config.tick_interval_seconds)
        logger.info("  think every:    %s ticks  (~%ss)",
                    config.ticks_per_think, config.tick_interval_seconds * config.ticks_per_think)
        logger.info("=" * 60)

        self.backend = BackendClient(config.backend_url, config.daemon_token)
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

        # 2. not time to think yet? (Gap B, selves=1 cutover: the old
        #    reflection-directive quiet gate is gone — see _adjust_after_turn.
        #    The kernel's own gates — salience_scorer.should_deliberate's rate
        #    limit, the heavy_llm exclusive lock, and delivery-side quiet-
        #    hours/cooldown checks — already cover "don't re-trigger right
        #    after a turn that had nothing to do," so this isn't a second,
        #    redundant gate sitting on top of those.)
        if not candidate and not past_floor:
            return

        # 3. ACS1: skip the think entirely if there's genuinely nothing to think
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

        # 4. one ambient turn, proxied to the kernel (selves=1 — the daemon
        #    keeps systemd resilience and local hands; the kernel is where it
        #    thinks). No more think/reflect split: the kernel's ambient_turn
        #    has one shape regardless of what the old cadence-based split
        #    would have called this tick.
        self.think_count += 1
        try:
            self.state = "thinking"
            logger.info("ambient turn #%s (proxied)", self.think_count)
            result = await self.backend.ambient_turn(world_delta=world_delta)
            self._adjust_after_turn(result)
        except Exception:
            logger.exception("ambient turn failed")
            await self.backend.append_activity(
                kind="error", summary="ambient turn raised",
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
        """ACS2, Gap A (selves=1 cutover): backoff now hinges on ONE field —
        `produced`, the kernel's own honest "did this turn actually do
        anything" signal (notification sent, home action taken, task
        dispatched/proposed) — instead of the old three-field tool_calls/
        focus_change/notify_david check specific to Mind's return shape.
        Same semantic, no information lost. `result` is None on a network/
        HTTP failure (treated as unproductive, same as before)."""
        produced = isinstance(result, dict) and bool(result.get("produced"))
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
        return f"idle (tick #{self.tick_count}, think #{self.think_count})"

    async def _heartbeat(self, *, summary: Optional[str], want_delta: bool = False) -> dict:
        if not self.backend:
            return {}
        try:
            return await self.backend.heartbeat(
                state=self.state, version=REPORTED_VERSION, pid=self.pid, hostname=self.hostname,
                started_at=self.started_at, last_tick_summary=summary,
                want_delta=want_delta, capabilities=sorted(ALLOWED_TOOLS),
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
