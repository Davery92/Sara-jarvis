"""
Reflection system services for Sara's cognitive architecture (Phase 3).

The reflection system provides meta-cognitive auditing and self-improvement:
- Scratchpad for storing observations and patterns
- Consolidation auditing
- Pattern detection
- Prompt modification proposals
- Uncertainty handling
"""

from .scratchpad import ReflectionScratchpad, get_reflection_scratchpad
from .consolidation_auditor import ConsolidationAuditor
from .pattern_detector import PatternDetector
from .proposal_generator import PromptProposalGenerator
from .agent import ReflectionAgent, get_reflection_agent

__all__ = [
    "ReflectionScratchpad",
    "get_reflection_scratchpad",
    "ConsolidationAuditor",
    "PatternDetector",
    "PromptProposalGenerator",
    "ReflectionAgent",
    "get_reflection_agent",
]
