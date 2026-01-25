"""
Cognitive Enhancement API Routes

Endpoints for Sara's cognitive enhancement features:
- Self-reflections and identity
- Hypotheses about the user
- Relationship state
- Reasoning traces
- Prediction calibration
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Header
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


# ==================== Raw Buffer Input Endpoints ====================
# These endpoints allow desktop sidecar and other services to submit sensory data

class AudioTranscriptInput(BaseModel):
    user_text: str
    sara_response: Optional[str] = None
    source: str = "voice_bridge"


class ScreenCaptureInput(BaseModel):
    active_app: Optional[str] = None
    window_title: Optional[str] = None
    screenshot_ref: Optional[str] = None
    source: str = "screenshot_service"


class ModeChangeInput(BaseModel):
    mode: str  # "ambient" or "active"
    reason: Optional[str] = None


@router.post("/raw-buffer/audio")
async def submit_audio_transcript(
    input_data: AudioTranscriptInput,
    current_user=Depends(get_current_user)
):
    """
    Accept voice transcripts from sidecar.

    Called by voice_bridge.py when transcript events arrive from Jetson.
    Writes to raw_buffer:text stream for cognitive processing.
    """
    from app.tasks.input_processing import process_text_input

    try:
        # Build metadata with Sara's response if present
        metadata = {
            "source": input_data.source,
            "has_sara_response": input_data.sara_response is not None
        }
        if input_data.sara_response:
            metadata["sara_response"] = input_data.sara_response

        # Submit to Celery task for raw buffer processing
        result = process_text_input.delay(
            content=input_data.user_text,
            source="voice_transcript",
            metadata=metadata
        )

        logger.info(f"Voice transcript submitted to raw buffer: {len(input_data.user_text)} chars")

        return {
            "status": "accepted",
            "task_id": result.id,
            "stream": "raw_buffer:text"
        }

    except Exception as e:
        logger.error(f"Failed to submit audio transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/raw-buffer/screen")
async def submit_screen_capture(
    input_data: ScreenCaptureInput,
    current_user=Depends(get_current_user)
):
    """
    Accept screen capture metadata from sidecar.

    Called by screenshot.py after uploading screenshot to backend.
    Writes to raw_buffer:screen stream for cognitive processing.
    """
    from app.tasks.input_processing import process_screen_capture

    try:
        # Submit to Celery task for raw buffer processing
        result = process_screen_capture.delay(
            screenshot_path=input_data.screenshot_ref,
            active_app=input_data.active_app
        )

        logger.info(f"Screen capture metadata submitted: app={input_data.active_app}")

        return {
            "status": "accepted",
            "task_id": result.id,
            "stream": "raw_buffer:screen"
        }

    except Exception as e:
        logger.error(f"Failed to submit screen capture: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/raw-buffer/stats")
async def get_raw_buffer_stats(
    current_user=Depends(get_current_user)
):
    """
    Get statistics about raw buffer streams.

    Useful for debugging and monitoring the input infrastructure.
    """
    from app.services.cognitive.raw_buffer import get_raw_buffer_service

    try:
        buffer_service = get_raw_buffer_service()
        stats = await buffer_service.get_all_streams_info()
        return stats

    except Exception as e:
        logger.error(f"Failed to get raw buffer stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Mode Control Endpoints ====================

@router.get("/mode")
async def get_current_mode(
    current_user=Depends(get_current_user)
):
    """
    Get Sara's current attention mode.

    Returns mode (ambient/active), when it was entered,
    why it changed, and how long it's been in this mode.
    """
    from app.services.cognitive.mode_controller import get_mode_controller

    try:
        controller = get_mode_controller()
        info = await controller.get_mode_info(current_user.id)
        return info

    except Exception as e:
        logger.error(f"Failed to get mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mode")
async def set_mode(
    input_data: ModeChangeInput,
    current_user=Depends(get_current_user)
):
    """
    Manually set Sara's attention mode.

    Used by sidecar and other services to signal mode transitions.
    """
    from app.services.cognitive.mode_controller import get_mode_controller, Mode

    try:
        if input_data.mode not in ["ambient", "active"]:
            raise HTTPException(status_code=400, detail="mode must be 'ambient' or 'active'")

        controller = get_mode_controller()
        mode = Mode(input_data.mode)
        reason = input_data.reason or "manual_set"

        changed = await controller.set_mode(
            user_id=current_user.id,
            mode=mode,
            reason=reason
        )

        return {
            "status": "ok",
            "changed": changed,
            "mode": input_data.mode
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mode/wake-word")
async def handle_wake_word(
    current_user=Depends(get_current_user)
):
    """
    Signal that wake word was detected.

    Called by voice bridge when wake word triggers.
    Transitions to ACTIVE mode with auto-timeout.
    """
    from app.services.cognitive.mode_controller import get_mode_controller

    try:
        controller = get_mode_controller()
        changed = await controller.handle_wake_word(current_user.id)

        return {
            "status": "ok",
            "changed": changed,
            "mode": "active"
        }

    except Exception as e:
        logger.error(f"Failed to handle wake word: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mode/engagement")
async def handle_engagement(
    source: str = Query("chat", description="Source of engagement"),
    current_user=Depends(get_current_user)
):
    """
    Signal user engagement (chat, voice, etc.).

    Refreshes the active mode timeout.
    """
    from app.services.cognitive.mode_controller import get_mode_controller

    try:
        controller = get_mode_controller()
        changed = await controller.handle_user_engagement(current_user.id, source)

        return {
            "status": "ok",
            "changed": changed,
            "mode": "active"
        }

    except Exception as e:
        logger.error(f"Failed to handle engagement: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mode/goodbye")
async def handle_goodbye(
    current_user=Depends(get_current_user)
):
    """
    Signal end of conversation.

    Transitions to AMBIENT mode.
    """
    from app.services.cognitive.mode_controller import get_mode_controller

    try:
        controller = get_mode_controller()
        changed = await controller.handle_goodbye(current_user.id)

        return {
            "status": "ok",
            "changed": changed,
            "mode": "ambient"
        }

    except Exception as e:
        logger.error(f"Failed to handle goodbye: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Reflection System Endpoints (Phase 3) ====================

class ProposalApproval(BaseModel):
    notes: Optional[str] = None


class ProposalRejection(BaseModel):
    reason: str


class UncertaintyResolution(BaseModel):
    guidance: str


@router.get("/reflection/proposals")
async def list_proposals(
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected, implemented"),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List prompt proposals from the reflection system.

    Returns proposals for David to review and approve/reject.
    """
    from sqlalchemy import text

    try:
        # Build query based on status filter
        if status:
            query = text("""
                SELECT proposal_id, target_agent, target_prompt_section, proposal_type,
                       current_value_summary, proposed_value_summary, reasoning,
                       evidence_pattern_ids, status, created_at, reviewed_at, reviewer_notes
                FROM prompt_proposals
                WHERE status = :status
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            result = db.execute(query, {"status": status, "limit": limit})
        else:
            query = text("""
                SELECT proposal_id, target_agent, target_prompt_section, proposal_type,
                       current_value_summary, proposed_value_summary, reasoning,
                       evidence_pattern_ids, status, created_at, reviewed_at, reviewer_notes
                FROM prompt_proposals
                ORDER BY
                    CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                    created_at DESC
                LIMIT :limit
            """)
            result = db.execute(query, {"limit": limit})

        proposals = []
        for row in result:
            proposals.append({
                "proposal_id": row.proposal_id,
                "target_agent": row.target_agent,
                "target_prompt_section": row.target_prompt_section,
                "proposal_type": row.proposal_type,
                "current_value_summary": row.current_value_summary,
                "proposed_value_summary": row.proposed_value_summary,
                "reasoning": row.reasoning,
                "evidence_pattern_ids": row.evidence_pattern_ids or [],
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                "reviewer_notes": row.reviewer_notes
            })

        return {
            "proposals": proposals,
            "total": len(proposals),
            "filter": status
        }

    except Exception as e:
        logger.error(f"Failed to list proposals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reflection/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific proposal.

    Includes full proposed changes and supporting evidence.
    """
    from sqlalchemy import text

    try:
        query = text("""
            SELECT proposal_id, target_agent, target_prompt_section, proposal_type,
                   current_value_summary, proposed_value_summary, proposed_value,
                   reasoning, evidence_pattern_ids, confidence_score, status,
                   created_at, reviewed_at, reviewer_notes, implemented_at
            FROM prompt_proposals
            WHERE proposal_id = :proposal_id
        """)
        result = db.execute(query, {"proposal_id": proposal_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")

        # Get related patterns if any
        patterns = []
        if row.evidence_pattern_ids:
            for pattern_id in row.evidence_pattern_ids:
                pattern_query = text("""
                    SELECT pattern_id, pattern_type, description, confidence
                    FROM reflection_patterns
                    WHERE pattern_id = :pattern_id
                """)
                pattern_result = db.execute(pattern_query, {"pattern_id": pattern_id})
                pattern_row = pattern_result.fetchone()
                if pattern_row:
                    patterns.append({
                        "pattern_id": pattern_row.pattern_id,
                        "pattern_type": pattern_row.pattern_type,
                        "description": pattern_row.description,
                        "confidence": pattern_row.confidence
                    })

        return {
            "proposal_id": row.proposal_id,
            "target_agent": row.target_agent,
            "target_prompt_section": row.target_prompt_section,
            "proposal_type": row.proposal_type,
            "current_value_summary": row.current_value_summary,
            "proposed_value_summary": row.proposed_value_summary,
            "proposed_value": row.proposed_value,
            "reasoning": row.reasoning,
            "confidence_score": row.confidence_score,
            "evidence_patterns": patterns,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "reviewer_notes": row.reviewer_notes,
            "implemented_at": row.implemented_at.isoformat() if row.implemented_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get proposal {proposal_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reflection/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    approval: ProposalApproval,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Approve a pending proposal.

    The proposal will be queued for implementation.
    """
    from sqlalchemy import text
    from app.services.reflection.proposal_generator import ProposalGeneratorService

    try:
        # Check proposal exists and is pending
        check_query = text("SELECT status FROM prompt_proposals WHERE proposal_id = :id")
        result = db.execute(check_query, {"id": proposal_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if row.status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Proposal is already {row.status}, cannot approve"
            )

        # Process approval
        generator = ProposalGeneratorService(db)
        await generator.process_approval(
            proposal_id=proposal_id,
            approved=True,
            reviewer_notes=approval.notes
        )

        return {
            "status": "approved",
            "proposal_id": proposal_id,
            "message": "Proposal approved and queued for implementation"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve proposal {proposal_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reflection/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    rejection: ProposalRejection,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reject a pending proposal.

    Requires a reason for the rejection.
    """
    from sqlalchemy import text
    from app.services.reflection.proposal_generator import ProposalGeneratorService

    try:
        # Check proposal exists and is pending
        check_query = text("SELECT status FROM prompt_proposals WHERE proposal_id = :id")
        result = db.execute(check_query, {"id": proposal_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")

        if row.status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Proposal is already {row.status}, cannot reject"
            )

        # Process rejection
        generator = ProposalGeneratorService(db)
        await generator.process_approval(
            proposal_id=proposal_id,
            approved=False,
            reviewer_notes=rejection.reason
        )

        return {
            "status": "rejected",
            "proposal_id": proposal_id,
            "message": "Proposal rejected"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject proposal {proposal_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reflection/uncertainties")
async def list_uncertainties(
    resolved: Optional[bool] = Query(None, description="Filter by resolution status"),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List flagged uncertainties requiring David's input.
    """
    from sqlalchemy import text

    try:
        if resolved is not None:
            query = text("""
                SELECT observation_id, category, question_for_david, context,
                       flagged_at, resolved_at, resolution_guidance
                FROM reflection_observations
                WHERE requires_david_input = TRUE
                  AND (resolved_at IS NOT NULL) = :resolved
                ORDER BY flagged_at DESC
                LIMIT :limit
            """)
            result = db.execute(query, {"resolved": resolved, "limit": limit})
        else:
            query = text("""
                SELECT observation_id, category, question_for_david, context,
                       flagged_at, resolved_at, resolution_guidance
                FROM reflection_observations
                WHERE requires_david_input = TRUE
                ORDER BY
                    CASE WHEN resolved_at IS NULL THEN 0 ELSE 1 END,
                    flagged_at DESC
                LIMIT :limit
            """)
            result = db.execute(query, {"limit": limit})

        uncertainties = []
        for row in result:
            uncertainties.append({
                "observation_id": row.observation_id,
                "category": row.category,
                "question_for_david": row.question_for_david,
                "context": row.context,
                "flagged_at": row.flagged_at.isoformat() if row.flagged_at else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                "resolution_guidance": row.resolution_guidance,
                "is_resolved": row.resolved_at is not None
            })

        return {
            "uncertainties": uncertainties,
            "total": len(uncertainties),
            "unresolved_count": sum(1 for u in uncertainties if not u["is_resolved"])
        }

    except Exception as e:
        logger.error(f"Failed to list uncertainties: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reflection/uncertainties/{observation_id}/resolve")
async def resolve_uncertainty(
    observation_id: str,
    resolution: UncertaintyResolution,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Provide guidance to resolve a flagged uncertainty.
    """
    from sqlalchemy import text

    try:
        # Check uncertainty exists and is unresolved
        check_query = text("""
            SELECT resolved_at FROM reflection_observations
            WHERE observation_id = :id AND requires_david_input = TRUE
        """)
        result = db.execute(check_query, {"id": observation_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Uncertainty not found")

        if row.resolved_at is not None:
            raise HTTPException(status_code=400, detail="Uncertainty already resolved")

        # Resolve the uncertainty
        update_query = text("""
            UPDATE reflection_observations
            SET resolved_at = CURRENT_TIMESTAMP,
                resolution_guidance = :guidance
            WHERE observation_id = :id
        """)
        db.execute(update_query, {"id": observation_id, "guidance": resolution.guidance})
        db.commit()

        return {
            "status": "resolved",
            "observation_id": observation_id,
            "message": "Uncertainty resolved with guidance"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve uncertainty {observation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Audio Processing Endpoints ====================

class ProcessedAudioInput(BaseModel):
    """Input from GPU cluster audio worker."""
    transcript: str
    speaker: str = "unknown"
    duration_seconds: float = 0.0
    source: str = "gpu_cluster"
    diarization: Optional[Dict] = None
    metadata: Optional[Dict] = None


@router.post("/audio/processed")
async def receive_processed_audio(
    input_data: ProcessedAudioInput,
    x_internal_service: Optional[str] = Header(None, alias="X-Internal-Service")
):
    """
    Receive processed audio from GPU cluster.

    Called by the audio pipeline worker after Riva/NeMo processing.
    Stores result in raw buffer for cognitive processing.
    """
    from app.tasks.input_processing import process_audio_input

    # Validate internal service header (optional security)
    if x_internal_service != "gpu-audio-worker":
        logger.warning(f"Audio received from unexpected source: {x_internal_service}")

    try:
        result = process_audio_input.delay(
            transcript=input_data.transcript,
            speaker=input_data.speaker,
            duration_seconds=input_data.duration_seconds,
            source=input_data.source,
            diarization=input_data.diarization
        )

        logger.info(f"Processed audio received: {len(input_data.transcript)} chars, speaker={input_data.speaker}")

        return {
            "status": "accepted",
            "task_id": result.id,
            "stream": "raw_buffer:audio"
        }

    except Exception as e:
        logger.error(f"Failed to receive processed audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audio/health")
async def check_audio_services_health(
    current_user=Depends(get_current_user)
):
    """
    Check health of audio processing services (Riva + NeMo).
    """
    from app.services.audio.riva_client import get_riva_client
    from app.services.audio.diarization_service import get_diarization_service
    from app.services.audio.speaker_service import get_speaker_service

    results = {}

    try:
        riva = await get_riva_client()
        results["riva"] = await riva.check_health()
    except Exception as e:
        results["riva"] = {"status": "error", "error": str(e)}

    try:
        diarization = await get_diarization_service()
        results["diarization"] = await diarization.check_health()
    except Exception as e:
        results["diarization"] = {"status": "error", "error": str(e)}

    try:
        speaker = await get_speaker_service()
        results["speaker_enrollment"] = await speaker.check_health()
    except Exception as e:
        results["speaker_enrollment"] = {"status": "error", "error": str(e)}

    # Overall status
    all_healthy = all(
        r.get("status") == "healthy"
        for r in results.values()
    )

    return {
        "overall_status": "healthy" if all_healthy else "degraded",
        "services": results
    }


# ==================== Speaker Enrollment Endpoints ====================

class SpeakerEnrollmentInput(BaseModel):
    """Input for speaker enrollment."""
    speaker_id: str
    audio_paths: List[str]
    display_name: Optional[str] = None


@router.post("/speakers/enroll")
async def enroll_speaker(
    input_data: SpeakerEnrollmentInput,
    current_user=Depends(get_current_user)
):
    """
    Enroll a new speaker for recognition.

    Requires 1-5 audio samples of the speaker.
    """
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()
        result = await speaker_service.enroll_speaker(
            speaker_id=input_data.speaker_id,
            audio_paths=input_data.audio_paths,
            display_name=input_data.display_name
        )

        logger.info(f"Enrolled speaker: {input_data.speaker_id}")
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Speaker enrollment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/speakers")
async def list_enrolled_speakers(
    current_user=Depends(get_current_user)
):
    """
    List all enrolled speakers.
    """
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()
        speakers = await speaker_service.list_speakers()

        return {
            "speakers": [
                {
                    "speaker_id": s.speaker_id,
                    "display_name": s.display_name,
                    "num_samples": s.num_samples
                }
                for s in speakers
            ]
        }

    except Exception as e:
        logger.error(f"Failed to list speakers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/speakers/{speaker_id}")
async def get_speaker(
    speaker_id: str,
    current_user=Depends(get_current_user)
):
    """
    Get details for a specific speaker.
    """
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()
        speaker = await speaker_service.get_speaker(speaker_id)

        if not speaker:
            raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

        return {
            "speaker_id": speaker.speaker_id,
            "display_name": speaker.display_name,
            "num_samples": speaker.num_samples
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get speaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/speakers/{speaker_id}")
async def delete_speaker(
    speaker_id: str,
    current_user=Depends(get_current_user)
):
    """
    Delete an enrolled speaker.
    """
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()
        deleted = await speaker_service.delete_speaker(speaker_id)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Speaker not found: {speaker_id}")

        return {"status": "deleted", "speaker_id": speaker_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete speaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/speakers/david/status")
async def check_david_enrollment(
    current_user=Depends(get_current_user)
):
    """
    Check if David is enrolled for speaker recognition.
    """
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()
        is_enrolled = await speaker_service.is_david_enrolled()

        speaker = None
        if is_enrolled:
            speaker = await speaker_service.get_speaker("david")

        return {
            "is_enrolled": is_enrolled,
            "speaker_id": "david" if is_enrolled else None,
            "num_samples": speaker.num_samples if speaker else 0
        }

    except Exception as e:
        logger.error(f"Failed to check David enrollment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
