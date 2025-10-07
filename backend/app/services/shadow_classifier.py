"""
Shadow Event Classifier
Classifies raw events and notes into: task, decision, question, idea, reference
"""
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class ShadowClassifier:
    """Classify Shadow events into actionable categories"""

    def __init__(self):
        # Keyword patterns for quick classification
        self.patterns = {
            "task": [
                r"\btodo\b",
                r"\btask\b",
                r"\bfix\b",
                r"\bimplement\b",
                r"\badd\b",
                r"\bcreate\b",
                r"\bupdate\b",
                r"\brefactor\b",
                r"\btest\b",
                r"\bdeploy\b",
                r"\bdue\b",
                r"\bdeadline\b",
                r"\bneed to\b",
                r"\bshould\b",
                r"\bmust\b"
            ],
            "decision": [
                r"\bchose\b",
                r"\bdecided\b",
                r"\bgoing with\b",
                r"\bwill use\b",
                r"\bsettled on\b",
                r"\bpicked\b",
                r"\bselected\b",
                r"\bagreed\b",
                r"\bapproved\b",
                r"\brejected\b",
                r"\bfinalized\b"
            ],
            "question": [
                r"\?$",
                r"\bhow to\b",
                r"\bwhy\b",
                r"\bwhat if\b",
                r"\bshould we\b",
                r"\bcan we\b",
                r"\bis it possible\b",
                r"\bunclear\b",
                r"\bnot sure\b",
                r"\bconfused\b"
            ],
            "idea": [
                r"\bidea\b",
                r"\bbrainstorm\b",
                r"\bcould try\b",
                r"\bmight work\b",
                r"\bconsider\b",
                r"\bwhat about\b",
                r"\bmaybe\b",
                r"\bpotential\b",
                r"\bsuggestion\b",
                r"\bproposal\b"
            ]
        }
        logger.info("🔍 ShadowClassifier initialized")

    def classify_text(self, text: str) -> str:
        """
        Classify text into: task, decision, question, idea, or reference
        Uses keyword matching with confidence scoring
        """
        if not text or len(text.strip()) < 3:
            return "reference"

        text_lower = text.lower().strip()

        # Score each category
        scores = {
            "task": 0,
            "decision": 0,
            "question": 0,
            "idea": 0
        }

        for category, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    scores[category] += 1

        # Question mark is strong signal
        if text.endswith("?"):
            scores["question"] += 5

        # Find highest score
        max_score = max(scores.values())

        if max_score == 0:
            # No strong signals, default to reference
            return "reference"

        # Get category with highest score
        classified_as = max(scores, key=scores.get)

        logger.debug(f"Classified '{text[:50]}...' as {classified_as} (scores: {scores})")
        return classified_as

    def classify_event(self, event_type: str, event_metadata: Dict[str, Any]) -> str:
        """
        Classify a Shadow event based on type and event_metadata
        """
        # Extract relevant text from event_metadata
        text_content = []

        if event_type == "browser":
            title = event_metadata.get("title", "")
            url = event_metadata.get("url", "")
            text_content.append(title)
            # Check for documentation/search URLs
            if any(keyword in url.lower() for keyword in ["stackoverflow", "docs", "github", "search"]):
                return "reference"

        elif event_type == "editor":
            file_path = event_metadata.get("file_path", "")
            action = event_metadata.get("action", "")

            # File save with TODO comment nearby
            if action == "save" and event_metadata.get("nearby_comments"):
                comments = event_metadata.get("nearby_comments", [])
                text_content.extend(comments)

            # Check for test files
            if "test" in file_path.lower() or "spec" in file_path.lower():
                return "task"  # Writing tests is usually a task

        elif event_type == "terminal":
            command = event_metadata.get("command", "")
            text_content.append(command)

            # Git commits are often decisions
            if command.startswith("git commit"):
                commit_msg = event_metadata.get("commit_message", "")
                if commit_msg:
                    return self.classify_text(commit_msg)
                return "decision"

            # Deployment commands
            if any(kw in command for kw in ["deploy", "build", "release"]):
                return "task"

        elif event_type == "fs":
            # Filesystem events are usually references
            return "reference"

        # Classify based on combined text
        combined_text = " ".join(text_content)
        if combined_text:
            return self.classify_text(combined_text)

        # Default fallback
        return "reference"

    def extract_due_date(self, text: str) -> Optional[datetime]:
        """
        Extract due date from text like 'due Friday', 'deadline tomorrow', 'by next week'
        Returns None if no date found
        """
        # TODO: Implement proper NLP date extraction
        # For MVP, just detect keywords and return None
        # This can be enhanced with dateparser library later

        text_lower = text.lower()

        # Simple pattern matching for common phrases
        if "today" in text_lower:
            from datetime import datetime, timedelta
            return datetime.now() + timedelta(hours=8)  # End of workday

        if "tomorrow" in text_lower:
            from datetime import datetime, timedelta
            return datetime.now() + timedelta(days=1)

        # For MVP, return None and let users specify explicitly
        return None

    def extract_tags(self, text: str, event_type: str) -> List[str]:
        """
        Extract relevant tags from text and event metadata
        """
        tags = []

        # Add event type as tag
        tags.append(event_type)

        # Common technical tags
        tech_keywords = {
            "coding": ["code", "programming", "debug", "function", "class"],
            "testing": ["test", "spec", "coverage", "assertion"],
            "deployment": ["deploy", "build", "release", "production"],
            "documentation": ["docs", "readme", "comment", "document"],
            "bug-fix": ["bug", "fix", "error", "crash", "issue"],
            "performance": ["performance", "optimize", "speed", "slow"],
            "security": ["security", "auth", "password", "encrypt", "vulnerability"]
        }

        text_lower = text.lower()
        for tag, keywords in tech_keywords.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(tag)

        return list(set(tags))  # Deduplicate


# Global classifier instance
shadow_classifier = ShadowClassifier()
