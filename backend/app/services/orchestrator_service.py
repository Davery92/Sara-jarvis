"""
Orchestrator Service - Multi-agent task orchestration with tool calling

Devstral acts as an orchestrator agent with tools to spawn worker agents.
It decides naturally when to delegate tasks to workers.

When used with real tools (db session provided), workers have:
- Real web search via Tavily/SearXNG
- Real URL content extraction
- READ-ONLY access to user's notes, calendar, memories
- Write access ONLY to agent workspace
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Ollama configuration — centralized
from app.core.llm_config import llm_config as _llm_cfg
ORCHESTRATOR_OLLAMA_URL = _llm_cfg.primary_url.replace('/v1', '')
ORCHESTRATOR_MODEL = _llm_cfg.fast_model

WORKER_OLLAMA_URL = _llm_cfg.primary_url.replace('/v1', '')
WORKER_MODEL = _llm_cfg.fast_model

# Tools available to the orchestrator
ORCHESTRATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "spawn_worker",
            "description": "Spawn a worker agent to research a specific topic. Use this to delegate research tasks that can run in parallel. The worker will return a detailed report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The specific research task for the worker (e.g., 'Research Cursor IDE features and pricing')"
                    },
                    "focus_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific areas to focus on (e.g., ['features', 'pricing', 'pros and cons'])"
                    }
                },
                "required": ["task"]
            }
        }
    }
]

# Tools available to workers (mock implementations)
WORKER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information on a topic. Returns a list of relevant search results with titles, snippets, and URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 5, max 10)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Fetch and read the content of a specific URL. Returns the main text content of the page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch and read"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_notes",
            "description": "Save important findings to your notes. Use this to record key information you've discovered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "A short title for this note"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content/findings to save"
                    }
                },
                "required": ["title", "content"]
            }
        }
    }
]

WORKER_SYSTEM_PROMPT = """You are a research worker agent. Your job is to thoroughly research the given topic using the tools available to you.

Available tools:
- web_search: Search the web for information
- read_url: Read the full content of a specific URL
- take_notes: Save important findings

Strategy:
1. Start by searching for relevant information on the topic
2. Read promising URLs to get detailed information
3. Take notes on key findings as you go
4. Continue searching and reading until you have comprehensive information
5. When done, provide a final summary of your research

Be thorough but efficient. Use multiple searches if needed to cover different aspects of the topic."""


# Mock tool implementations for testing
def mock_web_search(query: str, num_results: int = 5) -> str:
    """Generate mock search results based on the query"""
    import hashlib

    # Generate deterministic but varied results based on query
    query_hash = int(hashlib.md5(query.encode()).hexdigest()[:8], 16)

    mock_domains = [
        "techcrunch.com", "wired.com", "theverge.com", "arstechnica.com",
        "zdnet.com", "cnet.com", "engadget.com", "venturebeat.com",
        "medium.com", "dev.to", "github.com", "stackoverflow.com"
    ]

    results = []
    for i in range(min(num_results, 10)):
        domain = mock_domains[(query_hash + i) % len(mock_domains)]
        results.append({
            "title": f"{query} - Result {i+1} from {domain}",
            "url": f"https://{domain}/article/{query_hash + i}",
            "snippet": f"This is a mock search result about '{query}'. It contains relevant information about the topic including features, comparisons, and expert opinions. Published recently with updated information for 2024."
        })

    return json.dumps({"results": results, "query": query, "total_results": num_results}, indent=2)


def mock_read_url(url: str) -> str:
    """Generate mock page content based on the URL"""
    import hashlib

    url_hash = int(hashlib.md5(url.encode()).hexdigest()[:8], 16)

    # Extract topic hints from URL
    topic = url.split("/")[-1].replace("-", " ").replace("_", " ")

    paragraphs = [
        f"# Article about {topic}",
        f"\nThis comprehensive article covers everything you need to know about {topic}.",
        f"\n## Key Features\n- Feature 1: Advanced capabilities for modern workflows\n- Feature 2: Seamless integration with existing tools\n- Feature 3: Competitive pricing starting at $10/month\n- Feature 4: 24/7 customer support",
        f"\n## Pros and Cons\n**Pros:**\n- Easy to use interface\n- Regular updates and improvements\n- Strong community support\n\n**Cons:**\n- Learning curve for advanced features\n- Some features require premium subscription",
        f"\n## Pricing\n- Free tier available with basic features\n- Pro plan: $15/month\n- Enterprise: Custom pricing",
        f"\n## Conclusion\nOverall, {topic} is a solid choice for teams looking to improve their productivity. The combination of features and pricing makes it competitive in the market.",
        f"\n*Last updated: December 2024*"
    ]

    return "\n".join(paragraphs)


def mock_take_notes(title: str, content: str) -> str:
    """Mock saving notes - just acknowledge the save"""
    return json.dumps({
        "status": "saved",
        "title": title,
        "content_length": len(content),
        "message": f"Note '{title}' saved successfully"
    })

ORCHESTRATOR_SYSTEM_PROMPT = """You are an orchestrator agent that helps with research and analysis tasks.

You have access to worker agents that can help you research specific topics in parallel. Use the spawn_worker tool to delegate research tasks.

Strategy:
1. When given a complex research task, break it down into specific subtasks
2. Use spawn_worker for each subtask - workers run in parallel so spawn multiple at once
3. Wait for all workers to complete
4. Synthesize the results into a comprehensive response

Be efficient - spawn workers for distinct topics that can be researched independently.
After receiving worker results, provide a thorough synthesis with comparisons and recommendations."""


class OrchestratorService:
    """Manages orchestration using tool-calling pattern"""

    def __init__(
        self,
        db: Optional[Session] = None,
        user_id: Optional[str] = None,
        workspace_folder_id: Optional[str] = None,
        orchestrator_model: Optional[str] = None,
        worker_model: Optional[str] = None
    ):
        """
        Initialize orchestrator service.

        Args:
            db: Optional database session for real tool access
            user_id: Optional user ID for scoping data access
            workspace_folder_id: Optional workspace folder ID for note creation
            orchestrator_model: Optional custom model for orchestrator (defaults to ORCHESTRATOR_MODEL)
            worker_model: Optional custom model for workers (defaults to WORKER_MODEL)

        If db/user_id are provided, workers will use real tools (web search,
        URL reading, Sara data access). Otherwise, mock tools are used.
        """
        self.orchestrator_url = ORCHESTRATOR_OLLAMA_URL
        self.worker_url = WORKER_OLLAMA_URL
        self.orchestrator_model = orchestrator_model or ORCHESTRATOR_MODEL
        self.worker_model = worker_model or WORKER_MODEL
        self.pending_workers: Dict[str, asyncio.Task] = {}
        self.worker_results: Dict[str, Dict] = {}
        self.worker_counter = 0

        # Real tools support
        self.db = db
        self.user_id = user_id
        self.workspace_folder_id = workspace_folder_id
        self.use_real_tools = db is not None and user_id is not None

        # Initialize tool executor if using real tools
        self.tool_executor = None
        if self.use_real_tools:
            from .worker_tools import WorkerToolExecutor
            self.tool_executor = WorkerToolExecutor(db, user_id, workspace_folder_id)
            logger.info(f"Orchestrator initialized with REAL tools for user {user_id}")
        else:
            logger.info("Orchestrator initialized with MOCK tools")

    async def run_task(
        self,
        query: str,
        event_callback: Callable[[Dict[str, Any]], Any]
    ) -> Dict[str, Any]:
        """Execute orchestration with tool calling"""
        start_time = time.time()

        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": query}
        ]

        try:
            await event_callback({
                "phase": "thinking",
                "message": f"Orchestrator ({self.orchestrator_model}) analyzing task...",
                "model": self.orchestrator_model
            })

            # Agentic loop - keep going until no more tool calls
            max_iterations = 20  # Orchestrator may need multiple rounds to coordinate workers
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                # Call orchestrator
                response = await self._call_orchestrator(messages)

                if "error" in response:
                    await event_callback({
                        "phase": "error",
                        "message": f"Orchestrator error: {response['error']}",
                        "raw_response": response.get("raw_response", "")
                    })
                    return response

                assistant_message = response.get("message", {})
                messages.append(assistant_message)

                # Check for tool calls
                tool_calls = assistant_message.get("tool_calls", [])

                if not tool_calls:
                    # No tool calls - orchestrator is done
                    final_content = assistant_message.get("content", "")

                    total_time = time.time() - start_time
                    await event_callback({
                        "phase": "complete",
                        "message": "Orchestration complete",
                        "final_response": final_content,
                        "total_duration_ms": int(total_time * 1000)
                    })

                    return {
                        "response": final_content,
                        "total_duration_ms": int(total_time * 1000),
                        "iterations": iteration
                    }

                # Process tool calls - spawn workers in parallel
                # Send detailed tool call information
                detailed_tool_calls = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        args = {"raw": args_str}
                    detailed_tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "arguments": args
                    })

                await event_callback({
                    "phase": "spawning_workers",
                    "message": f"Spawning {len(tool_calls)} worker(s)...",
                    "tool_calls": [tc.get("function", {}).get("name") for tc in tool_calls],
                    "tool_calls_detailed": detailed_tool_calls
                })

                # Execute all tool calls in parallel
                tool_results = await self._execute_tool_calls(tool_calls, event_callback)

                # Add tool results to messages
                for tool_call, result in zip(tool_calls, tool_results):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": result
                    })

                await event_callback({
                    "phase": "workers_complete",
                    "message": f"All workers complete, synthesizing results...",
                    "results_count": len(tool_results)
                })

            # Max iterations reached
            return {
                "error": "Max iterations reached",
                "partial_response": messages[-1].get("content", "")
            }

        except Exception as e:
            logger.exception("Orchestration failed")
            await event_callback({
                "phase": "error",
                "message": str(e)
            })
            return {"error": str(e)}

    async def _call_orchestrator(self, messages: List[Dict]) -> Dict[str, Any]:
        """Call orchestrator model with tools"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.orchestrator_url}/api/chat",
                    json={
                        "model": self.orchestrator_model,
                        "messages": messages,
                        "tools": ORCHESTRATOR_TOOLS,
                        "stream": False,
                        "options": {
                            "temperature": 0.7,
                            "num_predict": 4096
                        }
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling orchestrator: {e}")
            return {"error": f"Failed to connect to orchestrator: {e}"}
        except Exception as e:
            logger.error(f"Error calling orchestrator: {e}")
            return {"error": str(e)}

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict],
        event_callback: Callable
    ) -> List[str]:
        """Execute tool calls in parallel"""

        async def execute_single(tool_call: Dict) -> str:
            func = tool_call.get("function", {})
            name = func.get("name", "")

            # Parse arguments
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            if name == "spawn_worker":
                return await self._spawn_worker(
                    task=args.get("task", ""),
                    focus_areas=args.get("focus_areas", []),
                    event_callback=event_callback
                )
            else:
                return f"Unknown tool: {name}"

        # Run all tool calls in parallel
        results = await asyncio.gather(
            *[execute_single(tc) for tc in tool_calls],
            return_exceptions=True
        )

        # Convert exceptions to error strings
        return [
            str(r) if isinstance(r, Exception) else r
            for r in results
        ]

    async def _spawn_worker(
        self,
        task: str,
        focus_areas: List[str],
        event_callback: Callable
    ) -> str:
        """Spawn a worker agent with its own agentic tool-calling loop"""
        self.worker_counter += 1
        worker_id = self.worker_counter

        start_time = time.time()

        # Build worker prompt
        focus_str = ", ".join(focus_areas) if focus_areas else "general aspects"
        worker_prompt = f"""Research the following topic thoroughly using the tools available to you.

Topic: {task}
Focus areas: {focus_str}

Use web_search to find information, read_url to get details from specific pages, and take_notes to record important findings.
When you have gathered enough information, provide a comprehensive summary."""

        # Select appropriate system prompt based on mode
        if self.use_real_tools:
            from .worker_tools import WORKER_SYSTEM_PROMPT as REAL_WORKER_SYSTEM_PROMPT
            system_prompt = REAL_WORKER_SYSTEM_PROMPT
            tools_list = ["web_search", "read_url", "take_notes", "read_notes", "read_calendar", "read_memories"]
        else:
            system_prompt = WORKER_SYSTEM_PROMPT
            tools_list = ["web_search", "read_url", "take_notes"]

        await event_callback({
            "phase": "worker_started",
            "worker_id": worker_id,
            "task": task,
            "focus_areas": focus_areas,
            "model": self.worker_model,
            "worker_prompt": worker_prompt,
            "tools_available": tools_list,
            "using_real_tools": self.use_real_tools
        })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": worker_prompt}
        ]

        # Track tool calls for this worker
        worker_tool_calls = []
        max_iterations = 30  # Allow enough iterations for thorough research
        iteration = 0

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                while iteration < max_iterations:
                    iteration += 1

                    # Select appropriate tools based on mode
                    if self.use_real_tools:
                        from .worker_tools import WORKER_TOOLS as REAL_WORKER_TOOLS
                        worker_tools = REAL_WORKER_TOOLS
                    else:
                        worker_tools = WORKER_TOOLS

                    # Call worker model with tools
                    response = await client.post(
                        f"{self.worker_url}/api/chat",
                        json={
                            "model": self.worker_model,
                            "messages": messages,
                            "tools": worker_tools,
                            "stream": False,
                            "options": {
                                "temperature": 0.5,
                                "num_predict": 2048
                            }
                        }
                    )
                    response.raise_for_status()
                    data = response.json()

                    assistant_message = data.get("message", {})
                    messages.append(assistant_message)

                    # Check for tool calls
                    tool_calls = assistant_message.get("tool_calls", [])

                    if not tool_calls:
                        # No more tool calls - worker is done
                        final_content = assistant_message.get("content", "No response")
                        break

                    # Execute worker tool calls
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        tool_name = func.get("name", "")
                        args_str = func.get("arguments", "{}")

                        try:
                            args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except json.JSONDecodeError:
                            args = {}

                        # Execute tool - real or mock based on configuration
                        if self.use_real_tools and self.tool_executor:
                            # Use real tool executor
                            tool_result = await self.tool_executor.execute_tool(tool_name, args)
                        else:
                            # Fallback to mock tools
                            if tool_name == "web_search":
                                tool_result = mock_web_search(
                                    query=args.get("query", ""),
                                    num_results=args.get("num_results", 5)
                                )
                            elif tool_name == "read_url":
                                tool_result = mock_read_url(url=args.get("url", ""))
                            elif tool_name == "take_notes":
                                tool_result = mock_take_notes(
                                    title=args.get("title", ""),
                                    content=args.get("content", "")
                                )
                            else:
                                tool_result = f"Unknown tool: {tool_name}"

                        # Record tool call for event
                        tool_call_record = {
                            "tool": tool_name,
                            "arguments": args,
                            "result_preview": tool_result[:200] + "..." if len(tool_result) > 200 else tool_result,
                            "result_full": tool_result
                        }
                        worker_tool_calls.append(tool_call_record)

                        # Send event for this tool call
                        await event_callback({
                            "phase": "worker_tool_call",
                            "worker_id": worker_id,
                            "task": task,
                            "iteration": iteration,
                            "tool_name": tool_name,
                            "tool_arguments": args,
                            "tool_result_preview": tool_result[:300] + "..." if len(tool_result) > 300 else tool_result,
                            "tool_result_full": tool_result
                        })

                        # Add tool result to messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": tool_result
                        })

                else:
                    # Max iterations reached
                    final_content = f"Worker reached max iterations ({max_iterations}). Last response: {messages[-1].get('content', '')}"

            duration_ms = int((time.time() - start_time) * 1000)

            await event_callback({
                "phase": "worker_complete",
                "worker_id": worker_id,
                "task": task,
                "focus_areas": focus_areas,
                "result_preview": final_content[:200] + "..." if len(final_content) > 200 else final_content,
                "result_full": final_content,
                "result_length": len(final_content),
                "duration_ms": duration_ms,
                "iterations": iteration,
                "tool_calls_count": len(worker_tool_calls),
                "tool_calls_summary": [{"tool": tc["tool"], "args": tc["arguments"]} for tc in worker_tool_calls]
            })

            return f"[Worker {worker_id} Report - {task}]\n\n{final_content}"

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e) if str(e) else f"Unknown error: {type(e).__name__}"
            logger.error(f"Worker {worker_id} failed: {error_msg}")

            await event_callback({
                "phase": "worker_error",
                "worker_id": worker_id,
                "task": task,
                "error": error_msg,
                "duration_ms": duration_ms,
                "iterations": iteration,
                "tool_calls_count": len(worker_tool_calls)
            })

            return f"[Worker {worker_id} Error - {task}]\n\nFailed to complete research: {error_msg}"
