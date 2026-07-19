"""
Surface spec validation.

A surface spec is a closed vocabulary of typed components. Validation is strict
and returns corrective error messages back through the tool loop (same posture
as text-format tool-call salvage) so the model can retry in-turn. No free-form
HTML/JS ever — markdown in, typed JSON out.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal, Union
from pydantic import BaseModel, Field, ValidationError, field_validator


# --- Component models -------------------------------------------------------

class MarkdownComponent(BaseModel):
    type: Literal["markdown"]
    text: str


class ChecklistItem(BaseModel):
    id: str
    label: str
    checked: bool = False


class ChecklistComponent(BaseModel):
    type: Literal["checklist"]
    id: str
    items: List[ChecklistItem]
    # If true, checking items wakes Sara ("I'm done shopping"); else silent.
    notify: bool = False


class StepItem(BaseModel):
    id: str
    text: str
    done: bool = False


class StepsComponent(BaseModel):
    type: Literal["steps"]
    id: str
    steps: List[StepItem]
    notify: bool = False


class TimerComponent(BaseModel):
    type: Literal["timer"]
    id: str
    label: str = "Timer"
    duration_seconds: int = Field(gt=0, le=24 * 3600)
    notify: bool = True


class FileEntry(BaseModel):
    name: str
    artifact_id: Optional[str] = None
    job_id: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    mime: Optional[str] = None


class FileListComponent(BaseModel):
    type: Literal["file_list"]
    id: str
    files: List[FileEntry] = []


class TableColumn(BaseModel):
    key: str
    title: str


class TableComponent(BaseModel):
    type: Literal["table"]
    id: str
    columns: List[TableColumn]
    rows: List[Dict[str, Any]] = []


class FormField(BaseModel):
    id: str
    label: str
    kind: Literal["text", "number", "textarea", "select", "checkbox"] = "text"
    options: Optional[List[str]] = None
    value: Optional[Any] = None
    placeholder: Optional[str] = None


class FormComponent(BaseModel):
    type: Literal["form"]
    id: str
    fields: List[FormField]
    submit_label: str = "Submit"
    notify: bool = True


class ButtonSpec(BaseModel):
    id: str
    label: str
    style: Literal["default", "primary", "danger"] = "default"
    notify: bool = True


class ButtonsComponent(BaseModel):
    type: Literal["buttons"]
    id: str
    buttons: List[ButtonSpec]


class ProgressComponent(BaseModel):
    type: Literal["progress"]
    id: str
    value: float = 0
    max: float = 100
    label: Optional[str] = None


Component = Union[
    MarkdownComponent,
    ChecklistComponent,
    StepsComponent,
    TimerComponent,
    FileListComponent,
    TableComponent,
    FormComponent,
    ButtonsComponent,
    ProgressComponent,
]

_COMPONENT_BY_TYPE = {
    "markdown": MarkdownComponent,
    "checklist": ChecklistComponent,
    "steps": StepsComponent,
    "timer": TimerComponent,
    "file_list": FileListComponent,
    "table": TableComponent,
    "form": FormComponent,
    "buttons": ButtonsComponent,
    "progress": ProgressComponent,
}

VALID_TYPES = sorted(_COMPONENT_BY_TYPE.keys())


class SurfaceSpec(BaseModel):
    components: List[Dict[str, Any]]

    @field_validator("components")
    @classmethod
    def _non_empty(cls, v):
        if not v:
            raise ValueError("A surface needs at least one component")
        return v


def validate_surface_spec(spec: Any) -> Dict[str, Any]:
    """
    Validate a surface spec against the closed vocabulary.

    Returns the normalized spec dict on success. Raises ValueError with a
    concrete, model-actionable message on failure.
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object with a 'components' array")

    try:
        outer = SurfaceSpec(**spec)
    except ValidationError as e:
        raise ValueError(f"Invalid surface spec: {e.errors()[0].get('msg', str(e))}")

    normalized: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, comp in enumerate(outer.components):
        if not isinstance(comp, dict) or "type" not in comp:
            raise ValueError(f"Component {idx} is missing a 'type' field")
        ctype = comp["type"]
        model = _COMPONENT_BY_TYPE.get(ctype)
        if not model:
            raise ValueError(
                f"Component {idx} has unknown type '{ctype}'. "
                f"Valid types: {', '.join(VALID_TYPES)}"
            )
        try:
            validated = model(**comp)
        except ValidationError as e:
            first = e.errors()[0]
            loc = ".".join(str(x) for x in first.get("loc", []))
            raise ValueError(
                f"Component {idx} ('{ctype}') invalid at '{loc}': {first.get('msg')}"
            )
        # Interactive components must have unique ids so events can target them.
        comp_id = getattr(validated, "id", None)
        if comp_id is not None:
            if comp_id in seen_ids:
                raise ValueError(f"Duplicate component id '{comp_id}'")
            seen_ids.add(comp_id)
        normalized.append(validated.model_dump(exclude_none=True))

    return {"components": normalized}
