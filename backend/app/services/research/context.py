"""
Context builder for research executor steps.

Each step gets a fresh context with:
- System prompt defining the agent's role
- The current step's instructions
- Relevant findings from prior steps (cherry-picked, not the whole history)
- Any Sara-provided answers to prior questions
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_system_prompt(plan: Dict[str, Any]) -> str:
    """Build the system prompt for the research agent."""
    return f"""You are a research agent working on a structured research plan. Your job is to thoroughly research each topic you're given, using the tools available to you.

## Research Plan
**Title:** {plan['title']}
**Objective:** {plan['objective']}

## Your Capabilities
- **web_search**: Search the web for current information
- **web_fetch**: Read the full content of web pages
- **write_file**: Save findings, notes, and data to files
- **read_file**: Read previously saved files
- **list_files**: See what files exist in your working directory
- **run_command**: Execute shell commands for data processing
- **ask_sara**: Ask Sara (the primary AI) for help if you're stuck or need clarification
- **report_findings**: Submit your findings when you've completed research on the current topic

## Guidelines
1. Be thorough — check multiple sources, cross-reference information
2. Always cite your sources with URLs
3. Save important findings to files as you go (use write_file)
4. If a topic is too broad, use report_findings with substeps_needed to break it down
5. If you're stuck or the instructions are unclear, use ask_sara — don't guess
6. Focus on current, up-to-date information — verify dates on sources
7. When done with a step, call report_findings with a clear summary and detailed findings
8. Write findings in clean markdown format"""


def build_step_context(
    plan: Dict[str, Any],
    step_index: int,
    prior_findings: Optional[List[Dict[str, Any]]] = None,
    sara_answers: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """
    Build the message list for executing a research step.

    Returns a fresh conversation: [system, user] — no prior turn history.
    """
    messages = []

    # System prompt
    messages.append({
        "role": "system",
        "content": build_system_prompt(plan),
    })

    # Build the user message with step instructions + context
    steps = plan.get("steps", [])
    if step_index >= len(steps):
        return messages

    current_step = steps[step_index]
    step_title = current_step.get("title", f"Step {step_index + 1}")
    step_description = current_step.get("description", "")
    step_instructions = current_step.get("instructions", step_description)

    user_content = f"## Current Task: Step {step_index + 1} — {step_title}\n\n"
    user_content += f"{step_instructions}\n"

    # Add relevant prior findings (only summaries to keep context small)
    if prior_findings:
        user_content += "\n## Relevant Prior Findings\n"
        for pf in prior_findings[-5:]:  # Last 5 at most
            pf_title = pf.get("title", "Previous step")
            pf_summary = pf.get("summary", "")
            if pf_summary:
                user_content += f"\n### {pf_title}\n{pf_summary}\n"

    # Add Sara's answers to prior questions
    if sara_answers:
        user_content += "\n## Sara's Guidance\n"
        for sa in sara_answers[-3:]:  # Last 3 answers
            user_content += f"\n**Q:** {sa.get('question', '')}\n**A:** {sa.get('answer', '')}\n"

    user_content += (
        "\n---\n"
        "Begin your research. Use web_search to find sources, web_fetch to read them, "
        "and write_file to save your work. When done, call report_findings."
    )

    messages.append({
        "role": "user",
        "content": user_content,
    })

    return messages


def build_sara_answer_context(
    plan: Dict[str, Any],
    step_index: int,
    question: str,
    prior_findings: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Build a prompt for Sara to answer the research agent's question.

    Sara has the full plan context and can provide guidance.
    """
    steps = plan.get("steps", [])
    current_step = steps[step_index] if step_index < len(steps) else {}

    prompt = f"""The research agent working on your plan "{plan['title']}" has a question.

**Plan Objective:** {plan['objective']}

**Current Step ({step_index + 1}/{len(steps)}):** {current_step.get('title', 'Unknown')}
{current_step.get('description', '')}

"""

    if prior_findings:
        prompt += "**Findings so far:**\n"
        for pf in prior_findings:
            prompt += f"- {pf.get('title', 'Step')}: {pf.get('summary', 'No summary')}\n"
        prompt += "\n"

    prompt += f"**Agent's Question:**\n{question}\n\n"
    prompt += "Please provide a helpful answer to guide the research agent. Be specific and actionable."

    return prompt
