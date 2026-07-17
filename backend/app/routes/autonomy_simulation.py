"""
Autonomy simulation routes — manual dry-run endpoint for action simulation.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.services.autonomy.action_simulator import action_simulator
from app.services.autonomy.policy_engine import policy_engine
from app.services.autonomy.action_tracer import get_risk_tier

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


class SimulateRequest(BaseModel):
    action_name: str
    action_args: Optional[Dict[str, Any]] = None


class SimulateResponse(BaseModel):
    action_name: str
    risk_tier: int
    simulation: Dict[str, Any]
    policy_decision: str
    policy_reason: str


@router.post("/simulate", response_model=SimulateResponse)
async def simulate_action(
    request: SimulateRequest,
    current_user=Depends(get_current_user),
):
    """
    Dry-run an action through simulation and policy checks.
    Does not execute anything — returns what would happen.
    """
    # Simulate
    sim_result = await action_simulator.simulate(
        action_name=request.action_name,
        action_args=request.action_args,
    )

    # Policy check
    risk_tier = get_risk_tier(request.action_name)
    policy_result = policy_engine.evaluate(
        action_name=request.action_name,
        action_args=request.action_args,
        confidence=0.5,  # Default for dry-run
    )

    return SimulateResponse(
        action_name=request.action_name,
        risk_tier=risk_tier,
        simulation=sim_result.to_json(),
        policy_decision=policy_result.decision,
        policy_reason=policy_result.reason,
    )
