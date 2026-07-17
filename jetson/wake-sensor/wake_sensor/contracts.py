"""Canonical wake-sensor event contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class VoiceEvent:
    event_type: str
    source: str
    payload: Dict[str, Any]
    trace_id: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "source": self.source,
            "payload": self.payload,
            "trace_id": self.trace_id,
        }


@dataclass
class TurnContext:
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    speaker_id: str = "david"

