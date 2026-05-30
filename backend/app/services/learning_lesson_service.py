"""
Learning Lesson Service
Generates structured teaching lessons from blueprint modules + topic sources.

Lessons differ from study guides:
- Guides are quick-reference ("here's what to know")
- Lessons are progressive teaching units ("let me explain this to you")
- Lessons are ~5-12k words with worked examples, exercises, comprehension checks
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm import get_background_llm_client
from app.models.learning import (
    LearningArtifact,
    LearningBlueprint,
    LearningGuideJob,
    LearningTopic,
    TopicSource,
)
from app.services.learning_source_service import learning_source_service

logger = logging.getLogger(__name__)

DEFAULT_LESSON_MODEL = "qwen3.6-27b"


class JobCancelledError(Exception):
    """Raised when a lesson job is cancelled mid-run."""


class LearningLessonService:
    """Lesson generator with a multi-stage LLM pipeline."""

    async def run_job(self, job_id: str, db: Session) -> Dict[str, Any]:
        """Run a lesson generation job end-to-end."""
        job = db.query(LearningGuideJob).filter(LearningGuideJob.id == job_id).first()
        if not job:
            return {"status": "error", "error": "Lesson job not found", "job_id": job_id}

        from app.services.autonomy.coordination import get_coordinator

        lock_group = "lesson_generation"
        lock_owner = f"lesson-job:{job_id}"
        coordinator = get_coordinator()
        lock_enabled = True
        lock_acquired = False
        lock_heartbeat_task: Optional[asyncio.Task] = None

        try:
            try:
                lock_acquired = await coordinator.acquire_exclusive(lock_owner, lock_group)
            except Exception as lock_error:
                lock_enabled = False
                logger.warning(
                    f"Lesson generation lock unavailable; continuing without pause coordination: {lock_error}"
                )
                lock_acquired = False

            if lock_enabled and not lock_acquired:
                holder = None
                try:
                    holder = await coordinator.get_lock_holder(lock_group)
                except Exception:
                    holder = None
                try:
                    if job.status == "running":
                        job.status = "queued"
                    job.current_step = "Waiting for active lesson generation to finish"
                    db.commit()
                except Exception:
                    db.rollback()
                return {
                    "status": "postponed",
                    "job_id": job.id,
                    "reason": "lesson_generation_in_progress",
                    "lock_holder": holder,
                }

            if lock_enabled and lock_acquired:
                lock_heartbeat_task = asyncio.create_task(
                    self._maintain_lesson_lock(
                        coordinator=coordinator,
                        group=lock_group,
                        worker_name=lock_owner,
                    )
                )

            blueprint = db.query(LearningBlueprint).filter(
                LearningBlueprint.id == job.blueprint_id,
                LearningBlueprint.user_id == job.user_id,
            ).first()
            if not blueprint:
                raise ValueError("Blueprint not found for lesson job")

            config = job.meta or {}
            model = (job.model or config.get("model") or DEFAULT_LESSON_MODEL).strip() or DEFAULT_LESSON_MODEL
            module_limit = int(config.get("module_limit") or 0)
            force_regenerate = bool(config.get("force_regenerate", False))
            num_ctx = int(config.get("num_ctx") or settings.learning_lesson_num_ctx or 49152)
            # Hard cap lesson context to 48k for model stability.
            num_ctx = max(2048, min(num_ctx, 49152))

            modules = self._build_module_work_items(blueprint=blueprint, db=db)
            if module_limit > 0:
                modules = modules[:module_limit]

            if not modules:
                raise ValueError("Blueprint has no modules to generate lessons for")

            db.refresh(job)
            if job.status in {"cancelled", "cancelling"}:
                self._mark_cancelled(job=job, db=db)
                return {
                    "status": "cancelled",
                    "job_id": job.id,
                    "blueprint_id": blueprint.id,
                    "modules_total": len(modules),
                    "modules_completed": job.completed_modules or 0,
                    "artifacts_created": job.artifacts_created or 0,
                    "model": model,
                }
            if job.status not in {"queued", "running"}:
                return {
                    "status": "skipped",
                    "job_id": job.id,
                    "reason": f"job_status_{job.status}",
                }

            if job.status == "queued":
                job.status = "running"
                job.progress = 2
                job.current_step = "Preparing lesson orchestration"
                job.started_at = datetime.now(timezone.utc)
                job.total_modules = len(modules)
                job.completed_modules = 0
                job.artifacts_created = 0
                job.model = model
                db.commit()

            llm = get_background_llm_client()
            artifacts_created = 0

            # Track previous module context for continuity
            prev_module_context: Optional[str] = None

            for idx, module in enumerate(modules, start=1):
                if self._is_cancel_requested(db=db, job_id=job.id):
                    self._mark_cancelled(job=job, db=db)
                    return {
                        "status": "cancelled",
                        "job_id": job.id,
                        "blueprint_id": blueprint.id,
                        "modules_total": len(modules),
                        "modules_completed": job.completed_modules,
                        "artifacts_created": artifacts_created,
                        "model": model,
                    }

                pct = 5 + int(((idx - 1) / max(len(modules), 1)) * 85)
                job.progress = min(pct, 95)
                job.current_step = f"Generating lesson for {module['code']} {module['title']}"
                db.commit()

                try:
                    generated = await self._generate_lesson_for_module(
                        llm=llm,
                        model=model,
                        module=module,
                        blueprint=blueprint,
                        db=db,
                        user_id=job.user_id,
                        force_regenerate=force_regenerate,
                        num_ctx=num_ctx,
                        job_id=job.id,
                        prev_module_context=prev_module_context,
                    )
                except JobCancelledError:
                    self._mark_cancelled(job=job, db=db)
                    return {
                        "status": "cancelled",
                        "job_id": job.id,
                        "blueprint_id": blueprint.id,
                        "modules_total": len(modules),
                        "modules_completed": job.completed_modules,
                        "artifacts_created": artifacts_created,
                        "model": model,
                    }

                if self._is_cancel_requested(db=db, job_id=job.id):
                    self._mark_cancelled(job=job, db=db)
                    return {
                        "status": "cancelled",
                        "job_id": job.id,
                        "blueprint_id": blueprint.id,
                        "modules_total": len(modules),
                        "modules_completed": job.completed_modules,
                        "artifacts_created": artifacts_created,
                        "model": model,
                    }

                now = datetime.now(timezone.utc)
                lesson_md = generated.get("lesson_markdown", "")
                word_count = len(lesson_md.split())
                est_read_time = max(1, round(word_count / 250))

                existing_lesson = generated.get("existing_lesson", {})
                next_version = int(existing_lesson.get("version") or 0) + 1

                artifact = LearningArtifact(
                    id=str(uuid.uuid4()),
                    user_id=job.user_id,
                    topic_id=module.get("topic_id"),
                    artifact_type="lesson",
                    title=f"{module['title']} - Lesson",
                    version=next_version,
                    content={
                        "blueprint_id": blueprint.id,
                        "phase_index": module.get("phase_index"),
                        "module_code": module.get("code"),
                        "module_title": module.get("title"),
                        "model": model,
                        "num_ctx": num_ctx,
                        "generated_at": now.isoformat(),
                        "sources": generated.get("sources", []),
                        "lesson_plan": generated.get("lesson_plan", {}),
                        "critic_review": generated.get("critic_review", {}),
                        "lesson_markdown": lesson_md,
                        "word_count": word_count,
                        "estimated_read_time_minutes": est_read_time,
                    },
                )
                db.add(artifact)
                db.commit()

                artifacts_created += 1
                job.completed_modules = idx
                job.artifacts_created = artifacts_created
                job.progress = min(5 + int((idx / max(len(modules), 1)) * 90), 99)
                job.current_step = f"Completed {idx}/{len(modules)} modules"
                db.commit()

                # Save summary for next module's continuity
                prev_module_context = f"Previous module: {module['code']} {module['title']}"

            job.status = "completed"
            job.progress = 100
            job.current_step = "Completed"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            return {
                "status": "completed",
                "job_id": job.id,
                "blueprint_id": blueprint.id,
                "modules_total": len(modules),
                "modules_completed": job.completed_modules,
                "artifacts_created": artifacts_created,
                "model": model,
            }
        except Exception as e:
            logger.error(f"Lesson generation failed for job {job_id}: {e}", exc_info=True)
            error_text = str(e).strip() or repr(e)
            try:
                job.status = "failed"
                job.error_message = error_text[:1000]
                job.current_step = "Failed"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
            except Exception:
                db.rollback()
            return {"status": "failed", "job_id": job_id, "error": error_text}
        finally:
            if lock_heartbeat_task:
                lock_heartbeat_task.cancel()
                try:
                    await lock_heartbeat_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

            if lock_enabled and lock_acquired:
                try:
                    await coordinator.release_exclusive(lock_group, worker_name=lock_owner)
                except Exception as release_error:
                    logger.warning(f"Failed to release lesson generation lock: {release_error}")

    async def _maintain_lesson_lock(self, coordinator, group: str, worker_name: str):
        """Refresh lesson-generation lock TTL while a job is running."""
        while True:
            await asyncio.sleep(60)
            try:
                refreshed = await coordinator.refresh_exclusive(worker_name=worker_name, group=group)
                if not refreshed:
                    logger.warning(
                        f"Lost lesson generation lock heartbeat for {worker_name}; "
                        "other background LLM jobs may resume."
                    )
                    return
            except Exception as e:
                logger.warning(f"Lesson generation lock refresh failed: {e}")

    # ── Module work items (reused from guide service) ──

    def _build_module_work_items(self, blueprint: LearningBlueprint, db: Session) -> List[Dict[str, Any]]:
        parsed = blueprint.parsed_json or {}
        phases = parsed.get("phases") or []

        topic_rows = db.query(LearningTopic).filter(
            LearningTopic.user_id == blueprint.user_id,
            LearningTopic.blueprint_id == blueprint.id,
        ).all()

        by_code: Dict[str, LearningTopic] = {}
        by_title: Dict[str, LearningTopic] = {}
        for topic in topic_rows:
            meta = topic.meta or {}
            if meta.get("blueprint_node_type") == "module":
                code = str(meta.get("blueprint_module_code") or "").strip()
                if code:
                    by_code[code] = topic
                title_key = (topic.title or "").strip().lower()
                if title_key:
                    by_title[title_key] = topic

        modules: List[Dict[str, Any]] = []
        for phase in sorted(phases, key=lambda p: int(p.get("index", 9999) or 9999)):
            phase_index = int(phase.get("index", 0) or 0)
            phase_title = str(phase.get("title") or f"Phase {phase_index}").strip()
            for mod_idx, module in enumerate(phase.get("modules") or []):
                code = str(module.get("code") or f"{phase_index}.{mod_idx + 1}").strip()
                title = str(module.get("title") or code).strip()
                topic = by_code.get(code) or by_title.get(title.lower())
                modules.append({
                    "phase_index": phase_index,
                    "phase_title": phase_title,
                    "code": code,
                    "title": title,
                    "summary": (module.get("summary") or "").strip(),
                    "learning_objectives": module.get("learning_objectives") or [],
                    "concepts": module.get("concepts") or [],
                    "resources": module.get("resources") or [],
                    "topic_id": topic.id if topic else None,
                })
        return modules

    # ── Load existing lesson ──

    def _load_existing_lesson(
        self,
        db: Session,
        user_id: str,
        module: Dict[str, Any],
        blueprint: LearningBlueprint,
    ) -> Dict[str, Any]:
        module_code = str(module.get("code") or "").strip()
        topic_id = module.get("topic_id")

        query = db.query(LearningArtifact).filter(
            LearningArtifact.user_id == user_id,
            LearningArtifact.artifact_type == "lesson",
        )
        if topic_id:
            query = query.filter(LearningArtifact.topic_id == topic_id)
        else:
            query = query.filter(
                LearningArtifact.content["blueprint_id"].astext == blueprint.id,
                LearningArtifact.content["module_code"].astext == module_code,
            )
        row = query.order_by(
            LearningArtifact.version.desc(),
            LearningArtifact.updated_at.desc(),
        ).first()

        if not row:
            return {}
        content = row.content or {}
        return {
            "id": row.id,
            "version": int(row.version or 1),
            "lesson_markdown": str(content.get("lesson_markdown") or "").strip(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ── Main per-module pipeline ──

    async def _generate_lesson_for_module(
        self,
        llm,
        model: str,
        module: Dict[str, Any],
        blueprint: LearningBlueprint,
        db: Session,
        user_id: str,
        force_regenerate: bool,
        num_ctx: int,
        job_id: str,
        prev_module_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the 5-agent lesson pipeline for one module."""
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        # Collect enhanced source context (more chunks than guides)
        source_context, source_cards = await self._collect_lesson_source_context(
            module=module, db=db, prev_module_context=prev_module_context,
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        existing_lesson = self._load_existing_lesson(
            db=db, user_id=user_id, module=module, blueprint=blueprint,
        )

        # Agent 1: Lesson Planner
        lesson_plan = await self._lesson_planner_agent(
            llm=llm, model=model, blueprint=blueprint, module=module,
            source_context=source_context, num_ctx=min(num_ctx, 32768),
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        # Agent 2: Lesson Writer (2-3 calls for section continuity)
        lesson_body = await self._lesson_writer_agent(
            llm=llm, model=model, blueprint=blueprint, module=module,
            source_context=source_context, source_cards=source_cards,
            lesson_plan=lesson_plan, num_ctx=num_ctx,
            prev_module_context=prev_module_context,
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        # Agent 3: Exercise Builder
        exercises = await self._exercise_builder_agent(
            llm=llm, model=model, module=module,
            source_context=source_context, lesson_plan=lesson_plan,
            num_ctx=min(num_ctx, 32768),
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        # Combine lesson body + exercises
        lesson_markdown = lesson_body.strip()
        if exercises.strip():
            lesson_markdown += "\n\n" + exercises.strip()

        # Agent 4: Lesson Critic
        critic_review = await self._lesson_critic_agent(
            llm=llm, model=model, module=module,
            lesson_plan=lesson_plan, lesson_markdown=lesson_markdown,
            num_ctx=min(num_ctx, 32768),
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        # Agent 5: Reviser (conditional)
        quality = float(critic_review.get("quality_score") or 0.0)
        coverage = float(critic_review.get("coverage_score") or 0.0)
        if quality < 0.75 or coverage < 0.78:
            lesson_markdown = await self._lesson_reviser_agent(
                llm=llm, model=model, module=module,
                lesson_markdown=lesson_markdown,
                critic_review=critic_review,
                source_context=source_context,
                num_ctx=num_ctx,
            )
            self._raise_if_cancel_requested(db=db, job_id=job_id)

        return {
            "lesson_plan": lesson_plan,
            "critic_review": critic_review,
            "lesson_markdown": lesson_markdown,
            "sources": source_cards,
            "existing_lesson": existing_lesson,
        }

    # ── Enhanced source context (more chunks than guides) ──

    async def _collect_lesson_source_context(
        self,
        module: Dict[str, Any],
        db: Session,
        prev_module_context: Optional[str] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Collect grounded source context for lesson generation.

        Enhanced over guide source collection:
        - 40 general chunks (vs 20 for guides)
        - Full referenced chapters
        - Previous module context for continuity
        """
        topic_id = module.get("topic_id")
        if not topic_id:
            return "No linked topic sources were materialized for this module.", []

        sources = db.query(TopicSource).filter(
            TopicSource.topic_id == topic_id
        ).order_by(TopicSource.created_at.asc()).all()

        source_cards: List[Dict[str, Any]] = []
        source_ref_by_title: Dict[str, str] = {}
        for idx, source in enumerate(sources[:20]):
            ref = f"S{idx + 1}"
            title = source.title or f"Source {idx + 1}"
            card = {
                "ref": ref,
                "title": title,
                "url": source.url,
                "source_type": source.source_type,
                "quality_score": float(source.quality_score or 0.0),
            }
            if source.toc:
                card["has_chapters"] = True
            source_cards.append(card)
            source_ref_by_title[title.strip().lower()] = ref

        query_terms = [module.get("title", ""), module.get("summary", "")]
        objectives = module.get("learning_objectives") or []
        query_terms.extend([str(obj) for obj in objectives[:4]])
        search_query = " | ".join(t for t in query_terms if t)

        # Chapter-filtered retrieval
        chapter_refs_for_module: List[str] = []
        chapter_context_notes: List[str] = []
        for resource in module.get("resources") or []:
            notes = resource.get("notes") or ""
            if notes:
                refs = learning_source_service.parse_chapter_refs_from_notes(notes)
                if refs:
                    chapter_refs_for_module.extend(refs)
                    res_title = resource.get("title", "")
                    chapter_context_notes.append(
                        f"[{res_title}] {', '.join(refs)}"
                    )

        chapter_refs_for_module = list(dict.fromkeys(chapter_refs_for_module))

        seen_chunk_ids = set()
        excerpt_lines: List[str] = []

        # Priority: full chapters when referenced
        if chapter_refs_for_module:
            chapter_chunks = learning_source_service.get_all_chapter_chunks(
                topic_id=topic_id,
                chapter_refs=chapter_refs_for_module,
                db=db,
            )
            for chunk in chapter_chunks:
                cid = chunk.get("id")
                if cid in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(cid)
                source_title = (chunk.get("source_title") or "").strip()
                ref = source_ref_by_title.get(source_title.lower(), "S?")
                text = str(chunk.get("original_text") or chunk.get("text") or "").strip()
                ch_ref = chunk.get("chapter_ref") or ""
                if not text:
                    continue
                label = f"[{ref}] {source_title}"
                if ch_ref:
                    label += f" ({ch_ref})"
                excerpt_lines.append(f"{label}\n{text}")

        # Fill with general vector search — 40 chunks for lessons (vs 20 for guides)
        general_chunks = await learning_source_service.search_chunks(
            topic_id=topic_id,
            query=search_query or module.get("title", ""),
            db=db,
            limit=40,
            prefer_analogy=False,
        )
        for chunk in general_chunks:
            cid = chunk.get("id")
            if cid in seen_chunk_ids:
                continue
            seen_chunk_ids.add(cid)
            source_title = (chunk.get("source_title") or "").strip()
            ref = source_ref_by_title.get(source_title.lower(), "S?")
            text = str(chunk.get("original_text") or chunk.get("text") or "").strip()
            if not text:
                continue
            excerpt_lines.append(f"[{ref}] {source_title}\n{text}")

        if not excerpt_lines:
            for idx, source in enumerate(sources[:6]):
                snippet = (source.content_text or "").strip()
                if not snippet:
                    continue
                ref = f"S{idx + 1}"
                excerpt_lines.append(f"[{ref}] {source.title or 'Source'}\n{snippet[:1200]}")

        if not excerpt_lines:
            return "No fetched source chunks were available for this module.", source_cards

        # Prepend chapter context note
        if chapter_context_notes:
            header = "Chapter-specific sources for this module:\n" + "\n".join(
                f"  - {note}" for note in chapter_context_notes
            )
            excerpt_lines.insert(0, header)

        # Add previous module context for continuity
        if prev_module_context:
            excerpt_lines.insert(0, f"[Continuity] {prev_module_context}")

        source_context = "\n\n".join(excerpt_lines)
        return source_context, source_cards

    # ── Agent 1: Lesson Planner ──

    async def _lesson_planner_agent(
        self,
        llm,
        model: str,
        blueprint: LearningBlueprint,
        module: Dict[str, Any],
        source_context: str,
        num_ctx: int,
    ) -> Dict[str, Any]:
        """Plan lesson structure: sections, concept ordering, teaching strategy."""
        concepts = module.get("concepts") or []
        concept_names = []
        for c in concepts[:20]:
            if isinstance(c, dict):
                name = str(c.get("name") or "").strip()
                if name:
                    concept_names.append(name)
            elif isinstance(c, str):
                concept_names.append(c.strip())

        prompt = f"""You are a curriculum designer planning a teaching lesson.
Create a detailed lesson plan for one module. This is a TEACHING lesson, not a reference guide.
The goal is to progressively explain concepts from familiar to unfamiliar.
Output ONLY valid JSON.

Blueprint: {blueprint.title}
Phase: {module.get("phase_index")} - {module.get("phase_title")}
Module: {module.get("code")} {module.get("title")}
Module summary: {module.get("summary") or "N/A"}
Learning objectives: {json.dumps(module.get("learning_objectives") or [], ensure_ascii=False)}
Concepts: {json.dumps(concept_names, ensure_ascii=False)}

Source excerpts (sample):
{source_context[:4000]}

Return JSON with this schema:
{{
  "teaching_strategy": "string describing overall approach",
  "concept_order": ["concept1", "concept2"],
  "sections": [
    {{
      "title": "section title",
      "purpose": "what this section teaches",
      "key_points": ["point1", "point2"],
      "examples_needed": ["example description"]
    }}
  ],
  "prerequisites": ["what learner should already know"],
  "connections_to_next": "how this connects to the next module"
}}"""

        try:
            content = await self._llm_text(
                llm=llm, model=model,
                messages=[
                    {"role": "system", "content": "Return only valid JSON. You are an expert curriculum designer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25, max_tokens=1500, num_ctx=num_ctx,
            )
            parsed = self._parse_json(content)
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Lesson planner failed for {module.get('code')}: {e}")

        return {
            "teaching_strategy": "progressive explanation",
            "concept_order": concept_names[:10],
            "sections": [{"title": module.get("title"), "purpose": "Core content", "key_points": [], "examples_needed": []}],
            "prerequisites": [],
            "connections_to_next": "",
        }

    # ── Agent 2: Lesson Writer (multi-call for continuity) ──

    async def _lesson_writer_agent(
        self,
        llm,
        model: str,
        blueprint: LearningBlueprint,
        module: Dict[str, Any],
        source_context: str,
        source_cards: List[Dict[str, Any]],
        lesson_plan: Dict[str, Any],
        num_ctx: int,
        prev_module_context: Optional[str] = None,
    ) -> str:
        """Write the lesson in 2-3 calls for section continuity."""
        source_list = "\n".join(
            f"- [{s['ref']}] {s['title']}" + (f" ({s['url']})" if s.get("url") else "")
            for s in source_cards[:14]
        ) or "- No explicit sources were linked."

        sections = lesson_plan.get("sections") or []
        prerequisites = lesson_plan.get("prerequisites") or []
        teaching_strategy = lesson_plan.get("teaching_strategy") or "progressive explanation"
        connections = lesson_plan.get("connections_to_next") or ""

        base_context = f"""You are writing a structured teaching lesson for a student.
This is NOT a reference guide — it's a lesson that teaches concepts progressively like a great textbook chapter.

Blueprint: {blueprint.title}
Module: {module.get("code")} {module.get("title")}
Phase: {module.get("phase_index")} - {module.get("phase_title")}
Module summary: {module.get("summary") or "N/A"}
Teaching strategy: {teaching_strategy}

Lesson plan:
{json.dumps(lesson_plan, ensure_ascii=False)}

Sources:
{source_list}

Source excerpts:
{source_context}

IMPORTANT RULES:
- Weave source material naturally into explanations, citing as [S1], [S2] etc.
- Bold key terms on first use
- Build from familiar to unfamiliar
- Use concrete examples and analogies
- Write in an engaging, clear teaching voice — not dry reference style"""

        continuity_note = ""
        if prev_module_context:
            continuity_note = f"\n{prev_module_context} — reference it in the 'Why This Matters' section.\n"

        # Call 1: Opening sections (Why This Matters, Prerequisites, first half of Core Concepts)
        call1_prompt = f"""{base_context}
{continuity_note}
Write the FIRST PART of the lesson in Markdown:

## Why This Matters
Motivation, connection to prior modules, real-world relevance. Make the student care about this topic.

## Prerequisites
{json.dumps(prerequisites, ensure_ascii=False) if prerequisites else "Quick self-check of what they should already know."}

## Core Concepts (Part 1)
Begin the progressive explanations. Cover the first half of concepts from the plan.
Build from the most familiar concepts to set up the harder ones.

Write engaging, thorough content. Target ~2000-3000 words for this section."""

        part1 = await self._llm_text(
            llm=llm, model=model,
            messages=[
                {"role": "system", "content": "You are an expert teacher writing a structured lesson. Write detailed, engaging educational content."},
                {"role": "user", "content": call1_prompt},
            ],
            temperature=0.3, max_tokens=8192, num_ctx=num_ctx,
        )

        # Call 2: Continue Core Concepts + Worked Examples
        call2_prompt = f"""{base_context}

Here is what you've written so far:
{part1}

Continue the lesson from where you left off. Write:

## Core Concepts (continued)
Complete the remaining concepts from the plan. Build on what was established in Part 1.
Increase complexity progressively.

## Worked Examples
Step-by-step walkthroughs grounded in source material. Start simple, increase complexity.
Show the thinking process, not just the answer.

Target ~2000-3000 words for this continuation. Do NOT repeat content from Part 1."""

        part2 = await self._llm_text(
            llm=llm, model=model,
            messages=[
                {"role": "system", "content": "You are continuing a structured lesson. Write detailed, engaging educational content that builds on what came before."},
                {"role": "user", "content": call2_prompt},
            ],
            temperature=0.3, max_tokens=8192, num_ctx=num_ctx,
        )

        # Call 3: Key Takeaways + What's Next
        call3_prompt = f"""{base_context}

The lesson so far covers concepts and worked examples. Now write the closing sections:

## Key Takeaways
Write 5-8 "You should now be able to..." statements that summarize what the student learned.

## What's Next
{f"Connection to next module: {connections}" if connections else "Preview how these concepts connect forward in the learning path."}

Keep this section concise (~500-800 words)."""

        part3 = await self._llm_text(
            llm=llm, model=model,
            messages=[
                {"role": "system", "content": "You are completing a structured lesson with takeaways and forward-looking summary."},
                {"role": "user", "content": call3_prompt},
            ],
            temperature=0.3, max_tokens=4096, num_ctx=num_ctx,
        )

        # Combine all parts under a single heading
        heading = f"# {module.get('code')} {module.get('title')}\n\n"
        lesson = heading + part1.strip() + "\n\n" + part2.strip() + "\n\n" + part3.strip()
        return lesson

    # ── Agent 3: Exercise Builder ──

    async def _exercise_builder_agent(
        self,
        llm,
        model: str,
        module: Dict[str, Any],
        source_context: str,
        lesson_plan: Dict[str, Any],
        num_ctx: int,
    ) -> str:
        """Build comprehension checks and practice exercises."""
        prompt = f"""You are creating exercises for a teaching lesson on: {module.get("code")} {module.get("title")}

Lesson plan concepts: {json.dumps(lesson_plan.get("concept_order", []), ensure_ascii=False)}
Learning objectives: {json.dumps(module.get("learning_objectives") or [], ensure_ascii=False)}

Source excerpts (for grounding exercises in real content):
{source_context[:6000]}

Write TWO sections in Markdown:

## Check Your Understanding
5-8 comprehension questions testing key concepts from this lesson.
Format each as:

**Q1: [Question text]**

> **Answer:** [Concise answer explaining the reasoning]

## Practice Exercises
3-5 practice problems with increasing difficulty (recall → application → analysis).
Format each as:

**Exercise 1: [Title]**
[Problem description]

> **Hint:** [A helpful hint]

> **Solution:** [Detailed solution with explanation]

Ground exercises in real scenarios from the source material where possible.
Questions should test understanding, not just memorization."""

        try:
            return await self._llm_text(
                llm=llm, model=model,
                messages=[
                    {"role": "system", "content": "You create thoughtful educational exercises that test real understanding. Use blockquotes for answers and solutions."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.35, max_tokens=6144, num_ctx=num_ctx,
            )
        except Exception as e:
            logger.warning(f"Exercise builder failed for {module.get('code')}: {e}")
            return ""

    # ── Agent 4: Lesson Critic ──

    async def _lesson_critic_agent(
        self,
        llm,
        model: str,
        module: Dict[str, Any],
        lesson_plan: Dict[str, Any],
        lesson_markdown: str,
        num_ctx: int,
    ) -> Dict[str, Any]:
        """Review lesson quality and coverage."""
        prompt = f"""Review this teaching lesson for quality and coverage.
Return ONLY valid JSON.

Module: {module.get("code")} {module.get("title")}
Lesson plan:
{json.dumps(lesson_plan, ensure_ascii=False)}

Lesson text:
{lesson_markdown[:12000]}

Evaluate and return:
{{
  "quality_score": 0.0,
  "coverage_score": 0.0,
  "missing_concepts": ["string"],
  "pedagogical_strengths": ["string"],
  "revision_instructions": ["specific actionable improvement"]
}}

Scoring guide:
- quality_score: 0-1, based on clarity, engagement, progressive difficulty, use of examples
- coverage_score: 0-1, based on how many planned concepts and objectives are actually taught"""

        try:
            content = await self._llm_text(
                llm=llm, model=model,
                messages=[
                    {"role": "system", "content": "You are a strict educational quality reviewer. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1, max_tokens=1000, num_ctx=num_ctx,
            )
            parsed = self._parse_json(content)
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Lesson critic failed for {module.get('code')}: {e}")

        return {
            "quality_score": 0.8,
            "coverage_score": 0.8,
            "missing_concepts": [],
            "pedagogical_strengths": [],
            "revision_instructions": [],
        }

    # ── Agent 5: Lesson Reviser (conditional) ──

    async def _lesson_reviser_agent(
        self,
        llm,
        model: str,
        module: Dict[str, Any],
        lesson_markdown: str,
        critic_review: Dict[str, Any],
        source_context: str,
        num_ctx: int,
    ) -> str:
        """Revise lesson based on critic feedback."""
        prompt = f"""Revise this teaching lesson to address the critic's feedback.
Keep the lesson structure intact. Fix gaps and improve weak areas.
Add missing content — do not just rearrange existing text.

Module: {module.get("code")} {module.get("title")}

Critic feedback:
{json.dumps(critic_review, ensure_ascii=False)}

Source excerpts (for adding missing content):
{source_context[:8000]}

Current lesson:
{lesson_markdown}

Return the complete revised lesson in Markdown."""

        try:
            return await self._llm_text(
                llm=llm, model=model,
                messages=[
                    {"role": "system", "content": "You are revising a teaching lesson based on specific feedback. Be thorough — address every point raised by the critic."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2, max_tokens=16384, num_ctx=num_ctx,
            )
        except Exception as e:
            logger.warning(f"Lesson revision failed for {module.get('code')}: {e}")
            return lesson_markdown

    # ── Shared utilities ──

    async def _llm_text(
        self,
        llm,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        num_ctx: int,
    ) -> str:
        lesson_timeout = float(getattr(settings, "learning_lesson_request_timeout", 300.0) or 300.0)
        lesson_timeout = max(60.0, lesson_timeout)
        response = await llm.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            options={"num_ctx": num_ctx},
            allow_during_lesson_generation=True,
            allow_fallback=False,
            request_timeout=lesson_timeout,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            raise ValueError("Empty LLM response")
        return content

    def _parse_json(self, text_value: str) -> Optional[Dict[str, Any]]:
        candidate = text_value.strip()
        if "```" in candidate:
            parts = candidate.split("```")
            for part in parts:
                piece = part.strip()
                if piece.startswith("json"):
                    piece = piece[4:].strip()
                if piece.startswith("{") and piece.endswith("}"):
                    try:
                        return json.loads(piece)
                    except Exception:
                        continue

        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                return json.loads(candidate)
            except Exception:
                pass

        match = re.search(r"\{[\s\S]*\}", candidate)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
        return None

    def _is_cancel_requested(self, db: Session, job_id: str) -> bool:
        status = db.query(LearningGuideJob.status).filter(
            LearningGuideJob.id == job_id
        ).scalar()
        return status in {"cancelling", "cancelled"}

    def _raise_if_cancel_requested(self, db: Session, job_id: str):
        if self._is_cancel_requested(db=db, job_id=job_id):
            raise JobCancelledError("Lesson generation cancelled")

    def _mark_cancelled(self, job: LearningGuideJob, db: Session):
        job.status = "cancelled"
        job.current_step = "Cancelled"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()


learning_lesson_service = LearningLessonService()
