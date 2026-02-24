"""Temerant service package."""

__all__ = [
    "TemerantRulesEngine",
    "CharacterService",
    "OracleService",
    "TermService",
    "JournalService",
    "IngestionService",
]


def __getattr__(name: str):
    if name == "TemerantRulesEngine":
        from .rules_engine import TemerantRulesEngine

        return TemerantRulesEngine
    if name == "CharacterService":
        from .character_service import CharacterService

        return CharacterService
    if name == "OracleService":
        from .oracle_service import OracleService

        return OracleService
    if name == "TermService":
        from .term_service import TermService

        return TermService
    if name == "JournalService":
        from .journal_service import JournalService

        return JournalService
    if name == "IngestionService":
        from .ingestion_service import IngestionService

        return IngestionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
