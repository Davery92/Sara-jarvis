"""
Learning Guide Service
Generates blueprint-aligned study guides from imported plans + topic sources.
"""
from __future__ import annotations

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

DEFAULT_GUIDE_MODEL = "gpt-oss:20b"


class JobCancelledError(Exception):
    """Raised when a guide job is cancelled mid-run."""


class LearningGuideService:
    """Study-guide generator with a multi-stage orchestration flow."""

    async def run_job(self, job_id: str, db: Session) -> Dict[str, Any]:
        """Run a guide generation job end-to-end."""
        job = db.query(LearningGuideJob).filter(LearningGuideJob.id == job_id).first()
        if not job:
            return {"status": "error", "error": "Guide job not found", "job_id": job_id}

        try:
            blueprint = db.query(LearningBlueprint).filter(
                LearningBlueprint.id == job.blueprint_id,
                LearningBlueprint.user_id == job.user_id,
            ).first()
            if not blueprint:
                raise ValueError("Blueprint not found for guide job")

            config = job.meta or {}
            model = (job.model or config.get("model") or DEFAULT_GUIDE_MODEL).strip() or DEFAULT_GUIDE_MODEL
            module_limit = int(config.get("module_limit") or 0)
            force_regenerate = bool(config.get("force_regenerate", False))
            num_ctx = int(config.get("num_ctx") or settings.learning_guide_num_ctx or 16384)
            num_ctx = max(2048, min(num_ctx, 131072))

            modules = self._build_module_work_items(blueprint=blueprint, db=db)
            if module_limit > 0:
                modules = modules[:module_limit]

            if not modules:
                raise ValueError("Blueprint has no modules to generate guides for")

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
                job.current_step = "Preparing module orchestration"
                job.started_at = datetime.now(timezone.utc)
                job.total_modules = len(modules)
                job.completed_modules = 0
                job.artifacts_created = 0
                job.model = model
                db.commit()

            llm = get_background_llm_client()
            artifacts_created = 0

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
                job.current_step = f"Generating guides for {module['code']} {module['title']}"
                db.commit()

                try:
                    generated = await self._generate_guides_for_module(
                        llm=llm,
                        model=model,
                        module=module,
                        blueprint=blueprint,
                        db=db,
                        user_id=job.user_id,
                        force_regenerate=force_regenerate,
                        num_ctx=num_ctx,
                        job_id=job.id,
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
                pareto_artifact = LearningArtifact(
                    id=str(uuid.uuid4()),
                    user_id=job.user_id,
                    topic_id=module.get("topic_id"),
                    artifact_type="study_guide_pareto",
                    title=f"{module['title']} - Pareto Overview",
                    version=int(generated.get("pareto_next_version") or 1),
                    content={
                        "blueprint_id": blueprint.id,
                        "phase_index": module.get("phase_index"),
                        "module_code": module.get("code"),
                        "module_title": module.get("title"),
                        "model": model,
                        "num_ctx": num_ctx,
                        "generated_at": now.isoformat(),
                        "force_regenerate": force_regenerate,
                        "enhanced_from_existing": bool(generated.get("existing_pareto")),
                        "base_artifact_id": generated.get("existing_pareto", {}).get("id") if isinstance(generated.get("existing_pareto"), dict) else None,
                        "sources": generated.get("sources", []),
                        "coverage_plan": generated.get("coverage_plan", {}),
                        "guide_markdown": generated.get("pareto_guide", ""),
                    },
                )
                db.add(pareto_artifact)

                deep_artifact = LearningArtifact(
                    id=str(uuid.uuid4()),
                    user_id=job.user_id,
                    topic_id=module.get("topic_id"),
                    artifact_type="study_guide_deep",
                    title=f"{module['title']} - Deep Study Guide",
                    version=int(generated.get("deep_next_version") or 1),
                    content={
                        "blueprint_id": blueprint.id,
                        "phase_index": module.get("phase_index"),
                        "module_code": module.get("code"),
                        "module_title": module.get("title"),
                        "model": model,
                        "num_ctx": num_ctx,
                        "generated_at": now.isoformat(),
                        "force_regenerate": force_regenerate,
                        "enhanced_from_existing": bool(generated.get("existing_deep")),
                        "base_artifact_id": generated.get("existing_deep", {}).get("id") if isinstance(generated.get("existing_deep"), dict) else None,
                        "sources": generated.get("sources", []),
                        "coverage_plan": generated.get("coverage_plan", {}),
                        "critic_review": generated.get("critic_review", {}),
                        "guide_markdown": generated.get("deep_guide", ""),
                    },
                )
                db.add(deep_artifact)
                db.commit()

                artifacts_created += 2
                job.completed_modules = idx
                job.artifacts_created = artifacts_created
                job.progress = min(5 + int((idx / max(len(modules), 1)) * 90), 99)
                job.current_step = f"Completed {idx}/{len(modules)} modules"
                db.commit()

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
            logger.error(f"Guide generation failed for job {job_id}: {e}", exc_info=True)
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

    def _build_module_work_items(self, blueprint: LearningBlueprint, db: Session) -> List[Dict[str, Any]]:
        """Create a normalized module worklist from parsed blueprint + materialized topics."""
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

    def _load_existing_guides(
        self,
        db: Session,
        user_id: str,
        module: Dict[str, Any],
        blueprint: LearningBlueprint,
    ) -> Dict[str, Dict[str, Any]]:
        """Load latest Pareto/deep artifacts for this module, if any."""
        module_code = str(module.get("code") or "").strip()
        topic_id = module.get("topic_id")

        def _latest(artifact_type: str) -> Optional[LearningArtifact]:
            query = db.query(LearningArtifact).filter(
                LearningArtifact.user_id == user_id,
                LearningArtifact.artifact_type == artifact_type,
            )
            if topic_id:
                query = query.filter(LearningArtifact.topic_id == topic_id)
            else:
                query = query.filter(
                    LearningArtifact.content["blueprint_id"].astext == blueprint.id,
                    LearningArtifact.content["module_code"].astext == module_code,
                )
            return query.order_by(
                LearningArtifact.version.desc(),
                LearningArtifact.updated_at.desc(),
            ).first()

        def _pack(row: Optional[LearningArtifact]) -> Dict[str, Any]:
            if not row:
                return {}
            content = row.content or {}
            return {
                "id": row.id,
                "version": int(row.version or 1),
                "guide_markdown": str(content.get("guide_markdown") or "").strip(),
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

        return {
            "pareto": _pack(_latest("study_guide_pareto")),
            "deep": _pack(_latest("study_guide_deep")),
        }

    async def _generate_guides_for_module(
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
    ) -> Dict[str, Any]:
        """Run the orchestrated agent stack for one module."""
        self._raise_if_cancel_requested(db=db, job_id=job_id)
        source_context, source_cards = await self._collect_source_context(module=module, db=db)
        self._raise_if_cancel_requested(db=db, job_id=job_id)
        existing_guides = self._load_existing_guides(
            db=db,
            user_id=user_id,
            module=module,
            blueprint=blueprint,
        )
        include_existing = not force_regenerate

        coverage_plan = await self._coverage_agent(
            llm=llm,
            model=model,
            blueprint=blueprint,
            module=module,
            source_context=source_context,
            num_ctx=num_ctx,
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        pareto_guide = await self._pareto_agent(
            llm=llm,
            model=model,
            blueprint=blueprint,
            module=module,
            source_context=source_context,
            source_cards=source_cards,
            coverage_plan=coverage_plan,
            previous_guide=existing_guides.get("pareto", {}).get("guide_markdown") if include_existing else None,
            num_ctx=num_ctx,
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        deep_guide = await self._deep_guide_agent(
            llm=llm,
            model=model,
            blueprint=blueprint,
            module=module,
            source_context=source_context,
            source_cards=source_cards,
            coverage_plan=coverage_plan,
            previous_guide=existing_guides.get("deep", {}).get("guide_markdown") if include_existing else None,
            num_ctx=num_ctx,
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        critic_review = await self._critic_agent(
            llm=llm,
            model=model,
            module=module,
            coverage_plan=coverage_plan,
            deep_guide=deep_guide,
            num_ctx=num_ctx,
        )
        self._raise_if_cancel_requested(db=db, job_id=job_id)

        if float(critic_review.get("coverage_score") or 0.0) < 0.78:
            deep_guide = await self._revise_deep_guide(
                llm=llm,
                model=model,
                module=module,
                deep_guide=deep_guide,
                critic_review=critic_review,
                num_ctx=num_ctx,
            )
            self._raise_if_cancel_requested(db=db, job_id=job_id)

        return {
            "coverage_plan": coverage_plan,
            "pareto_guide": pareto_guide,
            "deep_guide": deep_guide,
            "critic_review": critic_review,
            "sources": source_cards,
            "existing_pareto": existing_guides.get("pareto"),
            "existing_deep": existing_guides.get("deep"),
            "pareto_next_version": int(existing_guides.get("pareto", {}).get("version") or 0) + 1,
            "deep_next_version": int(existing_guides.get("deep", {}).get("version") or 0) + 1,
        }

    async def _collect_source_context(
        self,
        module: Dict[str, Any],
        db: Session,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Collect grounded source context for the module.

        Enhanced with chapter-aware retrieval:
        1. Parse chapter refs from blueprint resource notes
        2. For matched sources, search chapter-filtered chunks first (priority slots)
        3. Fill remaining slots with standard vector similarity
        4. De-duplicate by chunk ID
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
            # Note if this source has chapter structure
            if source.toc:
                card["has_chapters"] = True
            source_cards.append(card)
            source_ref_by_title[title.strip().lower()] = ref

        query_terms = [module.get("title", ""), module.get("summary", "")]
        objectives = module.get("learning_objectives") or []
        query_terms.extend([str(obj) for obj in objectives[:4]])
        search_query = " | ".join(t for t in query_terms if t)

        # ── Chapter-filtered retrieval ──
        # Parse chapter refs from blueprint resource notes
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

        # De-duplicate chapter refs
        chapter_refs_for_module = list(dict.fromkeys(chapter_refs_for_module))

        seen_chunk_ids = set()
        excerpt_lines: List[str] = []

        # Priority: pull ENTIRE chapters when the plan references them
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

        # Fill with general vector search for supplementary context
        general_chunks = await learning_source_service.search_chunks(
            topic_id=topic_id,
            query=search_query or module.get("title", ""),
            db=db,
            limit=20,
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

        # Prepend chapter context note if we had chapter-specific retrieval
        if chapter_context_notes:
            header = "Chapter-specific sources for this module:\n" + "\n".join(
                f"  - {note}" for note in chapter_context_notes
            )
            excerpt_lines.insert(0, header)

        source_context = "\n\n".join(excerpt_lines)

        return source_context, source_cards

    async def _coverage_agent(
        self,
        llm,
        model: str,
        blueprint: LearningBlueprint,
        module: Dict[str, Any],
        source_context: str,
        num_ctx: int,
    ) -> Dict[str, Any]:
        """Agent 1: Build a coverage checklist from plan + sources."""
        concepts = module.get("concepts") or []
        concept_names = []
        for c in concepts[:20]:
            if isinstance(c, dict):
                name = str(c.get("name") or "").strip()
                if name:
                    concept_names.append(name)
            elif isinstance(c, str):
                concept_names.append(c.strip())

        prompt = f"""You are a curriculum coverage planner.
Create a compact study-coverage checklist for one module.
Output ONLY valid JSON.

Blueprint: {blueprint.title}
Phase: {module.get("phase_index")} - {module.get("phase_title")}
Module: {module.get("code")} {module.get("title")}
Module summary: {module.get("summary") or "N/A"}
Learning objectives: {json.dumps(module.get("learning_objectives") or [], ensure_ascii=False)}
Concepts: {json.dumps(concept_names, ensure_ascii=False)}

Source excerpts:
{source_context}

Return JSON with this schema:
{{
  "must_cover": ["string"],
  "deep_dive_points": ["string"],
  "practice_targets": ["string"],
  "common_misconceptions": ["string"],
  "missing_source_coverage": ["string"]
}}"""

        try:
            content = await self._llm_text(
                llm=llm,
                model=model,
                messages=[
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=900,
                num_ctx=num_ctx,
            )
            parsed = self._parse_json(content)
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Coverage agent failed for {module.get('code')}: {e}")

        fallback = {
            "must_cover": [module.get("title")],
            "deep_dive_points": [module.get("summary")] if module.get("summary") else [],
            "practice_targets": [str(x) for x in (module.get("learning_objectives") or [])[:5]],
            "common_misconceptions": [],
            "missing_source_coverage": [],
        }
        return fallback

    async def _pareto_agent(
        self,
        llm,
        model: str,
        blueprint: LearningBlueprint,
        module: Dict[str, Any],
        source_context: str,
        source_cards: List[Dict[str, Any]],
        coverage_plan: Dict[str, Any],
        previous_guide: Optional[str],
        num_ctx: int,
    ) -> str:
        """Agent 2: Generate Pareto (80/20) overview."""
        source_list = "\n".join(
            f"- [{s['ref']}] {s['title']}" + (f" ({s['url']})" if s.get("url") else "")
            for s in source_cards[:12]
        ) or "- No explicit sources were linked."

        prior_text = (previous_guide or "").strip()
        prompt = f"""Write a high-signal Pareto study guide (80/20) for this module.
Keep it concise but concrete.
Use source references like [S1], [S2] when claims come from excerpts.

Module: {module.get("code")} {module.get("title")}
Phase: {module.get("phase_index")} - {module.get("phase_title")}
Blueprint: {blueprint.title}

Coverage checklist:
{json.dumps(coverage_plan, ensure_ascii=False)}

Available sources:
{source_list}

Source excerpts:
{source_context}

Existing guide (if present, improve and merge rather than rewrite from scratch):
{prior_text if prior_text else "N/A"}

Format in Markdown with sections:
1. Pareto Snapshot
2. Core Mental Model
3. Top 20 Percent Concepts
4. Fast Mastery Checklist
5. Common Pitfalls
6. 30-Minute Drill"""

        return await self._llm_text(
            llm=llm,
            model=model,
            messages=[
                {"role": "system", "content": "You write concise, practical study guides."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.35,
            max_tokens=8192,
            num_ctx=num_ctx,
        )

    async def _deep_guide_agent(
        self,
        llm,
        model: str,
        blueprint: LearningBlueprint,
        module: Dict[str, Any],
        source_context: str,
        source_cards: List[Dict[str, Any]],
        coverage_plan: Dict[str, Any],
        previous_guide: Optional[str],
        num_ctx: int,
    ) -> str:
        """Agent 3: Generate the deep, concise-comprehensive guide."""
        source_list = "\n".join(
            f"- [{s['ref']}] {s['title']}" + (f" ({s['url']})" if s.get("url") else "")
            for s in source_cards[:14]
        ) or "- No explicit sources were linked."

        prior_text = (previous_guide or "").strip()
        prompt = f"""Create a detailed, comprehensive study guide for this module.
Goal: cover the full module with practical understanding, not fluff.
Ground claims in provided source excerpts where possible and cite [Sx].

Module: {module.get("code")} {module.get("title")}
Phase: {module.get("phase_index")} - {module.get("phase_title")}
Blueprint: {blueprint.title}
Module summary: {module.get("summary") or "N/A"}
Objectives: {json.dumps(module.get("learning_objectives") or [], ensure_ascii=False)}

Coverage checklist:
{json.dumps(coverage_plan, ensure_ascii=False)}

Sources:
{source_list}

Source excerpts:
{source_context}

Existing deep guide (if present, enhance with new source-backed details):
{prior_text if prior_text else "N/A"}

Write Markdown with sections:
1. Why This Module Matters
2. Concept Map In Words
3. Deep Explanations (cover all must_cover + deep_dive_points)
4. Worked Examples / Thought Experiments
5. Self-Test Questions (with short answers)
6. Mastery Rubric (what "good" looks like)
7. Open Gaps / What To Read Next"""

        return await self._llm_text(
            llm=llm,
            model=model,
            messages=[
                {"role": "system", "content": "You produce accurate, comprehensive, high-coverage study guides. Be thorough — cover every concept in depth."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=16384,
            num_ctx=num_ctx,
        )

    async def _critic_agent(
        self,
        llm,
        model: str,
        module: Dict[str, Any],
        coverage_plan: Dict[str, Any],
        deep_guide: str,
        num_ctx: int,
    ) -> Dict[str, Any]:
        """Agent 4: Critic for coverage and actionable revisions."""
        prompt = f"""Review this study guide for module coverage quality.
Return ONLY valid JSON.

Module: {module.get("code")} {module.get("title")}
Required coverage:
{json.dumps(coverage_plan, ensure_ascii=False)}

Guide text:
{deep_guide}

Return:
{{
  "coverage_score": 0.0,
  "missing_points": ["string"],
  "revision_actions": ["string"],
  "strengths": ["string"]
}}"""

        try:
            content = await self._llm_text(
                llm=llm,
                model=model,
                messages=[
                    {"role": "system", "content": "You are a strict reviewer. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=700,
                num_ctx=num_ctx,
            )
            parsed = self._parse_json(content)
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Critic agent failed for {module.get('code')}: {e}")

        return {
            "coverage_score": 0.75,
            "missing_points": [],
            "revision_actions": [],
            "strengths": [],
        }

    async def _revise_deep_guide(
        self,
        llm,
        model: str,
        module: Dict[str, Any],
        deep_guide: str,
        critic_review: Dict[str, Any],
        num_ctx: int,
    ) -> str:
        """One revision pass when critic score is low."""
        prompt = f"""Revise this study guide to fix missing coverage while staying concise.
Keep structure and improve weak areas.

Module: {module.get("code")} {module.get("title")}
Critic feedback:
{json.dumps(critic_review, ensure_ascii=False)}

Current guide:
{deep_guide}

Return revised Markdown only."""

        try:
            return await self._llm_text(
                llm=llm,
                model=model,
                messages=[
                    {"role": "system", "content": "You improve technical writing with precise revisions. Be thorough."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=16384,
                num_ctx=num_ctx,
            )
        except Exception as e:
            logger.warning(f"Deep guide revision failed for {module.get('code')}: {e}")
            return deep_guide

    async def _llm_text(
        self,
        llm,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        num_ctx: int,
    ) -> str:
        """Call background LLM and return response text."""
        response = await llm.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            options={"num_ctx": num_ctx},
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
        """Parse JSON payload from plain text or fenced code blocks."""
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
        """Check whether a guide job has been marked for cancellation."""
        status = db.query(LearningGuideJob.status).filter(
            LearningGuideJob.id == job_id
        ).scalar()
        return status in {"cancelling", "cancelled"}

    def _raise_if_cancel_requested(self, db: Session, job_id: str):
        """Raise if the job has been marked for cancellation."""
        if self._is_cancel_requested(db=db, job_id=job_id):
            raise JobCancelledError("Guide generation cancelled")

    def _mark_cancelled(self, job: LearningGuideJob, db: Session):
        """Persist a job as cancelled."""
        job.status = "cancelled"
        job.current_step = "Cancelled"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()


learning_guide_service = LearningGuideService()
