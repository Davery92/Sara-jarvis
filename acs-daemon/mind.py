"""Sara's cognitive turns: think() and reflect().

A turn:
  1. Pulls ambient self-context (recent activity, focus, inbox, recall).
  2. Builds a prompt and calls the LLM.
  3. If the LLM returns tool_calls with finish=false, executes them, appends
     `tool_call` and `tool_result` activity entries, and re-asks the LLM with
     the results inline. Cap at MAX_TOOL_ITERATIONS to prevent runaway.
  4. When finish=true (or cap hit), applies side effects (thought/reflection,
     focus change, inbox action, notify) and returns.

If anything goes wrong (LLM unreachable, malformed JSON, tool failures), an
`error` activity entry is logged and the loop survives.
"""
from __future__ import annotations

import difflib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from backend_client import BackendClient
from llm import LLMClient, parse_json_loose
from prompt import build_reflect_prompt, build_think_prompt, humanize_duration

logger = logging.getLogger("acs-daemon.mind")


# Hard caps — protect against runaway behavior.
MAX_TOOL_ITERATIONS = 8         # max LLM round-trips chained per turn
MAX_TOOL_CALLS_PER_BATCH = 4    # max parallel tool calls in one LLM response
# ACS4 (Brain Alignment — one mind, two speeds): the slow mind must NOT grow
# its own senses. It may reason, research, and act on artifacts, but it must
# NEVER gain a tool that reads a live feed the backend already ingests (email,
# Home Assistant, calendar, presence, health). Those reach her only through the
# heartbeat's world_delta (ACS1). Adding such a tool here recreates the
# "second brain fighting the first" that UNLEASHED Phase A eliminated. If you
# add a tool below, it must be inert cognition, research, or her own goals/
# interests — never a poller of David's world.
ALLOWED_TOOLS = {
    # research / knowledge
    "web_search", "web_fetch", "write_note", "search_notes", "search_memory",
    # sandboxes on sara-node (Proxmox LXC)
    "provision_container", "list_containers", "exec_in_container",
    "destroy_container", "node_status",
    # standing interests — threads she chooses to keep tugging at
    "list_interests", "add_interest", "bump_interest", "touch_interest",
    # goals — persistent intent; the thing idle thinks are for
    "list_goals", "create_goal", "update_goal",
}


class Mind:
    def __init__(self, backend: BackendClient, llm: LLMClient, *, started_at: datetime) -> None:
        self.backend = backend
        self.llm = llm
        self.started_at = started_at

    # ── think ──
    async def think(self, world_delta: Optional[list[str]] = None) -> Optional[dict]:
        """Run one short thinking turn. Returns the parsed action dict or None."""
        activity = await self.backend.list_activity(limit=20)
        focus = await self.backend.get_focus()
        inbox = await self.backend.list_inbox(limit=20)
        interests = await self.backend.list_interests(limit=8)
        goals = await self.backend.list_goals(status="open")
        recall = await self._gather_recall(focus, inbox)
        boot_age = humanize_duration((datetime.now(timezone.utc) - self.started_at).total_seconds())

        system, user = build_think_prompt(
            activity=activity, focus=focus, inbox=inbox, interests=interests,
            goals=goals, recall=recall, boot_age=boot_age, world_delta=world_delta,
        )
        logger.debug("think prompt assembled (%d activity, %d inbox, %d interests, %d goals, %d recall)",
                     len(activity), len(inbox), len(interests), len(goals), len(recall))

        parsed = await self._run_chained_turn(
            system=system, user=user, turn="think",
            max_tokens=900, temperature=0.7, interests=interests,
        )
        if parsed is None:
            return None

        # Final-turn side effects — content fields plus the action set.
        thought = (parsed.get("thought") or "").strip()
        summary = (parsed.get("summary") or thought.split(".")[0] or "thought").strip()[:200]
        await self.backend.append_activity(
            kind="thought", summary=summary, body=thought or None,
            metadata={
                "turn": "think", "json_parsed": True,
                "recalled": self._recalled_meta(recall),
            },
        )

        # Inbox action runs first; it may change focus, which the explicit
        # focus_change can then override if she also returned one.
        await self._apply_inbox_action(parsed.get("inbox_action"), inbox=inbox, turn="think")
        await self._apply_focus_change(parsed.get("focus_change"), turn="think")
        await self._apply_notify(parsed.get("notify_david"), turn="think")
        return parsed

    # ── reflect ──
    async def reflect(self, world_delta: Optional[list[str]] = None) -> Optional[dict]:
        """Run one reflection turn. Returns parsed action dict or None."""
        activity = await self.backend.list_activity(limit=30)
        focus = await self.backend.get_focus()
        inbox = await self.backend.list_inbox(limit=20)
        interests = await self.backend.list_interests(limit=8)
        goals = await self.backend.list_goals(status="open")
        recall = await self._gather_recall(focus, inbox)
        boot_age = humanize_duration((datetime.now(timezone.utc) - self.started_at).total_seconds())

        system, user = build_reflect_prompt(
            activity=activity, focus=focus, inbox=inbox, interests=interests,
            goals=goals, recall=recall, boot_age=boot_age, world_delta=world_delta,
        )
        logger.debug("reflect prompt assembled (%d activity, %d inbox, %d interests, %d goals, %d recall)",
                     len(activity), len(inbox), len(interests), len(goals), len(recall))

        parsed = await self._run_chained_turn(
            system=system, user=user, turn="reflect",
            max_tokens=1200, temperature=0.5, interests=interests,
        )
        if parsed is None:
            return None

        reflection = (parsed.get("reflection") or "").strip()
        verdict = parsed.get("verdict")
        summary = (parsed.get("summary") or reflection.split(".")[0] or "reflection").strip()[:200]

        # SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25 §5.6/§8.2: prompt-level
        # instructions not to narrate "I'm still being still" twice weren't
        # enough in practice — reflection history kept repeating "going
        # quiet" verdicts every few hours. This is the code-level backstop:
        # an idle/looping verdict whose text is substantially the same as
        # the last reflection collapses into one compact marker instead of
        # a fresh fully-narrated entry, so quiet periods stay quiet in the
        # activity log too, not just in cadence (ACS2 already handles that).
        if verdict in {"idle", "looping"}:
            prior = await self.backend.list_activity(limit=1, kind="reflection")
            prior_text = (prior[0].get("body") or prior[0].get("summary") or "").strip() if prior else ""
            if self._is_repetitive_narration(reflection or summary, prior_text):
                summary = f"still {verdict} — nothing new since last reflection"
                reflection = None

        await self.backend.append_activity(
            kind="reflection", summary=summary, body=reflection or None,
            tags=[verdict] if verdict in {"productive", "looping", "drifting", "idle"} else [],
            metadata={
                "turn": "reflect", "json_parsed": True, "verdict": verdict,
                "should_quiet_minutes": parsed.get("should_quiet_minutes"),
                "recalled": self._recalled_meta(recall),
            },
        )

        await self._apply_inbox_action(parsed.get("inbox_action"), inbox=inbox, turn="reflect")
        await self._apply_focus_change(parsed.get("focus_change"), turn="reflect")
        await self._apply_notify(parsed.get("notify_david"), turn="reflect")
        return parsed

    # ── chained tool execution ──
    async def _run_chained_turn(
        self, *, system: str, user: str, turn: str,
        max_tokens: int, temperature: float, interests: list[dict] | None = None,
    ) -> Optional[dict]:
        """Loop: call LLM → if tool_calls + finish=false, run them, re-ask, repeat.

        Returns the final parsed dict (with finish=true or after cap), or
        None if everything failed.
        """
        current_user = user
        last_parsed: Optional[dict] = None
        for iteration in range(MAX_TOOL_ITERATIONS + 1):
            raw = await self.llm.chat(
                system=system, user=current_user,
                max_tokens=max_tokens, temperature=temperature,
            )
            if raw is None:
                await self.backend.append_activity(
                    kind="error", summary=f"{turn}: LLM unreachable (iter {iteration})",
                    metadata={"turn": turn, "iteration": iteration},
                )
                return last_parsed  # may be None, may be a partial earlier turn

            parsed = parse_json_loose(raw)
            if not parsed or not isinstance(parsed, dict):
                # Couldn't parse JSON — treat the raw text as the final thought/reflection.
                logger.info("%s iter %s: JSON parse fell through; using raw", turn, iteration)
                fallback_kind = "reflection" if turn == "reflect" else "thought"
                await self.backend.append_activity(
                    kind=fallback_kind,
                    summary=(raw.strip().splitlines()[0] if raw.strip() else "(empty)")[:200],
                    body=raw.strip(),
                    metadata={"turn": turn, "json_parsed": False, "iteration": iteration},
                )
                return None  # we already wrote the entry; caller skips its own write

            last_parsed = parsed
            tool_calls = parsed.get("tool_calls") or []
            finish = bool(parsed.get("finish", True))

            # If she's done OR not requesting tools OR we hit the cap → exit loop.
            if finish or not tool_calls or iteration >= MAX_TOOL_ITERATIONS:
                if not finish and iteration >= MAX_TOOL_ITERATIONS:
                    # Force-finish on cap; log so we can see runaway tendencies.
                    logger.warning("%s: hit MAX_TOOL_ITERATIONS=%s, force-finishing",
                                   turn, MAX_TOOL_ITERATIONS)
                    await self.backend.append_activity(
                        kind="error",
                        summary=f"{turn}: hit tool-call cap ({MAX_TOOL_ITERATIONS}); forced finish",
                        metadata={"turn": turn, "iteration": iteration},
                    )
                return parsed

            # Execute the requested tool calls.
            tool_calls = tool_calls[:MAX_TOOL_CALLS_PER_BATCH]
            results = await self._execute_tool_calls(tool_calls, turn=turn,
                                                     iteration=iteration, interests=interests)
            # Re-ask the LLM with the results appended to the user prompt.
            current_user = self._build_followup_prompt(user, parsed, results, iteration)

        return last_parsed

    # Tools that do real, consequential VM work — provisioning compute,
    # running arbitrary commands — as opposed to research/notes/interest
    # bookkeeping. SARA_PROACTIVENESS_IMPLEMENTATION_PLAN_2026_07_25 P5.2:
    # "no self-originated focused work starts without an approval record."
    _SUBSTANTIVE_VM_TOOLS = {"provision_container", "exec_in_container"}

    @staticmethod
    def _resolve_interest(short_or_full_id: str, interests: list[dict] | None) -> Optional[dict]:
        sid = (short_or_full_id or "").strip()
        if len(sid) < 4:
            return None
        for it in (interests or []):
            full = str(it.get("id", ""))
            if full.startswith(sid) or full == sid:
                return it
        return None

    @classmethod
    def _approved_interest_for_call(
        cls, args: dict, interests: list[dict] | None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Resolve the specific interest a VM tool call claims to be doing
        work for, and validate it's actually approved. Returns
        (interest, error) — exactly one is non-None.

        Binding matters: a single approved interest must not blanket-unlock
        VM tools for every OTHER interest the daemon happens to be turning
        over that tick (SARA_PROACTIVENESS critique 2026-07-25 §4 — "approval
        for one investigation can authorize unrelated self-originated work").
        """
        short_id = (args.get("interest_id") or "").strip()
        if not short_id:
            return None, ("missing interest_id — pass the id of the approved/active "
                           "interest this work is for (see list_interests)")
        interest = cls._resolve_interest(short_id, interests)
        if interest is None:
            return None, f"interest_id {short_id!r} not found in your current interests"
        if interest.get("status") not in ("approved", "active"):
            return None, (f"interest {interest.get('display_name', short_id)!r} has status "
                           f"{interest.get('status')!r}, not approved/active — propose it and "
                           "wait for David's decision first")
        return interest, None

    async def _execute_tool_calls(
        self, calls: list[dict], *, turn: str, iteration: int,
        interests: list[dict] | None = None,
    ) -> list[dict]:
        """Run a batch of tool calls, log call+result activity, return results."""
        results: list[dict] = []
        for raw_call in calls:
            if not isinstance(raw_call, dict):
                continue
            name = (raw_call.get("name") or "").strip()
            args = raw_call.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            if name not in ALLOWED_TOOLS:
                logger.warning("%s: unknown tool %r", turn, name)
                await self.backend.append_activity(
                    kind="error", summary=f"unknown tool: {name!r}"[:200],
                    metadata={"turn": turn, "iteration": iteration, "tool": name},
                )
                results.append({"name": name, "args": args, "error": "unknown tool"})
                continue

            bound_interest = None
            if name in self._SUBSTANTIVE_VM_TOOLS:
                bound_interest, gate_error = self._approved_interest_for_call(args, interests)
                if gate_error:
                    logger.info("%s: blocked %r — %s", turn, name, gate_error)
                    await self.backend.append_activity(
                        kind="error",
                        summary=f"{name} blocked: {gate_error}"[:200],
                        body=(
                            "VM tool calls must name the specific approved/active interest "
                            "they're doing work for via interest_id (see list_interests). "
                            "Proposed interests need David's approval (POST "
                            ".../interests/{id}/approve) first — one approved interest does "
                            "not authorize work on any other."
                        ),
                        metadata={"turn": turn, "iteration": iteration, "tool": name},
                    )
                    results.append({"name": name, "args": args, "error": gate_error})
                    continue

            # Log the call attempt. bound_interest_id records which specific
            # interest authorized a VM tool call, for auditability — None for
            # non-VM tools.
            bound_interest_id = bound_interest.get("id") if bound_interest else None
            args_summary = self._summarize_args(name, args)
            await self.backend.append_activity(
                kind="tool_call",
                summary=f"{name}({args_summary})"[:200],
                body=json.dumps({"name": name, "args": args}, indent=2)[:4000],
                metadata={"turn": turn, "iteration": iteration, "tool": name,
                          "bound_interest_id": bound_interest_id},
            )

            # Run it.
            result = await self.backend.call_tool(name, args)
            error = result.get("_error")

            # Log the result. Body holds the full payload (truncated) so she
            # can recall it later via search_notes/search_memory or by reading
            # her log directly.
            result_summary = self._summarize_result(name, result, error=error)
            body_text = self._render_result_body(result, error=error)
            await self.backend.append_activity(
                kind="tool_result",
                summary=f"{name} → {result_summary}"[:200],
                body=body_text[:8000],
                tags=["error"] if error else [],
                metadata={
                    "turn": turn, "iteration": iteration, "tool": name,
                    "error": error, "bound_interest_id": bound_interest_id,
                },
            )

            results.append({"name": name, "args": args, "result": result, "error": error})
        return results

    @staticmethod
    def _summarize_args(name: str, args: dict) -> str:
        if name in {"web_search", "search_notes", "search_memory"}:
            return f"query={args.get('query', '')!r}"[:120]
        if name == "web_fetch":
            return f"url={args.get('url', '')!r}"[:120]
        if name == "write_note":
            return f"title={args.get('title', '')!r}"[:120]
        if name == "provision_container":
            return (f"preset={args.get('preset', 'research')!r}, purpose={args.get('purpose', '')!r}, "
                    f"interest_id={args.get('interest_id', '')!r}")[:160]
        if name == "exec_in_container":
            cmd = (args.get("command") or "")
            return f"vmid={args.get('vmid')}, cmd={cmd!r}, interest_id={args.get('interest_id', '')!r}"[:160]
        if name == "destroy_container":
            return f"vmid={args.get('vmid')}"
        if name in {"list_containers", "node_status", "list_interests", "list_goals"}:
            return ""
        if name == "create_goal":
            return f"title={args.get('title', '')!r}"[:120]
        if name == "update_goal":
            short = (args.get("id") or "")[:8]
            bits = [f"id={short}"]
            if args.get("status"):
                bits.append(f"status={args['status']}")
            if args.get("progress_note"):
                bits.append(f"note={args['progress_note']!r}")
            return ", ".join(bits)[:120]
        if name == "add_interest":
            return f"name={args.get('display_name', '')!r}"[:120]
        if name in {"bump_interest", "touch_interest"}:
            short = (args.get("id") or "")[:8]
            delta = args.get("delta")
            return f"id={short}" + (f", delta={delta}" if delta is not None else "")
        return ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])[:120]

    @staticmethod
    def _summarize_result(name: str, result: dict, *, error: Optional[str]) -> str:
        if error:
            return f"ERROR: {error}"[:160]
        if name == "web_search":
            return f"{result.get('count', 0)} results"
        if name == "web_fetch":
            length = len(result.get("content") or "")
            trunc = " (truncated)" if result.get("truncated") else ""
            return f"{length} chars{trunc}"
        if name == "write_note":
            return f"wrote note id={(result.get('id') or '')[:8]}"
        if name == "search_notes":
            return f"{len(result) if isinstance(result, list) else 0} notes"
        if name == "search_memory":
            return f"{len(result) if isinstance(result, list) else 0} episodes"
        if name == "provision_container":
            return f"vmid={result.get('vmid')} ip={result.get('ip')} preset={result.get('preset')}"
        if name == "list_containers":
            return f"{result.get('count', 0)} active"
        if name == "exec_in_container":
            err = result.get("error")
            if err:
                return f"exec error: {err[:120]}"
            out_len = len(result.get("stdout") or "")
            trunc = " (truncated)" if result.get("truncated") else ""
            return f"vmid={result.get('vmid')} → {out_len} chars{trunc}"
        if name == "destroy_container":
            return f"vmid={result.get('vmid')} destroyed={result.get('destroyed')}"
        if name == "node_status":
            return (f"cpu={result.get('cpu_pct', 0):.0%} "
                    f"mem={result.get('memory_used_mb')}/{result.get('memory_total_mb')}MB "
                    f"managed={result.get('managed_active')}")
        if name == "list_interests":
            return f"{result.get('count', 0)} interests"
        if name == "add_interest":
            if result.get("blocked"):
                return (f"REJECTED — David has blocked {result.get('display_name', '')!r}. "
                        "Drop this thread for good; do not rephrase or re-add it.")[:160]
            verb = "merged into" if result.get("merged") else "added"
            return f"{verb} {result.get('display_name', '')!r} (weight={result.get('weight'):.1f})"[:160]
        if name in {"bump_interest", "touch_interest"}:
            return f"{result.get('display_name', '?')!r} weight={result.get('weight', 0):.1f}"[:160]
        return "ok"

    @staticmethod
    def _render_result_body(result: Any, *, error: Optional[str]) -> str:
        if error:
            return f"ERROR: {error}"
        try:
            return json.dumps(result, indent=2, default=str)
        except Exception:
            return str(result)[:8000]

    @staticmethod
    def _build_followup_prompt(
        original_user: str, prior_parsed: dict, results: list[dict], iteration: int,
    ) -> str:
        """Append tool results to the user message for the next LLM call."""
        # Render results compactly so the LLM has them inline. Truncate per-result
        # body so the prompt doesn't blow up.
        lines = ["", "## Tool results from your previous step", ""]
        for r in results:
            name = r.get("name", "?")
            args = r.get("args", {})
            err = r.get("error")
            lines.append(f"### {name}({Mind._summarize_args(name, args)})")
            if err:
                lines.append(f"  ERROR: {err}")
                continue
            payload = r.get("result", {})
            rendered = Mind._render_result_body(payload, error=None)
            if len(rendered) > 3500:
                rendered = rendered[:3500] + "\n[... truncated ...]"
            lines.append(rendered)
            lines.append("")

        lines.extend([
            "---",
            "Now use these results to either run more tool_calls or finish the turn.",
            "If you have what you need, set tool_calls=[] and finish=true and emit your",
            "final thought/focus/notify/inbox_action.",
        ])
        return original_user + "\n" + "\n".join(lines)

    # ── recall ──
    async def _gather_recall(
        self, focus: dict, inbox: list[dict],
    ) -> list[dict]:
        """Pull semantically related prior activity for the topic Sara is about
        to think about. Caps at 5 entries total; merges focus + top inbox query
        and dedupes by id. No-op if there's no obvious topic in play.
        """
        topics: list[str] = []
        if isinstance(focus, dict) and (focus.get("topic") or "").strip():
            topics.append(focus["topic"])
        # Include the most-urgent queued item too, so pickups have prior context.
        for item in inbox:
            if item.get("status") == "queued":
                prompt = (item.get("prompt") or "").strip()
                if prompt:
                    topics.append(prompt)
                    break  # one is enough; keeps recall tight
        if not topics:
            return []

        seen: set[str] = set()
        merged: list[dict] = []
        for topic in topics:
            results = await self.backend.list_related_activity(
                topic=topic, limit=4,
                exclude_recent_minutes=15, min_similarity=0.55,
            )
            for r in results:
                rid = r.get("id")
                if rid and rid not in seen:
                    seen.add(rid)
                    merged.append(r)
        # Sort by similarity desc, cap at 5.
        merged.sort(key=lambda r: r.get("similarity", 0.0), reverse=True)
        return merged[:5]

    # Below this ratio, two reflections are "about the same nothing" rather
    # than genuinely new content — calibrated loose on purpose: paraphrased
    # idle narration ("still quiet, nothing pulling at me" vs "remaining
    # still, no thread worth pulling on") should still collapse.
    _NARRATION_SIMILARITY_THRESHOLD = 0.55

    @staticmethod
    def _is_repetitive_narration(new_text: str, prior_text: str) -> bool:
        if not new_text or not prior_text:
            return False
        ratio = difflib.SequenceMatcher(None, new_text.lower(), prior_text.lower()).ratio()
        return ratio >= Mind._NARRATION_SIMILARITY_THRESHOLD

    @staticmethod
    def _recalled_meta(recall: list[dict]) -> list[dict]:
        """Compact form of what she pulled from memory this turn, stored on the
        thought/reflection so David's presence view can show "I remembered…".
        Top 2 only, trimmed — metadata should stay light.
        """
        out: list[dict] = []
        for r in (recall or [])[:2]:
            summary = (r.get("summary") or "").strip()
            if not summary:
                continue
            out.append({
                "summary": summary[:160],
                "created_at": r.get("created_at"),
                "kind": r.get("kind"),
                "similarity": r.get("similarity"),
            })
        return out

    # ── inbox side-effect ──
    async def _apply_inbox_action(
        self, action: Optional[dict], *, inbox: list[dict], turn: str,
    ) -> None:
        """Pickup / complete / dismiss an inbox item.

        The id Sara sees in her prompt is the first 8 characters of the UUID.
        We resolve it back to the full UUID against the inbox list we just
        fetched (so we never trust her with raw row IDs).
        """
        if not isinstance(action, dict):
            return
        kind = (action.get("action") or "").strip().lower()
        short_id = (action.get("id") or "").strip()
        if kind not in {"pickup", "complete", "dismiss"} or not short_id:
            return

        full_id = self._resolve_inbox_id(short_id, inbox)
        if not full_id:
            await self.backend.append_activity(
                kind="error",
                summary=f"inbox_action: unknown id '{short_id}' (action={kind})",
                metadata={"turn": turn, "action": kind, "short_id": short_id},
            )
            return

        # Find the item for prompt text in activity entries.
        item = next((it for it in inbox if str(it.get("id", "")).startswith(short_id)), {})
        prompt_text = (item.get("prompt") or "")[:200]

        if kind == "pickup":
            row = await self.backend.inbox_pickup(full_id)
            if row is None:
                await self.backend.append_activity(
                    kind="error", summary=f"inbox_pickup failed for {short_id}",
                    metadata={"turn": turn, "id": full_id},
                )
                return
            await self.backend.append_activity(
                kind="inbox_pickup",
                summary=f"picked up: {prompt_text}"[:200],
                body=item.get("prompt"),
                metadata={"turn": turn, "id": full_id, "urgency": item.get("urgency")},
            )
            # Pickup auto-sets focus to the item so subsequent ticks keep working.
            await self.backend.set_focus(
                topic=prompt_text,
                why=f"picked up from inbox (urgency={item.get('urgency') or 'normal'})",
            )

        elif kind == "complete":
            summary = (action.get("summary") or "").strip()
            if not summary:
                await self.backend.append_activity(
                    kind="error",
                    summary=f"inbox_complete missing summary for {short_id}",
                    metadata={"turn": turn, "id": full_id},
                )
                return
            row = await self.backend.inbox_complete(full_id, summary=summary[:4000])
            if row is None:
                return
            await self.backend.append_activity(
                kind="inbox_complete",
                summary=f"completed: {prompt_text}"[:200],
                body=summary,
                metadata={"turn": turn, "id": full_id},
            )
            # If the focus was the item we just completed, clear it.
            current_focus = await self.backend.get_focus()
            current_topic = ((current_focus or {}).get("topic") or "")
            if prompt_text and current_topic.startswith(prompt_text[:50]):
                await self.backend.clear_focus()

        elif kind == "dismiss":
            reason = (action.get("reason") or "").strip()
            if not reason:
                await self.backend.append_activity(
                    kind="error",
                    summary=f"inbox_dismiss missing reason for {short_id}",
                    metadata={"turn": turn, "id": full_id},
                )
                return
            row = await self.backend.inbox_dismiss(full_id, reason=reason[:2000])
            if row is None:
                return
            await self.backend.append_activity(
                kind="inbox_dismiss",
                summary=f"dismissed: {prompt_text}"[:200],
                body=reason,
                metadata={"turn": turn, "id": full_id},
            )

    @staticmethod
    def _resolve_inbox_id(short_id: str, inbox: list[dict]) -> Optional[str]:
        if len(short_id) < 4:
            return None
        for it in inbox:
            full = str(it.get("id", ""))
            if full.startswith(short_id):
                return full
        return None

    # ── notify side-effect ──
    async def _apply_notify(self, notify: Optional[dict], *, turn: str) -> None:
        """If the model asked to notify David, fire it and log to activity.

        The activity entry is what makes this honest: she'll see "you notified
        David 12m ago about X" in her next ambient context, so she can't
        unintentionally spam him while believing she'd been quiet.
        """
        if not isinstance(notify, dict):
            return
        title = (notify.get("title") or "").strip()
        body = (notify.get("body") or "").strip()
        if not title or not body:
            return
        priority = notify.get("priority") or "normal"
        if priority not in {"low", "normal", "important", "high", "urgent", "critical"}:
            priority = "normal"
        why = (notify.get("why") or "").strip() or None
        note_id = (notify.get("note_id") or "").strip() or None

        title = title[:200]
        body = body[:2000]

        result = await self.backend.notify_david(
            title=title, body=body, priority=priority, why=why, note_id=note_id,
        )
        delivered = bool(result.get("delivered"))
        reason = result.get("reason")

        summary = f"{'pinged' if delivered else 'TRIED to ping'} David: {title}"[:200]
        await self.backend.append_activity(
            kind="notify_david",
            summary=summary,
            body=f"Title: {title}\n\nBody: {body}" + (f"\n\nWhy: {why}" if why else ""),
            tags=[priority] + (["delivered"] if delivered else ["failed"]),
            metadata={
                "turn": turn, "priority": priority, "delivered": delivered,
                "reason": reason, "notification_id": result.get("notification_id"),
                "note_id": note_id, "why": why,
            },
        )
        logger.info("notify_david: delivered=%s reason=%s title=%r",
                    delivered, reason, title[:60])

    # ── focus side-effect ──
    async def _apply_focus_change(self, change: Optional[dict], *, turn: str) -> None:
        if not isinstance(change, dict):
            return
        topic = change.get("topic")
        why = change.get("why")
        if topic is None:
            await self.backend.clear_focus()
            await self.backend.append_activity(
                kind="focus_clear",
                summary=f"cleared focus ({why or 'no reason given'})"[:200],
                body=why,
                metadata={"turn": turn},
            )
        elif isinstance(topic, str) and topic.strip():
            topic = topic.strip()[:200]
            await self.backend.set_focus(topic=topic, why=(why or None))
            await self.backend.append_activity(
                kind="focus_set",
                summary=f"focus → {topic}"[:200],
                body=why,
                metadata={"turn": turn},
            )
