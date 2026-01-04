"""
Cognitive Enhancement API Routes

Endpoints for Sara's cognitive enhancement features:
- Self-reflections and identity
- Hypotheses about the user
- Relationship state
- Reasoning traces
- Prediction calibration
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime
import logging

# Import from main_simple for auth and database
from app.main_simple import SessionLocal, get_current_user

# Import services
from app.services.sara_identity_service import sara_identity_service
from app.services.hypothesis_service import hypothesis_service
from app.services.uncertainty_service import uncertainty_service, get_uncertainty_phrase, format_confidence_for_display

# Import models
from app.models.cognitive import SaraReflection, RelationshipState, Hypothesis, ReasoningTrace, Prediction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cognitive", tags=["cognitive"])


# ==================== Pydantic Models ====================

class ReflectionResponse(BaseModel):
    id: str
    reflection_type: str
    domain: Optional[str]
    content: str
    confidence: float
    times_applied: int
    effectiveness_score: Optional[float]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class HypothesisResponse(BaseModel):
    id: str
    statement: str
    domain: str
    confidence: float
    status: str
    times_useful: int
    evidence_for_count: int
    evidence_against_count: int
    first_formed: datetime
    last_updated: datetime

    class Config:
        from_attributes = True


class RelationshipResponse(BaseModel):
    phase: str
    duration: str
    total_conversations: int
    total_episodes: int
    top_topics: List[tuple]
    shared_references: List[Any]
    communication_preferences: Dict[str, Any]


class UserModelSummary(BaseModel):
    high_confidence: List[Dict[str, Any]]
    medium_confidence: List[Dict[str, Any]]
    forming: List[Dict[str, Any]]
    total_hypotheses: int
    domains_covered: List[str]


class CalibrationResponse(BaseModel):
    calibration_by_confidence: Dict[str, Any]
    brier_score: float
    total_predictions: int
    interpretation: str


class EvidenceCreate(BaseModel):
    evidence_type: str  # "for" or "against"
    quote: str
    weight: Optional[float] = 0.5


class PredictionCreate(BaseModel):
    statement: str
    confidence: float
    domain: Optional[str] = None


class PredictionResolve(BaseModel):
    outcome: str  # "correct" or "incorrect"
    notes: Optional[str] = None


# ==================== Dependency ====================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Self-Reflection Endpoints ====================

@router.get("/reflections", response_model=List[ReflectionResponse])
async def get_reflections(
    reflection_type: Optional[str] = Query(None, description="Filter by type: mistake, pattern, preference, growth"),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Sara's self-reflections."""
    reflections = await sara_identity_service.get_recent_reflections(
        db=db,
        reflection_type=reflection_type,
        limit=limit
    )
    return [
        ReflectionResponse(
            id=r.id,
            reflection_type=r.reflection_type,
            domain=r.domain,
            content=r.content,
            confidence=r.confidence,
            times_applied=r.times_applied,
            effectiveness_score=r.effectiveness_score,
            is_active=r.is_active,
            created_at=r.created_at
        )
        for r in reflections
    ]


@router.get("/reflections/relevant")
async def get_relevant_reflections(
    query: str = Query(..., description="Query to find relevant reflections for"),
    domain: Optional[str] = None,
    limit: int = Query(5, ge=1, le=20),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get reflections relevant to a specific query context."""
    reflections = await sara_identity_service.get_relevant_reflections(
        db=db,
        query=query,
        domain=domain,
        limit=limit
    )
    return [
        {
            "id": r.id,
            "type": r.reflection_type,
            "domain": r.domain,
            "content": r.content,
            "confidence": r.confidence
        }
        for r in reflections
    ]


# ==================== Relationship Endpoints ====================

@router.get("/relationship", response_model=RelationshipResponse)
async def get_relationship(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current relationship state between Sara and David."""
    context = await sara_identity_service.get_relationship_context(db)
    return RelationshipResponse(
        phase=context.get("phase", "new"),
        duration=context.get("duration", "unknown"),
        total_conversations=context.get("total_conversations", 0),
        total_episodes=0,  # Will be set from context if available
        top_topics=context.get("top_topics", []),
        shared_references=context.get("shared_references", []),
        communication_preferences=context.get("communication_preferences", {})
    )


# ==================== Hypothesis Endpoints ====================

@router.get("/hypotheses", response_model=UserModelSummary)
async def get_hypotheses(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Sara's current hypotheses about the user (user model summary)."""
    summary = await hypothesis_service.get_user_model_summary(db)
    return UserModelSummary(**summary)


@router.get("/hypotheses/relevant")
async def get_relevant_hypotheses(
    query: str = Query(..., description="Query to find relevant hypotheses for"),
    domain: Optional[str] = None,
    min_confidence: float = Query(0.2, ge=0.0, le=1.0),
    limit: int = Query(5, ge=1, le=20),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get hypotheses relevant to a specific query context."""
    hypotheses = await hypothesis_service.get_relevant_hypotheses(
        db=db,
        query=query,
        domain=domain,
        min_confidence=min_confidence,
        limit=limit
    )
    return [
        {
            "id": h.id,
            "statement": h.statement,
            "domain": h.domain,
            "confidence": h.confidence,
            "confidence_display": format_confidence_for_display(h.confidence),
            "uncertainty_phrase": get_uncertainty_phrase(h.confidence),
            "status": h.status
        }
        for h in hypotheses
    ]


@router.get("/hypotheses/{hypothesis_id}")
async def get_hypothesis_detail(
    hypothesis_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific hypothesis."""
    hypothesis = await hypothesis_service.get_hypothesis_by_id(db, hypothesis_id)
    if not hypothesis:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    return {
        "id": hypothesis.id,
        "statement": hypothesis.statement,
        "domain": hypothesis.domain,
        "confidence": hypothesis.confidence,
        "confidence_display": format_confidence_for_display(hypothesis.confidence),
        "status": hypothesis.status,
        "times_useful": hypothesis.times_useful,
        "evidence_for": hypothesis.evidence_for or [],
        "evidence_against": hypothesis.evidence_against or [],
        "first_formed": hypothesis.first_formed,
        "last_updated": hypothesis.last_updated,
        "last_evidence_at": hypothesis.last_evidence_at
    }


@router.post("/hypotheses/{hypothesis_id}/evidence")
async def add_hypothesis_evidence(
    hypothesis_id: str,
    evidence: EvidenceCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually add evidence to a hypothesis."""
    hypothesis = await hypothesis_service.get_hypothesis_by_id(db, hypothesis_id)
    if not hypothesis:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    if evidence.evidence_type not in ["for", "against"]:
        raise HTTPException(status_code=400, detail="evidence_type must be 'for' or 'against'")

    await hypothesis_service.add_evidence(
        db=db,
        hypothesis_id=hypothesis_id,
        evidence_type=evidence.evidence_type,
        quote=evidence.quote,
        episode_ids=[],
        weight=evidence.weight
    )

    return {"status": "ok", "message": f"Added {evidence.evidence_type} evidence to hypothesis"}


@router.post("/hypotheses/{hypothesis_id}/refute")
async def refute_hypothesis(
    hypothesis_id: str,
    reason: str = Query(..., description="Reason for refuting the hypothesis"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Explicitly refute a hypothesis."""
    hypothesis = await hypothesis_service.get_hypothesis_by_id(db, hypothesis_id)
    if not hypothesis:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    await hypothesis_service.refute_hypothesis(
        db=db,
        hypothesis_id=hypothesis_id,
        reason=reason
    )

    return {"status": "ok", "message": "Hypothesis refuted"}


# ==================== Calibration Endpoints ====================

@router.get("/calibration", response_model=CalibrationResponse)
async def get_calibration(
    domain: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Sara's prediction calibration statistics."""
    stats = await uncertainty_service.get_calibration_stats(db, domain)

    if stats.get("total_predictions", 0) == 0:
        return CalibrationResponse(
            calibration_by_confidence={},
            brier_score=0.0,
            total_predictions=0,
            interpretation="No resolved predictions yet to calculate calibration"
        )

    return CalibrationResponse(
        calibration_by_confidence=stats.get("calibration_by_confidence", {}),
        brier_score=stats.get("brier_score", 0.0),
        total_predictions=stats.get("total_predictions", 0),
        interpretation=stats.get("interpretation", "")
    )


@router.post("/predictions")
async def create_prediction(
    prediction: PredictionCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Log a prediction for calibration tracking."""
    result = await uncertainty_service.log_prediction(
        db=db,
        statement=prediction.statement,
        confidence=prediction.confidence,
        domain=prediction.domain
    )

    return {
        "id": result.id,
        "statement": result.statement,
        "confidence": result.confidence,
        "created_at": result.created_at
    }


@router.get("/predictions/unresolved")
async def get_unresolved_predictions(
    domain: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get predictions that haven't been resolved yet."""
    predictions = await uncertainty_service.get_unresolved_predictions(
        db=db,
        domain=domain,
        limit=limit
    )

    return [
        {
            "id": p.id,
            "statement": p.statement,
            "confidence": p.confidence,
            "confidence_display": format_confidence_for_display(p.confidence),
            "domain": p.domain,
            "created_at": p.created_at
        }
        for p in predictions
    ]


@router.post("/predictions/{prediction_id}/resolve")
async def resolve_prediction(
    prediction_id: str,
    resolution: PredictionResolve,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resolve a prediction as correct or incorrect."""
    prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    if resolution.outcome not in ["correct", "incorrect"]:
        raise HTTPException(status_code=400, detail="outcome must be 'correct' or 'incorrect'")

    await uncertainty_service.resolve_prediction(
        db=db,
        prediction_id=prediction_id,
        outcome=resolution.outcome,
        notes=resolution.notes
    )

    return {"status": "ok", "message": f"Prediction resolved as {resolution.outcome}"}


# ==================== Reasoning Trace Endpoints ====================

@router.get("/reasoning-traces")
async def get_reasoning_traces(
    conversation_id: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get recent reasoning traces."""
    traces = await uncertainty_service.get_recent_reasoning_traces(
        db=db,
        conversation_id=conversation_id,
        limit=limit
    )

    return [
        {
            "id": t.id,
            "episode_id": t.episode_id,
            "conversation_id": t.conversation_id,
            "reasoning_effort": t.reasoning_effort,
            "thinking_preview": t.thinking_content[:500] + "..." if len(t.thinking_content) > 500 else t.thinking_content,
            "final_answer_summary": t.final_answer_summary,
            "token_count": t.token_count,
            "duration_ms": t.duration_ms,
            "created_at": t.created_at
        }
        for t in traces
    ]


@router.get("/reasoning-traces/{trace_id}")
async def get_reasoning_trace_detail(
    trace_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get full details of a reasoning trace."""
    trace = db.query(ReasoningTrace).filter(ReasoningTrace.id == trace_id).first()
    if not trace:
        raise HTTPException(status_code=404, detail="Reasoning trace not found")

    return {
        "id": trace.id,
        "episode_id": trace.episode_id,
        "conversation_id": trace.conversation_id,
        "thinking_content": trace.thinking_content,
        "reasoning_effort": trace.reasoning_effort,
        "tool_calls_made": trace.tool_calls_made or [],
        "final_answer_summary": trace.final_answer_summary,
        "token_count": trace.token_count,
        "duration_ms": trace.duration_ms,
        "created_at": trace.created_at
    }


# ==================== Combined Context Endpoint ====================

@router.get("/context")
async def get_cognitive_context(
    query: str = Query(..., description="Query to build context for"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get combined cognitive context for inclusion in prompts.
    This is the main endpoint used during chat to inject Sara's self-knowledge.
    """

    # Get relevant reflections
    reflections = await sara_identity_service.get_relevant_reflections(
        db=db,
        query=query,
        limit=3
    )

    # Get relationship context
    relationship = await sara_identity_service.get_relationship_context(db)

    # Get relevant hypotheses
    hypotheses = await hypothesis_service.get_relevant_hypotheses(
        db=db,
        query=query,
        min_confidence=0.3,
        limit=3
    )

    # Build context strings
    reflection_text = ""
    if reflections:
        reflection_text = "## Sara's Self-Knowledge\nRemember these things about yourself:\n"
        for r in reflections:
            reflection_text += f"- [{r.reflection_type}] {r.content}\n"

    relationship_text = ""
    if relationship.get("phase") != "new":
        relationship_text = f"## Relationship Context\n"
        relationship_text += f"You and David have been talking for {relationship.get('duration')}. "
        relationship_text += f"Relationship phase: {relationship.get('phase')}. "
        if relationship.get("top_topics"):
            topics = [t[0] for t in relationship.get("top_topics", [])]
            relationship_text += f"Frequent topics: {', '.join(topics)}."

    hypothesis_text = ""
    if hypotheses:
        hypothesis_text = "## What Sara Believes About David\nConsider these beliefs when responding:\n"
        for h in hypotheses:
            confidence_label = "likely" if h.confidence >= 0.7 else "possibly"
            hypothesis_text += f"- {confidence_label}: {h.statement}\n"

    return {
        "reflection_context": reflection_text,
        "relationship_context": relationship_text,
        "hypothesis_context": hypothesis_text,
        "combined_context": "\n".join(filter(None, [reflection_text, relationship_text, hypothesis_text])),
        "raw": {
            "reflections": [{"id": r.id, "type": r.reflection_type, "content": r.content} for r in reflections],
            "relationship": relationship,
            "hypotheses": [{"id": h.id, "statement": h.statement, "confidence": h.confidence} for h in hypotheses]
        }
    }
