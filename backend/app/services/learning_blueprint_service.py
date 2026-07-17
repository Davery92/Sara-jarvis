"""
Learning Blueprint Service
Parses long-form learning plans and materializes them into the Learning System.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.learning import (
    LearningBlueprint,
    LearningProgress,
    LearningTopic,
    TopicConnection,
    TopicScratchpad,
    TopicSource,
)

logger = logging.getLogger(__name__)


class LearningBlueprintService:
    """Parse and materialize imported learning blueprints."""

    _PHASE_RE = re.compile(
        r"(?im)^\s{0,3}(?:#{1,6}\s*)?phase\s+(\d+)\s*[:\-]\s*(.+?)(?:\s*\(([^)]+)\))?\s*$"
    )
    _MODULE_RE = re.compile(
        r"(?im)^\s*(?:module\s+)?(\d{1,2}\.\d{1,2})(?:\s*[-:.)]\s*|\s+)([A-Za-z][^\n]{1,220})\s*$"
    )
    _WEEK_RE = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?week\s+(\d{1,2})(?:\s*[-:.)]\s*|\s+)([A-Za-z][^\n]{1,220})\s*$"
    )

    async def parse_blueprint_text(
        self,
        text: str,
        source_format: str = "markdown",
        parse_mode: str = "balanced",
        pace_mode: str = "self_directed",
        title_override: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], float]:
        """Parse raw blueprint text into structured JSON."""
        if not text or not text.strip():
            raise ValueError("Blueprint text is empty")

        deterministic = self._parse_deterministic(
            text=text,
            source_format=source_format,
            pace_mode=pace_mode,
            title_override=title_override,
        )

        llm_parsed = await self._parse_with_llm(
            text=text,
            source_format=source_format,
            parse_mode=parse_mode,
            pace_mode=pace_mode,
            title_override=title_override,
        )
        if llm_parsed:
            normalized = self._normalize_parsed_payload(
                llm_parsed, text, source_format, pace_mode, title_override
            )
            normalized.setdefault("metadata", {})
            llm_modules = self._count_modules(normalized)
            det_modules = self._count_modules(deterministic)
            if det_modules > llm_modules:
                deterministic.setdefault("metadata", {})
                deterministic["metadata"]["parser"] = "deterministic"
                deterministic["metadata"]["selection"] = "deterministic_outperformed_llm"
                return deterministic, 0.84

            normalized["metadata"]["parser"] = "llm"
            return normalized, 0.92

        deterministic.setdefault("metadata", {})
        deterministic["metadata"]["parser"] = "deterministic"
        return deterministic, 0.75

    async def _parse_with_llm(
        self,
        text: str,
        source_format: str,
        parse_mode: str,
        pace_mode: str,
        title_override: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """LLM-first parser. Returns None on failure."""
        try:
            from app.core.llm import llm_client

            prompt = f"""Convert the following study plan into strict JSON.
Output ONLY valid JSON. No markdown, no commentary.

Schema:
{{
  "blueprint": {{
    "title": "string",
    "subtitle": "string|null",
    "description": "string|null",
    "estimated_duration_weeks": number|null,
    "pace_mode": "{pace_mode}",
    "source_format": "{source_format}"
  }},
  "phases": [
    {{
      "index": number,
      "title": "string",
      "duration_label": "string|null",
      "summary": "string|null",
      "modules": [
        {{
          "code": "string",
          "title": "string",
          "summary": "string|null",
          "learning_objectives": ["string"],
          "concepts": [{{"name":"string","tags":["string"]}}],
          "resources": [
            {{
              "title": "string",
              "type": "textbook|course|paper|book|software|website|other",
              "url": "string|null",
              "notes": "string|null",
              "priority": "high|medium|low"
            }}
          ]
        }}
      ]
    }}
  ],
  "connections": [
    {{
      "from_module_code": "string",
      "to_module_code": "string",
      "type": "prerequisite|related|builds_on|contrasts|applies_to",
      "strength": number,
      "reason": "string|null"
    }}
  ],
  "metadata": {{
    "warnings": ["string"]
  }}
}}

Parse mode: {parse_mode}
Title override: {title_override or ""}

Plan text:
{text[:50000]}
"""
            result = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not content:
                return None

            extracted = self._extract_json_blob(content)
            return json.loads(extracted) if extracted else None
        except Exception as e:
            logger.info(f"Blueprint LLM parse fallback: {e}")
            return None

    def _parse_deterministic(
        self,
        text: str,
        source_format: str,
        pace_mode: str,
        title_override: Optional[str],
    ) -> Dict[str, Any]:
        """Regex/rule-based fallback parser for long learning plans."""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = title_override or (lines[0][:255] if lines else "Imported Blueprint")
        subtitle = lines[1][:255] if len(lines) > 1 and not lines[1].lower().startswith("phase ") else None
        description = lines[2][:500] if len(lines) > 2 and not lines[2].lower().startswith("phase ") else None

        phases = self._extract_phases_and_modules(text)
        if not phases:
            phases = self._infer_phases_without_headers(
                text=text,
                blueprint_title=title,
                blueprint_description=description,
            )

        connections = self._build_default_connections(phases)
        return {
            "blueprint": {
                "title": title,
                "subtitle": subtitle,
                "description": description,
                "estimated_duration_weeks": self._estimate_duration_weeks(text),
                "pace_mode": pace_mode,
                "source_format": source_format,
            },
            "phases": phases,
            "connections": connections,
            "metadata": {"warnings": []},
        }

    def _extract_phases_and_modules(self, text: str) -> List[Dict[str, Any]]:
        matches = list(self._PHASE_RE.finditer(text))
        phases: List[Dict[str, Any]] = []
        if not matches:
            return phases

        for idx, match in enumerate(matches):
            phase_index = int(match.group(1))
            phase_title = match.group(2).strip()[:255]
            duration_label = (match.group(3) or "").strip() or None
            body_start = match.end()
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            phase_body = text[body_start:body_end].strip()

            modules = self._extract_modules_for_phase(phase_index, phase_title, phase_body)
            phase_summary = self._extract_summary_text(phase_body)

            phases.append({
                "index": phase_index,
                "title": phase_title,
                "duration_label": duration_label,
                "summary": phase_summary,
                "modules": modules,
            })
        return phases

    def _extract_modules_for_phase(
        self,
        phase_index: int,
        phase_title: str,
        phase_body: str,
    ) -> List[Dict[str, Any]]:
        modules = []
        segments = self._extract_module_segments(phase_body)
        if not segments:
            week_segments = self._extract_week_segments(phase_body)
            if week_segments:
                for week in week_segments:
                    code = f"{phase_index}.{week['week_index']}"
                    body = week["body"]
                    modules.append({
                        "code": code,
                        "title": week["title"][:255],
                        "summary": self._extract_summary_text(body),
                        "learning_objectives": self._extract_objectives(body),
                        "concepts": self._extract_concepts(body),
                        "resources": self._parse_resources(body),
                    })
                modules.sort(key=lambda m: self._module_sort_key(str(m.get("code") or "")))
                return modules
            return [{
                "code": f"{phase_index}.1",
                "title": phase_title,
                "summary": self._extract_summary_text(phase_body),
                "learning_objectives": self._extract_objectives(phase_body),
                "concepts": self._extract_concepts(phase_body),
                "resources": self._parse_resources(phase_body),
            }]

        for seg in segments:
            code = seg["code"]
            title = seg["title"][:255]
            body = seg["body"]

            major = self._module_sort_key(code)[0]
            if major not in (9999, phase_index):
                continue

            modules.append({
                "code": code,
                "title": title,
                "summary": self._extract_summary_text(body),
                "learning_objectives": self._extract_objectives(body),
                "concepts": self._extract_concepts(body),
                "resources": self._parse_resources(body),
            })

        if not modules:
            return [{
                "code": f"{phase_index}.1",
                "title": phase_title,
                "summary": self._extract_summary_text(phase_body),
                "learning_objectives": self._extract_objectives(phase_body),
                "concepts": self._extract_concepts(phase_body),
                "resources": self._parse_resources(phase_body),
            }]

        modules.sort(key=lambda m: self._module_sort_key(str(m.get("code") or "")))
        return modules

    def _extract_module_segments(self, text: str) -> List[Dict[str, str]]:
        matches = list(self._MODULE_RE.finditer(text))
        segments: List[Dict[str, str]] = []
        for idx, match in enumerate(matches):
            code = match.group(1).strip()
            title = " ".join(match.group(2).split()).strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            segments.append({
                "code": code,
                "title": title,
                "body": body,
            })
        return segments

    def _extract_week_segments(self, text: str) -> List[Dict[str, Any]]:
        matches = list(self._WEEK_RE.finditer(text))
        segments: List[Dict[str, Any]] = []
        for idx, match in enumerate(matches):
            week_index = int(match.group(1))
            title = " ".join(match.group(2).split()).strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            segments.append({
                "week_index": week_index,
                "title": title,
                "body": body,
            })
        return segments

    def _module_sort_key(self, code: str) -> Tuple[int, int]:
        try:
            major_str, minor_str = str(code).split(".", 1)
            return int(major_str), int(re.sub(r"\D+", "", minor_str) or 0)
        except Exception:
            return (9999, 9999)

    def _infer_phases_without_headers(
        self,
        text: str,
        blueprint_title: str,
        blueprint_description: Optional[str],
    ) -> List[Dict[str, Any]]:
        segments = self._extract_module_segments(text)
        if not segments:
            return [{
                "index": 1,
                "title": "Imported Plan",
                "duration_label": None,
                "summary": "Imported as a single phase (no explicit phase/module headers found).",
                "modules": [{
                    "code": "1.1",
                    "title": blueprint_title,
                    "summary": blueprint_description or "Imported plan content",
                    "learning_objectives": [],
                    "concepts": [],
                    "resources": self._parse_resources(text),
                }],
            }]

        grouped: Dict[int, List[Dict[str, str]]] = {}
        for seg in segments:
            major, _minor = self._module_sort_key(seg["code"])
            grouped.setdefault(major if major < 9999 else 1, []).append(seg)

        title_hint_match = re.search(r"(?i)\bphase\s+(\d+)\b\s*[:\-]?\s*(.*)", blueprint_title or "")
        title_hint_index = int(title_hint_match.group(1)) if title_hint_match else None
        title_hint_label = (title_hint_match.group(2).strip() if title_hint_match else "") or None

        phases: List[Dict[str, Any]] = []
        for phase_index in sorted(grouped.keys()):
            phase_segments = grouped[phase_index]
            modules = []
            for seg in sorted(phase_segments, key=lambda s: self._module_sort_key(s["code"])):
                body = seg["body"]
                modules.append({
                    "code": seg["code"],
                    "title": seg["title"][:255],
                    "summary": self._extract_summary_text(body),
                    "learning_objectives": self._extract_objectives(body),
                    "concepts": self._extract_concepts(body),
                    "resources": self._parse_resources(body),
                })

            phase_title = f"Phase {phase_index}"
            if title_hint_index == phase_index and title_hint_label:
                phase_title = title_hint_label[:255]

            phase_summary = self._extract_summary_text("\n\n".join(seg["body"] for seg in phase_segments))
            phases.append({
                "index": phase_index,
                "title": phase_title,
                "duration_label": None,
                "summary": phase_summary,
                "modules": modules,
            })

        return phases

    def _extract_summary_text(self, text: str) -> str:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for paragraph in paragraphs:
            low = paragraph.lower()
            if low.startswith("key resources"):
                continue
            if re.match(r"^\d+\.\d+\s+", paragraph):
                continue
            clean = " ".join(paragraph.split())
            if clean:
                return clean[:700]
        return ""

    def _extract_objectives(self, text: str) -> List[str]:
        bullet_lines: List[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(("-", "•", "*")):
                bullet_lines.append(line.lstrip("-•* ").strip())
        if bullet_lines:
            return bullet_lines[:8]

        objective_like = re.findall(r"(?m)^([A-Z][^:\n]{3,120}):", text)
        return list(dict.fromkeys(objective_like))[:8]

    def _extract_concepts(self, text: str) -> List[Dict[str, Any]]:
        concepts = []
        found = re.findall(r"(?m)^([A-Z][^:\n]{2,140}):", text)
        for item in found[:15]:
            name = " ".join(item.split())[:140]
            if name and len(name) > 2:
                concepts.append({"name": name, "tags": []})
        return concepts

    def _parse_resources(self, text: str) -> List[Dict[str, Any]]:
        resources: List[Dict[str, Any]] = []
        if "key resources" not in text.lower():
            return resources

        lines = text.splitlines()
        collecting = False
        for raw in lines:
            line = raw.strip()
            if not line:
                if collecting and resources:
                    break
                continue

            if line.lower().startswith("key resources"):
                collecting = True
                continue

            if not collecting:
                continue

            if line.lower().startswith("resource") and ("type" in line.lower()):
                continue

            # Tab-separated row
            if "\t" in line:
                cols = [c.strip() for c in re.split(r"\t+", line) if c.strip()]
                if len(cols) >= 2:
                    resources.append({
                        "title": cols[0][:255],
                        "type": self._normalize_resource_type(cols[1] if len(cols) > 1 else "other"),
                        "url": None,
                        "notes": cols[2][:500] if len(cols) > 2 else None,
                        "priority": "medium",
                    })
                    continue

            # Markdown table row
            if "|" in line and line.count("|") >= 2:
                cols = [c.strip() for c in line.strip("|").split("|")]
                if len(cols) >= 2 and cols[0].lower() != "resource":
                    resources.append({
                        "title": cols[0][:255],
                        "type": self._normalize_resource_type(cols[1]),
                        "url": None,
                        "notes": cols[2][:500] if len(cols) > 2 else None,
                        "priority": "medium",
                    })
                    continue

            # Fallback row format: "Title — Type — Notes"
            if " — " in line:
                cols = [c.strip() for c in line.split(" — ")]
                if len(cols) >= 2:
                    resources.append({
                        "title": cols[0][:255],
                        "type": self._normalize_resource_type(cols[1]),
                        "url": None,
                        "notes": cols[2][:500] if len(cols) > 2 else None,
                        "priority": "medium",
                    })

        # de-dup by title
        seen = set()
        deduped = []
        for r in resources:
            key = r["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        return deduped[:30]

    def _normalize_resource_type(self, raw: str) -> str:
        value = (raw or "").strip().lower()
        if "textbook" in value:
            return "textbook"
        if "course" in value:
            return "course"
        if "paper" in value:
            return "paper"
        if "book" in value:
            return "book"
        if "software" in value or "tool" in value:
            return "software"
        if "website" in value or "docs" in value:
            return "website"
        return "other"

    def _build_default_connections(self, phases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordered_modules: List[Tuple[int, str, str]] = []
        for phase in sorted(phases, key=lambda p: p.get("index", 999)):
            pidx = int(phase.get("index", 0) or 0)
            for module in phase.get("modules", []):
                code = module.get("code")
                if code:
                    ordered_modules.append((pidx, code, module.get("title", "")))

        ordered_modules.sort(
            key=lambda item: (
                item[0],
                tuple(int(x) if x.isdigit() else 0 for x in item[1].split(".")[:2]),
            )
        )

        edges: List[Dict[str, Any]] = []
        for i in range(1, len(ordered_modules)):
            prev = ordered_modules[i - 1]
            cur = ordered_modules[i]
            edges.append({
                "from_module_code": prev[1],
                "to_module_code": cur[1],
                "type": "prerequisite",
                "strength": 0.85,
                "reason": "Sequential dependency from imported learning plan",
            })
        return edges

    def _estimate_duration_weeks(self, text: str) -> Optional[int]:
        m = re.search(r"estimated\s+total\s+time\s*:\s*([^\n.]+)", text, re.IGNORECASE)
        if not m:
            return None
        value = m.group(1).strip().lower()

        range_match = re.search(r"(\d+)\s*[–-]\s*(\d+)\s*(month|months|week|weeks)", value)
        if range_match:
            lo = int(range_match.group(1))
            hi = int(range_match.group(2))
            unit = range_match.group(3)
            avg = (lo + hi) // 2
            if unit.startswith("month"):
                return avg * 4
            return avg

        single_match = re.search(r"(\d+)\s*(month|months|week|weeks)", value)
        if single_match:
            num = int(single_match.group(1))
            unit = single_match.group(2)
            if unit.startswith("month"):
                return num * 4
            return num
        return None

    def _extract_json_blob(self, content: str) -> Optional[str]:
        text = content.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                if candidate.startswith("{") and candidate.endswith("}"):
                    return candidate

        match = re.search(r"\{[\s\S]*\}", text)
        return match.group(0) if match else None

    def _normalize_parsed_payload(
        self,
        payload: Dict[str, Any],
        raw_text: str,
        source_format: str,
        pace_mode: str,
        title_override: Optional[str],
    ) -> Dict[str, Any]:
        blueprint = payload.get("blueprint") or {}
        title = title_override or blueprint.get("title") or "Imported Blueprint"
        normalized = {
            "blueprint": {
                "title": str(title)[:255],
                "subtitle": blueprint.get("subtitle"),
                "description": blueprint.get("description"),
                "estimated_duration_weeks": blueprint.get("estimated_duration_weeks"),
                "pace_mode": blueprint.get("pace_mode") or pace_mode,
                "source_format": blueprint.get("source_format") or source_format,
            },
            "phases": payload.get("phases") or [],
            "connections": payload.get("connections") or [],
            "metadata": payload.get("metadata") or {"warnings": []},
        }

        if not normalized["phases"]:
            return self._parse_deterministic(
                text=raw_text,
                source_format=source_format,
                pace_mode=pace_mode,
                title_override=title_override,
            )

        for idx, phase in enumerate(normalized["phases"], start=1):
            phase_idx = int(phase.get("index", 0) or 0)
            if phase_idx <= 0:
                phase_idx = idx
            phase["index"] = phase_idx
            phase["title"] = str(phase.get("title") or f"Phase {phase['index']}")[:255]
            phase.setdefault("duration_label", None)
            phase.setdefault("summary", "")
            phase.setdefault("modules", [])

            for mod_idx, module in enumerate(phase["modules"], start=1):
                module["code"] = self._normalize_module_code(
                    str(module.get("code") or ""),
                    phase["index"],
                    mod_idx,
                )
                module["title"] = str(module.get("title") or module["code"])[:255]
                module.setdefault("summary", "")
                module.setdefault("learning_objectives", [])
                module.setdefault("concepts", [])
                module.setdefault("resources", [])

                cleaned_resources = []
                for r in module["resources"]:
                    cleaned_resources.append({
                        "title": str(r.get("title") or "Untitled Resource")[:255],
                        "type": self._normalize_resource_type(r.get("type", "other")),
                        "url": r.get("url"),
                        "notes": (r.get("notes") or "")[:500] or None,
                        "priority": (r.get("priority") or "medium").lower(),
                    })
                module["resources"] = cleaned_resources

        repaired = self._repair_phase_module_alignment(
            normalized=normalized,
            raw_text=raw_text,
            title_override=title_override,
            source_format=source_format,
            pace_mode=pace_mode,
        )
        return repaired

    def _normalize_module_code(self, code: str, phase_index: int, module_position: int) -> str:
        clean = str(code or "").strip()
        if re.match(r"^\d+\.\d+$", clean):
            return clean

        code_match = re.search(r"(\d+\.\d+)", clean)
        if code_match:
            return code_match.group(1)

        return f"{phase_index}.{module_position}"

    def _count_modules(self, payload: Dict[str, Any]) -> int:
        return sum(len((phase or {}).get("modules") or []) for phase in (payload.get("phases") or []))

    def _repair_phase_module_alignment(
        self,
        normalized: Dict[str, Any],
        raw_text: str,
        title_override: Optional[str],
        source_format: str,
        pace_mode: str,
    ) -> Dict[str, Any]:
        phase_rows = normalized.get("phases") or []
        if not phase_rows:
            return self._parse_deterministic(
                text=raw_text,
                source_format=source_format,
                pace_mode=pace_mode,
                title_override=title_override,
            )

        phase_meta: Dict[int, Dict[str, Any]] = {}
        grouped_modules: Dict[int, List[Dict[str, Any]]] = {}

        for idx, phase in enumerate(phase_rows, start=1):
            phase_index = int(phase.get("index", idx) or idx)
            if phase_index <= 0:
                phase_index = idx
            phase_meta.setdefault(phase_index, {
                "title": str(phase.get("title") or f"Phase {phase_index}")[:255],
                "duration_label": phase.get("duration_label"),
                "summary": phase.get("summary") or "",
            })

            modules = phase.get("modules") or []
            for mod_pos, module in enumerate(modules, start=1):
                code = self._normalize_module_code(str(module.get("code") or ""), phase_index, mod_pos)
                major = self._module_sort_key(code)[0]
                target_phase = phase_index if major == 9999 else major
                m = dict(module)
                m["code"] = code
                m["title"] = str(m.get("title") or code)[:255]
                m.setdefault("summary", "")
                m.setdefault("learning_objectives", [])
                m.setdefault("concepts", [])
                m.setdefault("resources", [])
                grouped_modules.setdefault(target_phase, []).append(m)

        phase_indexes = sorted(set(list(phase_meta.keys()) + list(grouped_modules.keys())))
        rebuilt_phases: List[Dict[str, Any]] = []
        for phase_index in phase_indexes:
            meta = phase_meta.get(phase_index, {})
            modules = grouped_modules.get(phase_index, [])
            modules.sort(key=lambda m: self._module_sort_key(str(m.get("code") or "")))

            fixed_modules = []
            for mod_idx, module in enumerate(modules, start=1):
                code = self._normalize_module_code(str(module.get("code") or ""), phase_index, mod_idx)
                major, _minor = self._module_sort_key(code)
                if major != phase_index:
                    code = f"{phase_index}.{mod_idx}"
                module["code"] = code
                fixed_modules.append(module)

            rebuilt_phases.append({
                "index": phase_index,
                "title": str(meta.get("title") or f"Phase {phase_index}")[:255],
                "duration_label": meta.get("duration_label"),
                "summary": meta.get("summary") or "",
                "modules": fixed_modules,
            })

        repaired = dict(normalized)
        repaired["phases"] = rebuilt_phases
        if self._count_modules(repaired) == 0:
            return self._parse_deterministic(
                text=raw_text,
                source_format=source_format,
                pace_mode=pace_mode,
                title_override=title_override,
            )
        return repaired

    def materialize_blueprint(
        self,
        blueprint: LearningBlueprint,
        user_id: str,
        db: Session,
        mode: str = "adaptive",
        create_sources: bool = True,
        create_connections: bool = True,
        create_curriculum: bool = True,
        seed_reviews: bool = True,
        replace_existing: bool = False,
        parent_topic_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create topics/resources/connections/curriculum from parsed blueprint."""
        if blueprint.user_id != user_id:
            raise ValueError("Blueprint does not belong to user")

        parsed = blueprint.parsed_json or {}
        phases = parsed.get("phases") or []
        if not phases:
            raise ValueError("Blueprint has no phases to materialize")

        existing_root = (blueprint.meta or {}).get("root_topic_id")
        if blueprint.status == "materialized" and existing_root and not replace_existing:
            return {
                "status": "already_materialized",
                "blueprint_id": blueprint.id,
                "root_topic_id": existing_root,
                "created": {
                    "topics": 0,
                    "sources": 0,
                    "connections": 0,
                    "curricula": 0,
                    "seeded_reviews": 0,
                },
            }

        created = {
            "topics": 0,
            "sources": 0,
            "connections": 0,
            "curricula": 0,
            "seeded_reviews": 0,
        }

        now = datetime.now(timezone.utc)
        parent_topic: Optional[LearningTopic] = None
        if parent_topic_id:
            parent_topic = db.query(LearningTopic).filter(
                LearningTopic.id == parent_topic_id,
                LearningTopic.user_id == user_id,
            ).first()
            if not parent_topic:
                raise ValueError("Parent topic not found")

        root_topic_created = False
        if parent_topic:
            # When a parent is provided, materialize phases/modules directly under that topic.
            root_topic = parent_topic
        else:
            root_topic = LearningTopic(
                id=str(uuid.uuid4()),
                user_id=user_id,
                blueprint_id=blueprint.id,
                parent_id=None,
                title=blueprint.title,
                description=blueprint.description,
                status="active",
                priority=10,
                meta={
                    "blueprint_id": blueprint.id,
                    "blueprint_node_type": "root",
                    "materialize_mode": mode,
                    "materialize_parent_topic_id": None,
                },
            )
            db.add(root_topic)
            created["topics"] += 1
            root_topic_created = True

        module_topic_ids: Dict[str, str] = {}

        sorted_phases = sorted(phases, key=lambda p: int(p.get("index", 9999)))
        for phase in sorted_phases:
            phase_index = int(phase.get("index", 0) or 0)
            phase_title = phase.get("title") or f"Phase {phase_index}"
            phase_topic = LearningTopic(
                id=str(uuid.uuid4()),
                user_id=user_id,
                blueprint_id=blueprint.id,
                parent_id=root_topic.id,
                title=phase_title[:255],
                description=phase.get("summary") or phase.get("duration_label"),
                status="active",
                priority=max(1, 10 - phase_index),
                meta={
                    "blueprint_id": blueprint.id,
                    "blueprint_node_type": "phase",
                    "blueprint_phase_index": phase_index,
                    "blueprint_phase_duration": phase.get("duration_label"),
                },
            )
            db.add(phase_topic)
            created["topics"] += 1

            modules = phase.get("modules") or []
            for mod_idx, module in enumerate(modules):
                module_code = str(module.get("code") or f"{phase_index}.{mod_idx + 1}")
                module_title = str(module.get("title") or module_code)[:255]
                module_summary = (module.get("summary") or "").strip()
                objectives = module.get("learning_objectives") or []
                concepts = module.get("concepts") or []

                objective_text = ""
                if objectives:
                    objective_text = "\n\nObjectives:\n" + "\n".join(
                        f"- {str(obj)[:240]}" for obj in objectives[:8]
                    )

                module_topic = LearningTopic(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    blueprint_id=blueprint.id,
                    parent_id=phase_topic.id,
                    title=module_title,
                    description=(module_summary + objective_text).strip()[:4000] or None,
                    status="active",
                    priority=8,
                    meta={
                        "blueprint_id": blueprint.id,
                        "blueprint_node_type": "module",
                        "blueprint_phase_index": phase_index,
                        "blueprint_module_code": module_code,
                        "blueprint_learning_objectives": objectives[:20],
                        "blueprint_concepts": concepts[:50],
                    },
                )
                db.add(module_topic)
                module_topic_ids[module_code] = module_topic.id
                created["topics"] += 1

                if create_sources:
                    for resource in module.get("resources") or []:
                        title = str(resource.get("title") or "Untitled Resource")[:500]
                        url = resource.get("url")
                        source_type = "web" if url else "note"
                        fetch_status = "pending" if url else "fetched"
                        notes = resource.get("notes")

                        source = TopicSource(
                            id=str(uuid.uuid4()),
                            topic_id=module_topic.id,
                            user_id=user_id,
                            source_type=source_type,
                            url=url,
                            title=title,
                            content_text=notes if source_type == "note" else None,
                            fetch_status=fetch_status,
                            meta={
                                "blueprint_id": blueprint.id,
                                "blueprint_resource_type": resource.get("type", "other"),
                                "blueprint_priority": resource.get("priority", "medium"),
                            },
                        )
                        db.add(source)
                        created["sources"] += 1

                if seed_reviews and concepts:
                    for concept in concepts[:3]:
                        concept_name = ""
                        if isinstance(concept, dict):
                            concept_name = str(concept.get("name") or "").strip()
                        elif isinstance(concept, str):
                            concept_name = concept.strip()
                        if not concept_name:
                            continue

                        progress = LearningProgress(
                            id=str(uuid.uuid4()),
                            user_id=user_id,
                            topic_id=module_topic.id,
                            concept=concept_name[:500],
                            ease_factor=2.5,
                            interval_days=1,
                            repetitions=0,
                            next_review_at=now,
                            quality_history=[],
                        )
                        db.add(progress)
                        created["seeded_reviews"] += 1

            if create_curriculum and modules:
                steps = []
                for step_idx, module in enumerate(modules):
                    steps.append({
                        "index": step_idx,
                        "concept": str(module.get("title") or f"Module {step_idx + 1}")[:255],
                        "description": (module.get("summary") or "")[:800],
                        "action_type": "study",
                        "estimated_time": "60-120 min",
                        "reason": "Imported from blueprint phase sequence",
                        "status": "active" if step_idx == 0 else "pending",
                        "completed_at": None,
                    })

                scratchpad = TopicScratchpad(
                    id=str(uuid.uuid4()),
                    topic_id=phase_topic.id,
                    user_id=user_id,
                    content="",
                    session_state={},
                    curriculum={
                        "generated_at": now.isoformat(),
                        "summary": phase.get("summary") or f"Curriculum for {phase_title}",
                        "steps": steps,
                    },
                )
                db.add(scratchpad)
                created["curricula"] += 1

        if create_connections:
            seen_edges = set()
            for conn in parsed.get("connections") or []:
                from_code = str(conn.get("from_module_code") or "").strip()
                to_code = str(conn.get("to_module_code") or "").strip()
                if not from_code or not to_code:
                    continue
                from_id = module_topic_ids.get(from_code)
                to_id = module_topic_ids.get(to_code)
                if not from_id or not to_id or from_id == to_id:
                    continue

                conn_type = str(conn.get("type") or "prerequisite").strip().lower()
                if conn_type not in {"prerequisite", "related", "builds_on", "contrasts", "applies_to"}:
                    conn_type = "prerequisite"
                edge_key = (from_id, to_id, conn_type)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                topic_conn = TopicConnection(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    source_topic_id=from_id,
                    target_topic_id=to_id,
                    connection_type=conn_type,
                    strength=float(conn.get("strength", 0.8) or 0.8),
                    description=conn.get("reason"),
                    auto_generated=True,
                    confirmed=False,
                )
                db.add(topic_conn)
                created["connections"] += 1

        # Match any existing uploaded sources against blueprint resources
        matched_sources = 0
        try:
            matched_sources = self._match_existing_sources_to_blueprint(
                blueprint=blueprint, root_topic_id=root_topic.id, user_id=user_id, db=db
            )
        except Exception as e:
            logger.warning(f"Post-materialize source matching failed: {e}")

        meta = dict(blueprint.meta or {})
        meta["root_topic_id"] = root_topic.id
        meta["root_topic_created"] = root_topic_created
        if parent_topic:
            meta["parent_topic_id"] = parent_topic.id
        meta["materialization"] = {
            "mode": mode,
            "created": created,
            "matched_sources": matched_sources,
            "completed_at": now.isoformat(),
        }
        blueprint.meta = meta
        blueprint.status = "materialized"
        blueprint.materialized_at = now
        blueprint.updated_at = now

        db.commit()

        return {
            "status": "materialized",
            "blueprint_id": blueprint.id,
            "root_topic_id": root_topic.id,
            "root_topic_created": root_topic_created,
            "parent_topic_id": parent_topic.id if parent_topic else None,
            "created": created,
            "matched_sources": matched_sources,
        }

    def compute_blueprint_progress(
        self,
        blueprint: LearningBlueprint,
        user_id: str,
        db: Session,
    ) -> Dict[str, Any]:
        """Compute progress for a materialized blueprint."""
        if blueprint.user_id != user_id:
            raise ValueError("Blueprint does not belong to user")

        phases = (blueprint.parsed_json or {}).get("phases") or []
        ordered = []
        for phase in sorted(phases, key=lambda p: int(p.get("index", 9999))):
            pidx = int(phase.get("index", 0) or 0)
            for module in phase.get("modules") or []:
                code = str(module.get("code") or "")
                if code:
                    ordered.append({
                        "phase_index": pidx,
                        "module_code": code,
                        "module_title": module.get("title"),
                    })

        if not ordered:
            return {
                "blueprint_id": blueprint.id,
                "completed_modules": 0,
                "total_modules": 0,
                "percent_complete": 0.0,
                "current_phase": None,
                "current_module_code": None,
                "current_module_title": None,
            }

        module_topics = db.query(LearningTopic).filter(
            LearningTopic.user_id == user_id,
            LearningTopic.blueprint_id == blueprint.id,
        ).all()
        by_code: Dict[str, LearningTopic] = {}
        for topic in module_topics:
            meta = topic.meta or {}
            if meta.get("blueprint_node_type") == "module":
                code = meta.get("blueprint_module_code")
                if code:
                    by_code[str(code)] = topic

        completed = 0
        current = None
        for item in ordered:
            topic = by_code.get(item["module_code"])
            is_done = False
            if topic:
                is_done = topic.status == "completed" or (topic.mastery_level or 0.0) >= 0.85
            if is_done:
                completed += 1
            elif current is None:
                current = item

        total = len(ordered)
        percent = round((completed / total) * 100.0, 2) if total else 0.0
        return {
            "blueprint_id": blueprint.id,
            "completed_modules": completed,
            "total_modules": total,
            "percent_complete": percent,
            "current_phase": current["phase_index"] if current else None,
            "current_module_code": current["module_code"] if current else None,
            "current_module_title": current["module_title"] if current else None,
        }

    def _match_existing_sources_to_blueprint(
        self,
        blueprint: LearningBlueprint,
        root_topic_id: str,
        user_id: str,
        db: Session,
    ) -> int:
        """After materialization, match any existing uploaded sources to blueprint resources."""
        from app.services.learning_source_service import learning_source_service

        # Find all sources under the root topic tree
        all_topic_ids = [root_topic_id]
        children = db.query(LearningTopic.id).filter(
            LearningTopic.parent_id == root_topic_id,
            LearningTopic.user_id == user_id,
        ).all()
        for (tid,) in children:
            all_topic_ids.append(tid)
            grandchildren = db.query(LearningTopic.id).filter(
                LearningTopic.parent_id == tid,
                LearningTopic.user_id == user_id,
            ).all()
            all_topic_ids.extend(gc_id for (gc_id,) in grandchildren)

        sources = db.query(TopicSource).filter(
            TopicSource.topic_id.in_(all_topic_ids),
            TopicSource.user_id == user_id,
        ).all()

        matched = 0
        for source in sources:
            # Skip if already matched
            if (source.meta or {}).get("blueprint_matched_resources"):
                continue
            matches = learning_source_service.match_source_to_blueprint(source, db)
            if matches:
                matched += 1

        return matched


learning_blueprint_service = LearningBlueprintService()
