"""Sampling configurations for the natural-conversation evaluation.

SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md, Stage 1 table.

B0 values are the ACTUAL runtime defaults confirmed 2026-09-23 by reading
`docker compose exec backend env` (CHAT_ENABLE_THINKING, CHAT_REASONING_EFFORT,
CHAT_PRESENCE_PENALTY, LOCAL_GENERATION_MODE were all UNSET in the running
container, so main_simple.py's os.getenv(...) fallbacks apply) plus the
model's own /health sampler_defaults. This is the user's present baseline,
not a guess from source alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SamplingConfig:
    id: str
    thinking: str  # "off" | "low" | "medium" | "xhigh" | "actual" (B0 marker)
    temperature: float
    top_p: float
    top_k: int = 20
    min_p: float = 0.0
    presence_penalty: float = 0.0
    repetition_penalty: Optional[float] = None  # only sent in thinking mode per source
    reasoning_effort: Optional[str] = None
    generation_mode: str = "ar"
    depth: int = 0
    purpose: str = ""

    def payload_fields(self) -> dict:
        """Fields to merge into the outgoing chat/completions payload.

        Mirrors `_apply_local_qwen_chat_sampling` in main_simple.py exactly:
        thinking mode sends a DIFFERENT sampler set than instruct mode, and
        every value is explicit (never relies on a server default).
        """
        fields: dict = {
            "generation_mode": self.generation_mode,
            "depth": self.depth if self.generation_mode == "mtp" else 0,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
        }
        enable_thinking = self.thinking not in ("off",)
        fields["chat_template_kwargs"] = {
            "enable_thinking": enable_thinking,
            "preserve_thinking": False,
        }
        if enable_thinking:
            effort = self.reasoning_effort or ("low" if self.thinking == "actual" else self.thinking)
            fields["reasoning_effort"] = effort
            fields["chat_template_kwargs"]["reasoning_effort"] = effort
            fields["presence_penalty"] = self.presence_penalty  # source sets 0.0 in thinking mode
            if self.repetition_penalty is not None:
                fields["repetition_penalty"] = self.repetition_penalty
        else:
            if self.presence_penalty:
                fields["presence_penalty"] = self.presence_penalty
        return fields


# B0: actual current effective configuration.
# CHAT_ENABLE_THINKING default "true" -> thinking ON.
# CHAT_REASONING_EFFORT default "low".
# LOCAL_GENERATION_MODE default "ar".
# CHAT_PRESENCE_PENALTY default 0.6, but the source code only applies
# presence_penalty in the non-thinking branch (thinking branch hardcodes 0.0)
# -- so at B0 (thinking ON), presence_penalty is 0.0 regardless of the env var.
B0 = SamplingConfig(
    id="B0", thinking="low", temperature=1.0, top_p=0.95, top_k=20, min_p=0.0,
    presence_penalty=0.0, repetition_penalty=1.0, reasoning_effort="low",
    generation_mode="ar", depth=0,
    purpose="User's present baseline (actual runtime env, confirmed 2026-09-23)",
)

STAGE1_CANDIDATES = {
    "B0": B0,
    "S1": SamplingConfig(id="S1", thinking="off", temperature=0.7, top_p=0.8, presence_penalty=0.0,
                          purpose="Explicit non-thinking control"),
    "S2": SamplingConfig(id="S2", thinking="off", temperature=0.7, top_p=0.8, presence_penalty=0.6,
                          purpose="Penalty change only vs S1"),
    "S3": SamplingConfig(id="S3", thinking="off", temperature=0.7, top_p=0.8, presence_penalty=1.0,
                          purpose="Further penalty test vs S1/S2"),
    "S4": SamplingConfig(id="S4", thinking="off", temperature=1.0, top_p=0.8, presence_penalty=0.0,
                          purpose="Temperature change only vs S1"),
    "S5": SamplingConfig(id="S5", thinking="low", temperature=1.0, top_p=0.95, presence_penalty=0.0,
                          repetition_penalty=1.0, reasoning_effort="low", purpose="Thinking candidate"),
    "S6": SamplingConfig(id="S6", thinking="medium", temperature=1.0, top_p=0.95, presence_penalty=0.0,
                          repetition_penalty=1.0, reasoning_effort="medium",
                          purpose="Effort change only vs S5"),
    "S7": SamplingConfig(id="S7", thinking="off", temperature=1.0, top_p=0.95, presence_penalty=0.0,
                          purpose="Thinking control vs S5; top_p comparison vs S4"),
}

COMMON_MAX_TOKENS = 4096
