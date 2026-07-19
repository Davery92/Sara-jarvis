"""
Soul Layer models.

Sara's persistent identity document - who she is, how she operates, where she's growing.
Sara can propose changes to her Soul, but they require David's approval.
"""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base


class SaraSoul(Base):
    """
    Sara's Soul - her core identity document.

    Sections:
    - identity: Who Sara is, her voice and personality
    - principles: Operating principles and behavioral rules
    - boundaries: Things Sara won't do or lines she won't cross
    - growth: Current growth areas and learning focus
    - evolution_log: History of changes to the Soul
    """
    __tablename__ = "sara_soul"

    id = Column(Integer, primary_key=True, autoincrement=True)
    section = Column(String(50), nullable=False, unique=True)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(50), nullable=False)  # sara, david, sara_approved_by_david

    def __repr__(self):
        return f"<SaraSoul(section='{self.section}', version={self.version})>"


class SoulChangeProposal(Base):
    """
    Soul change proposals - Sara's proposed modifications awaiting approval.

    When Sara notices a pattern or receives feedback that should become permanent,
    she creates a proposal. David can approve or reject it.
    """
    __tablename__ = "soul_change_proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    section = Column(String(50), nullable=False)
    current_content = Column(Text)
    proposed_content = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)  # Why Sara wants to change this
    status = Column(String(20), default='pending')  # pending, approved, rejected
    rejection_reason = Column(Text)  # If rejected, why
    proposed_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(String(50))  # david (manual) or system (auto-approved)
    # H7.2 graduation ladder: link back to the PKG fact that generated this
    # proposal (marked internalized on approval), style-vs-identity kind, and
    # the evidence count that justified graduation.
    source_ref = Column(String(128))
    kind = Column(String(20), default='identity')  # 'style' (auto-approvable) | 'identity'
    evidence_count = Column(Integer)

    def __repr__(self):
        return f"<SoulChangeProposal(section='{self.section}', status='{self.status}')>"
