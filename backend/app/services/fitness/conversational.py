from typing import Dict, Any, List
from app.core.llm import llm_client


SYSTEM_PROMPT = (
    "You are Sara, a friendly, professional fitness coach.\n"
    "Goal: collect the next missing detail with a natural, complete question.\n"
    "Constraints:\n"
    "- Ask ONE question at a time.\n"
    "- Use a complete sentence (not a fragment).\n"
    "- Keep it short (10–20 words), friendly, and specific.\n"
    "- If chip suggestions are provided, mention them as brief options.\n"
)


async def generate_prompt(
    stage: str,
    field: str,
    collected: Dict[str, Any],
    chips: List[str]
) -> str:
    """Generate a conversational prompt for the next onboarding question using the LLM.

    Falls back to a deterministic phrasing if model call fails.
    """
    try:
        summary_lines = []
        for k, v in collected.items():
            if v is None or v == "":
                continue
            summary_lines.append(f"- {k}: {v}")
        summary = "\n".join(summary_lines) if summary_lines else "(no prior answers)"

        user_msg = (
            f"Stage: {stage}\n"
            f"Collected so far:\n{summary}\n\n"
            f"Next field to collect: {field}.\n"
            f"Provide a single, friendly question asking for {field}."
        )
        if chips:
            user_msg += f"\nSuggested options: {', '.join(chips)}"

        result = await llm_client.chat_completion([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ], temperature=0.6, max_tokens=120)

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = (content or "").strip()
        if not content:
            raise RuntimeError("empty LLM content")
        return content
    except Exception:
        # Deterministic fallback
        pretty = field.replace("_", " ").capitalize()
        return f"Could you tell me your {pretty.lower()}?"
