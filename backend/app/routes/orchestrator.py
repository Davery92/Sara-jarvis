"""
Orchestrator API Routes - WebSocket endpoint for live orchestration
"""

import logging
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.orchestrator_service import OrchestratorService, ORCHESTRATOR_OLLAMA_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.get("/models")
async def list_available_models():
    """
    Fetch available models from the Ollama server.
    Returns a list of model names that can be used for orchestration.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ORCHESTRATOR_OLLAMA_URL}/api/tags")
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                name = model.get("name", "")
                size = model.get("size", 0)
                # Convert size to human readable
                size_gb = size / (1024 ** 3) if size else 0
                models.append({
                    "name": name,
                    "size": f"{size_gb:.1f}GB" if size_gb > 0 else "unknown",
                    "modified_at": model.get("modified_at", ""),
                    "details": model.get("details", {})
                })

            # Sort by name
            models.sort(key=lambda x: x["name"])

            return {
                "models": models,
                "ollama_url": ORCHESTRATOR_OLLAMA_URL
            }

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch models from Ollama: {e}")
        return {
            "models": [],
            "error": f"Failed to connect to Ollama: {str(e)}",
            "ollama_url": ORCHESTRATOR_OLLAMA_URL
        }
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        return {
            "models": [],
            "error": str(e),
            "ollama_url": ORCHESTRATOR_OLLAMA_URL
        }


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

        # Get optional model parameters
        orchestrator_model = data.get("orchestrator_model")
        worker_model = data.get("worker_model")

        logger.info(f"Starting orchestration for query: {query[:100]}...")
        if orchestrator_model:
            logger.info(f"Using custom orchestrator model: {orchestrator_model}")
        if worker_model:
            logger.info(f"Using custom worker model: {worker_model}")

        # Create service and event callback
        service = OrchestratorService(
            orchestrator_model=orchestrator_model,
            worker_model=worker_model
        )

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
                "url": "http://100.104.68.115:8080",
                "model": "Qwen3.5-35B-A3B"
            },
            "worker": {
                "url": "http://100.104.68.115:8080",
                "model": "Qwen3.5-35B-A3B"
            }
        }
    }
