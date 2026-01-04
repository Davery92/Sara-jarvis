"""
Orchestrator API Routes - WebSocket endpoint for live orchestration
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.websocket("/stream")
async def orchestrator_stream(websocket: WebSocket):
    """
    WebSocket endpoint for live orchestration updates.

    Protocol:
    1. Client connects and sends: {"query": "research task description"}
    2. Server streams events as JSON messages
    3. Connection closes when task completes or errors

    Event types:
    - decomposing: Task analysis started
    - decomposed: Subtasks created
    - worker_started: Worker began processing
    - worker_complete: Worker finished successfully
    - worker_error: Worker failed
    - consolidating: Synthesis started
    - complete: Final report ready
    - error: Fatal error occurred
    """
    await websocket.accept()
    logger.info("Orchestrator WebSocket connection accepted")

    try:
        # Wait for initial query
        data = await websocket.receive_json()
        query = data.get("query")

        if not query:
            await websocket.send_json({
                "phase": "error",
                "message": "No query provided",
                "recoverable": False
            })
            await websocket.close()
            return

        logger.info(f"Starting orchestration for query: {query[:100]}...")

        # Create service and event callback
        service = OrchestratorService()

        async def send_event(event: Dict[str, Any]):
            """Send event to WebSocket client"""
            try:
                await websocket.send_json(event)
                logger.debug(f"Sent event: {event.get('phase')}")
            except Exception as e:
                logger.error(f"Failed to send event: {e}")

        # Run orchestration
        result = await service.run_task(query, send_event)

        # Send final completion if not already sent
        if "error" not in result:
            logger.info("Orchestration completed successfully")
        else:
            logger.warning(f"Orchestration completed with error: {result.get('error')}")

    except WebSocketDisconnect:
        logger.info("Client disconnected from orchestrator WebSocket")
    except Exception as e:
        logger.exception("Orchestrator WebSocket error")
        try:
            await websocket.send_json({
                "phase": "error",
                "message": str(e),
                "recoverable": False
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/status")
async def orchestrator_status():
    """Get orchestrator service status and configuration"""
    return {
        "status": "available",
        "config": {
            "orchestrator": {
                "url": "http://100.104.68.115:11434",
                "model": "gpt-oss:20b"
            },
            "worker": {
                "url": "http://100.104.68.115:11434",
                "model": "gpt-oss:20b"
            }
        }
    }
