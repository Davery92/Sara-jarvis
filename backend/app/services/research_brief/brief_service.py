"""Nightly research brief — orchestrator.

Pipeline:
  1. Fetch all sources in parallel (sources.fetch_all_sources)
  2. Dedupe + rank + cap
  3. Single-shot LLM synthesis into a long-form, thematically-clustered report
  4. TTS via Kokoro (reuses morning-brief endpoint + voice for sonic consistency)
  5. Persist to research_brief table
  6. Push notification when audio is ready
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import aiohttp
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import now as local_now, today as local_today

from .sources import ResearchItem, dedupe_and_rank, fetch_all_sources

logger = logging.getLogger(__name__)


# Reuse the morning-brief TTS + storage conventions so audio sounds the same.
TTS_BASE_URL = "http://10.185.1.9:8880/v1/audio/speech"
TTS_VOICE = "af_sarah(1)+af_bella(1)"
BRIEFINGS_BASE_PATH = Path("/home/david/jarvis/data/briefings")

# Target length. At ~150 wpm that's 12-17 minutes of audio.
TARGET_WORD_MIN = 1800
TARGET_WORD_MAX = 2500


SYSTEM_PROMPT = """You are Sara, David's personal AI research analyst. Write his nightly research briefing.

This is a long-form spoken report (not a list). David will listen to it on his commute or while making coffee in the morning. It should read like a senior researcher walking him through the day's most interesting work — connecting threads across papers, pointing out what matters and why, naming the open questions.

Structure (do not print these as headings; weave them into the prose):
  1. A 2-3 sentence opening that names the dominant themes of the day.
  2. The body, organized into 3-5 thematic clusters. Each cluster groups papers that speak to a common problem (e.g. "reasoning under distribution shift", "agent scaffolding", "post-training data engineering"). Inside each cluster, name 2-4 specific papers, summarize the problem and method in plain prose, then say why this paper moves the field — or doesn't.
  3. When an Interconnects AI post is in the inputs, fold its commentary in as connective tissue — Nathan Lambert's read on what's happening is high-signal. Quote or paraphrase his framing where it sharpens the picture.
  4. A closing synthesis: what's the through-line of the day? What should David be paying attention to over the next week?

Voice and style:
  - Tone: a knowledgeable colleague briefing him, not a marketing summary. Direct, specific, occasionally opinionated. Skip filler like "in conclusion" or "let's dive in".
  - Length: {word_min}-{word_max} words. This is meant to be a substantive listen, not a soundbite.
  - Use proper headings sparingly (markdown ## for top-level themes is fine; nothing deeper). Avoid bullet lists — this is being read aloud.
  - Spell out arXiv IDs only when essential. Prefer paper titles in spoken form ("the new Anthropic paper on..." rather than "2605.27385").
  - Never include URLs in the spoken text. The audio listener can't click them.

If a source has nothing interesting, say so briefly and move on — don't manufacture insight."""


USER_PROMPT = """Today is {today_date}. Below are {paper_count} items pulled from arXiv cs.LG, arXiv cs.AI, Hugging Face Daily Papers, and Interconnects AI.

{items_block}

Write the briefing now. Aim for {word_min}-{word_max} words."""


@dataclass
class ResearchBriefResult:
    user_id: str
    brief_date: str
    full_text: str
    audio_path: Optional[str]
    audio_duration_seconds: Optional[float]
    sources: List[dict]
    paper_count: int
    generated_at: str


class ResearchBriefService:
    def __init__(self) -> None:
        self._refresh_llm_config()
        self.llm_api_key = os.environ.get("OPENAI_API_KEY", "dummy")
        self.tts_timeout = aiohttp.ClientTimeout(total=600)

    def _refresh_llm_config(self) -> None:
        self.llm_base_url = settings.bg_llm_primary_url
        self.llm_model = settings.bg_llm_primary_model

    @staticmethod
    def _format_items(items: List[ResearchItem]) -> str:
        """Render fetched items into a structured block the LLM can synthesize.

        Group by source so the LLM can see the texture of each feed; arXiv items
        are kept terse (title + abstract), HF items include upvotes + keywords,
        Interconnects items are paragraphs of commentary."""
        source_labels = {
            "arxiv_lg": "arXiv cs.LG (Machine Learning)",
            "arxiv_ai": "arXiv cs.AI (Artificial Intelligence)",
            "hf_daily": "Hugging Face Daily Papers",
            "interconnects": "Interconnects AI (Nathan Lambert commentary)",
        }
        ordered = ["interconnects", "hf_daily", "arxiv_lg", "arxiv_ai"]
        by_source: dict[str, list[ResearchItem]] = {k: [] for k in ordered}
        for it in items:
            by_source.setdefault(it.source, []).append(it)

        blocks: list[str] = []
        for src in ordered:
            bucket = by_source.get(src) or []
            if not bucket:
                continue
            blocks.append(f"## {source_labels.get(src, src)}\n")
            for it in bucket:
                meta_bits = []
                if it.upvotes:
                    meta_bits.append(f"upvotes={it.upvotes}")
                if it.arxiv_id:
                    meta_bits.append(f"arxiv:{it.arxiv_id}")
                if it.github_repo:
                    meta_bits.append("has-github")
                if it.keywords:
                    meta_bits.append("tags=" + ",".join(it.keywords[:5]))
                meta = f" [{'; '.join(meta_bits)}]" if meta_bits else ""
                blocks.append(f"### {it.title}{meta}")
                # Cap each summary; arXiv abstracts run 200-400 words, IC posts up to 6k chars.
                summary = it.summary
                if len(summary) > 3500:
                    summary = summary[:3500] + "…"
                blocks.append(summary)
                blocks.append("")
        return "\n".join(blocks)

    async def _synthesize(self, items: List[ResearchItem]) -> str:
        self._refresh_llm_config()
        items_block = self._format_items(items)
        today_str = local_today().strftime("%A, %B %d, %Y")

        system_msg = SYSTEM_PROMPT.format(word_min=TARGET_WORD_MIN, word_max=TARGET_WORD_MAX)
        user_msg = USER_PROMPT.format(
            today_date=today_str,
            paper_count=len(items),
            items_block=items_block,
            word_min=TARGET_WORD_MIN,
            word_max=TARGET_WORD_MAX,
        )

        llm_timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=llm_timeout) as session:
            async with session.post(
                f"{self.llm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.llm_model,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 6000,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            ) as response:
                if response.status != 200:
                    err = await response.text()
                    logger.error(f"Research brief LLM call failed ({response.status}): {err}")
                    return ""
                data = await response.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                logger.info(f"Research brief generated: {len(content)} chars, {len(content.split())} words")
                return content

    @staticmethod
    def _strip_markdown_for_tts(s: str) -> str:
        s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"\*(.+?)\*", r"\1", s)
        s = re.sub(r"`(.+?)`", r"\1", s)
        s = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", s)
        s = re.sub(r"^-\s+", "", s, flags=re.MULTILINE)
        s = re.sub(r"^---+$", "", s, flags=re.MULTILINE)
        s = re.sub(r"https?://\S+", "", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    async def _generate_tts(self, text_in: str, output_path: Path) -> Optional[float]:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiohttp.ClientSession(timeout=self.tts_timeout) as session:
                async with session.post(
                    TTS_BASE_URL,
                    json={
                        "input": text_in,
                        "voice": TTS_VOICE,
                        "model": "kokoro",
                        "response_format": "mp3",
                    },
                ) as response:
                    if response.status != 200:
                        err = await response.text()
                        logger.error(f"Research brief TTS failed: {err}")
                        return None
                    audio = await response.read()
                    with open(output_path, "wb") as f:
                        f.write(audio)
                    word_count = len(text_in.split())
                    duration = (word_count / 150.0) * 60.0
                    logger.info(f"Research brief audio written: {output_path} (~{duration:.0f}s)")
                    return duration
        except Exception as e:
            logger.error(f"Research brief TTS error: {e}")
            return None

    def _persist(self, brief: ResearchBriefResult, db: Session) -> None:
        try:
            existing = db.execute(
                text(
                    """
                    SELECT id FROM research_brief
                    WHERE user_id = :uid AND brief_date = :d
                    """
                ),
                {"uid": brief.user_id, "d": brief.brief_date},
            ).fetchone()

            payload = {
                "uid": brief.user_id,
                "d": brief.brief_date,
                "full_text": brief.full_text,
                "audio_path": brief.audio_path,
                "dur": brief.audio_duration_seconds,
                "sources": json.dumps(brief.sources) if brief.sources else None,
                "pc": brief.paper_count,
                "gen": brief.generated_at,
            }

            if existing:
                db.execute(
                    text(
                        """
                        UPDATE research_brief SET
                            full_text = :full_text,
                            audio_path = :audio_path,
                            audio_duration_seconds = :dur,
                            sources = CAST(:sources AS jsonb),
                            paper_count = :pc,
                            generated_at = :gen
                        WHERE user_id = :uid AND brief_date = :d
                        """
                    ),
                    payload,
                )
            else:
                db.execute(
                    text(
                        """
                        INSERT INTO research_brief
                            (user_id, brief_date, full_text, audio_path, audio_duration_seconds,
                             sources, paper_count, generated_at)
                        VALUES
                            (:uid, :d, :full_text, :audio_path, :dur, CAST(:sources AS jsonb), :pc, :gen)
                        """
                    ),
                    payload,
                )
            db.commit()
        except Exception as e:
            logger.error(f"Failed to persist research brief: {e}")
            db.rollback()

    async def _notify(self, user_id: str, paper_count: int, duration_seconds: Optional[float], db: Session) -> None:
        try:
            from app.services.unified_notification import send_notification

            minutes = int((duration_seconds or 0) // 60) if duration_seconds else 0
            len_phrase = f" (~{minutes} min listen)" if minutes else ""
            body = f"Tonight's research briefing is ready — {paper_count} papers across arXiv, Hugging Face, and Interconnects{len_phrase}."

            await send_notification(
                user_id=user_id,
                title="Nightly Research Brief Ready",
                message=body,
                priority="normal",
                topic=f"research_brief:{local_today().isoformat()}",
                category="general",
                source="research_brief",
                cooldown_hours=20.0,
                db=db,
            )
            # send_notification doesn't commit a caller-supplied session (see
            # mindv2_deliver.py's identical fix, 2026-07-30) — without this
            # the notification_log row silently rolled back and the 20h
            # cooldown dedup could never see a prior send.
            db.commit()
        except Exception as e:
            logger.error(f"Research brief notification failed: {e}")

    async def generate(self, user_id: str, db: Session) -> ResearchBriefResult:
        today = local_today()
        brief_date = today.strftime("%Y-%m-%d")
        logger.info(f"Starting research brief for {user_id} on {brief_date}")

        raw_items = await fetch_all_sources()
        items = dedupe_and_rank(raw_items, max_items=25)
        logger.info(f"Research brief: ranked {len(items)} items from {len(raw_items)} fetched")

        if not items:
            logger.warning("Research brief: no items fetched; aborting")
            return ResearchBriefResult(
                user_id=user_id, brief_date=brief_date, full_text="",
                audio_path=None, audio_duration_seconds=None, sources=[],
                paper_count=0, generated_at=local_now().isoformat(),
            )

        full_text = await self._synthesize(items)
        if not full_text.strip():
            logger.error("Research brief: LLM produced empty output")
            return ResearchBriefResult(
                user_id=user_id, brief_date=brief_date, full_text="",
                audio_path=None, audio_duration_seconds=None,
                sources=[it.to_dict() for it in items],
                paper_count=len(items), generated_at=local_now().isoformat(),
            )

        tts_text = self._strip_markdown_for_tts(full_text)
        audio_path = BRIEFINGS_BASE_PATH / user_id / brief_date / "research_brief.mp3"
        duration = await self._generate_tts(tts_text, audio_path)

        result = ResearchBriefResult(
            user_id=user_id,
            brief_date=brief_date,
            full_text=full_text,
            audio_path=str(audio_path) if duration else None,
            audio_duration_seconds=duration,
            sources=[it.to_dict() for it in items],
            paper_count=len(items),
            generated_at=local_now().isoformat(),
        )

        self._persist(result, db)
        await self._notify(user_id, result.paper_count, result.audio_duration_seconds, db)

        logger.info(f"Research brief complete for {user_id}: {result.paper_count} papers, audio={'yes' if result.audio_path else 'no'}")
        return result


research_brief_service = ResearchBriefService()
