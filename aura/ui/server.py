"""FastAPI control panel for AURA's Nexus UI."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from dataclasses import dataclass, field, is_dataclass, asdict
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import aura
from aura.core.auth import AuthError, AuthManager
from aura.agents.aegis import tools as aegis_tools
from aura.agents.director import tools as director_tools
from aura.agents.lyra import tools as lyra_tools
from aura.agents.oracle_deep import tools as oracle_tools
from aura.agents.phantom import tools as phantom_tools
from aura.agents.mosaic import tools as mosaic_tools
from aura.agents.stream import tools as stream_tools
from aura.core.agent_loop import ReActAgentLoop
from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.llm_router import OllamaRouter
from aura.core.logging import get_logger
from aura.core.tools import get_tool_registry
from aura.core.multiagent.dispatcher import A2ADispatcher
from aura.core.multiagent.mcp_server import call_mcp_tool, list_mcp_tools
from aura.core.multiagent.orchestrator import NexusOrchestrator
from aura.core.multiagent.registry import AgentRegistry
from aura.memory import delete_memory, list_memories, recall_memory

LOGGER = get_logger(__name__, component="nexus")
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"
ASSETS_DIR = STATIC_DIR / "assets"
PLACEHOLDER_INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AURA</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }
      a { color: #2dd4bf; }
      .card { max-width: 42rem; padding: 1.5rem; border: 1px solid #334155; background: #111827; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>AURA is running</h1>
      <p>The frontend bundle is not present yet, so this fallback page is shown.</p>
      <p><a href="/health">Health</a> · <a href="/docs">API docs</a></p>
    </div>
  </body>
</html>
"""
EVENT_TYPES = {
    "director.event",
    "lyra.wake_word_detected",
    "lyra.speaking_started",
    "hermes.action",
    "phantom.task_run",
    "phantom.watch_triggered",
    "aegis.tier3_request",
    "mneme.memory_saved",
    "aura.error",
}
AUTH_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/register",
    "/api/auth/login",
    "/api/auth/register",
}

_CORS_ORIGINS = [
    "https://aura-khaki-seven.vercel.app",
    "http://localhost:5173",
    "http://localhost:3000",
]


class MessageRequest(BaseModel):
    text: str
    importance: int = Field(default=2, ge=1, le=4)


class VoiceModeRequest(BaseModel):
    enabled: bool


class OracleAnalyzeRequest(BaseModel):
    question: str
    use_iris: bool = True
    context: str | None = None


class OracleWhatIfRequest(BaseModel):
    change: str
    base_state: str | None = None


@dataclass(slots=True)
class NexusRuntime:
    """Runtime services exposed to the UI."""

    config: AppConfig
    event_bus: EventBus
    agent_loop: ReActAgentLoop
    orchestrator: NexusOrchestrator | None = None
    auth_manager: AuthManager | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_token: str | None = None


def _default_runtime() -> NexusRuntime:
    config = load_config()
    event_bus = EventBus()
    # Read secret from config.auth.secret (correct attr name) then env fallback.
    auth_secret = (
        getattr(getattr(config, "auth", None), "secret", None)
        or os.getenv("AURA_JWT_SECRET")
        or os.getenv("JWT_SECRET")
        or None
    )
    auth_manager = AuthManager(config.paths.data_dir, secret=auth_secret)
    return NexusRuntime(
        config=config,
        event_bus=event_bus,
        agent_loop=ReActAgentLoop(
            router=OllamaRouter(
                model=config.primary_model.name,
                host=config.primary_model.host,
            ),
            registry=get_tool_registry(),
            event_bus=event_bus,
        ),
        auth_manager=auth_manager,
    )


STATIC_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
if not INDEX_PATH.exists():
    INDEX_PATH.write_text(PLACEHOLDER_INDEX, encoding="utf-8")


_RUNTIME: NexusRuntime = _default_runtime()
_CONNECTED_CLIENTS: set[WebSocket] = set()
_CLIENT_CONNECTIONS: dict[str, WebSocket] = {}
_CLIENT_TOOL_FUTURES: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
_EVENT_BRIDGE_READY = False


def configure_runtime(
    config: AppConfig | None = None,
    event_bus: EventBus | None = None,
    agent_loop: ReActAgentLoop | None = None,
    orchestrator: NexusOrchestrator | None = None,
    auth_manager: AuthManager | None = None,
) -> None:
    """Update the runtime dependencies used by the UI."""

    global _RUNTIME, _EVENT_BRIDGE_READY
    current = _RUNTIME
    _RUNTIME = NexusRuntime(
        config=config or current.config,
        event_bus=event_bus or current.event_bus,
        agent_loop=agent_loop or current.agent_loop,
        orchestrator=orchestrator or current.orchestrator,
        auth_manager=auth_manager or current.auth_manager,
        started_at=current.started_at,
    )
    _EVENT_BRIDGE_READY = False
    app.state.runtime = _RUNTIME


def get_runtime() -> NexusRuntime:
    """Return the active UI runtime."""

    return getattr(app.state, "runtime", _RUNTIME)


def _auth_manager() -> AuthManager | None:
    return get_runtime().auth_manager


def _require_token(request: Request) -> str | None:
    manager = _auth_manager()
    if manager is None:
        return None
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return manager.verify_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _workflow_summary(plan: Any) -> dict[str, Any]:
    steps = list(getattr(plan, "steps", []) or [])
    current_step = next(
        (s for s in steps if getattr(s, "status", "") not in {"done", "skipped"}),
        steps[-1] if steps else None,
    )
    return {
        "id": getattr(plan, "id", ""),
        "name": getattr(plan, "name", ""),
        "status": getattr(plan, "status", ""),
        "current_step": getattr(current_step, "description", "") if current_step is not None else "",
        "total_steps": len(steps),
        "started_at": _serialize(getattr(plan, "started_at", None)),
    }


def _phantom_summary(task: Any) -> dict[str, Any]:
    return {
        "id": getattr(task, "id", ""),
        "name": getattr(task, "name", ""),
        "next_run": _serialize(getattr(task, "next_run", None)),
        "last_run": _serialize(getattr(task, "last_run", None)),
        "status": "enabled" if getattr(task, "enabled", True) else "disabled",
    }


def _memory_summary(record: Any) -> dict[str, Any]:
    return {
        "id": getattr(record, "id", ""),
        "key": getattr(record, "key", ""),
        "category": getattr(record, "category", ""),
        "preview": str(getattr(record, "value", ""))[:160],
        "timestamp": getattr(record, "updated_at", getattr(record, "created_at", "")),
    }


def _lyra_status(runtime: NexusRuntime) -> dict[str, Any]:
    lyra_config = getattr(runtime.config, "lyra", None)
    return {
        "enabled": bool(getattr(lyra_config, "enabled", False)),
        "listening": lyra_tools.is_wake_word_listener_running(),
        "voice_mode": bool(getattr(lyra_config, "voice_mode", False)),
        "wake_engine": str(getattr(lyra_config, "wake_word_engine", "energy_threshold")),
    }


def _system_health() -> dict[str, Any]:
    snapshot = aegis_tools.get_system_info()
    return {
        "cpu_pct": snapshot.cpu_percent,
        "ram_pct": snapshot.ram_percent,
        "disk_pct": snapshot.disk_percent,
        "uptime": snapshot.uptime_seconds,
    }


def build_state_snapshot(runtime: NexusRuntime | None = None) -> dict[str, Any]:
    """Build the daemon state snapshot used by the UI."""

    runtime = runtime or get_runtime()
    try:
        workflows = director_tools.list_workflows(status_filter=None, limit=50)
    except Exception:
        workflows = []
    try:
        phantom_tasks = phantom_tools.list_workflows()
    except Exception:
        phantom_tasks = []
    try:
        memories = list_memories(limit=10)
    except Exception:
        memories = []
    return {
        "active_workflows": [
            _workflow_summary(w)
            for w in workflows
            if getattr(w, "status", "") in {"running", "paused", "pending_approval", "waiting_approval", "planned"}
        ],
        "phantom_tasks": [_phantom_summary(t) for t in phantom_tasks],
        "recent_memories": [_memory_summary(m) for m in memories],
        "lyra_status": _lyra_status(runtime),
        "system_health": _system_health(),
    }


async def _broadcast_event(topic: str, payload: Any) -> None:
    message = {
        "type": topic,
        "data": _serialize(payload),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    dead: list[WebSocket] = []
    for client in list(_CONNECTED_CLIENTS):
        try:
            await client.send_json(message)
        except Exception:
            dead.append(client)
    for client in dead:
        _CONNECTED_CLIENTS.discard(client)


async def _send_client_message(user_id: str, payload: dict[str, Any]) -> None:
    ws = _CLIENT_CONNECTIONS.get(user_id)
    if ws is None:
        raise ConnectionError("client not connected")
    await ws.send_json(payload)


async def request_local_tool(
    user_id: str,
    tool: str,
    args: dict[str, Any],
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    call_id = secrets.token_hex(16)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    _CLIENT_TOOL_FUTURES[call_id] = (user_id, future)
    try:
        await _send_client_message(
            user_id,
            {"action": "tool_call", "tool": tool, "args": args, "call_id": call_id},
        )
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    finally:
        _CLIENT_TOOL_FUTURES.pop(call_id, None)


async def _ensure_event_bridge() -> None:
    global _EVENT_BRIDGE_READY
    if _EVENT_BRIDGE_READY:
        return
    runtime = get_runtime()
    runtime.event_token = await runtime.event_bus.subscribe("*", _broadcast_event)
    _EVENT_BRIDGE_READY = True


async def _shutdown_event_bridge() -> None:
    global _EVENT_BRIDGE_READY
    runtime = get_runtime()
    if runtime.event_token is not None:
        await runtime.event_bus.unsubscribe("*", runtime.event_token)
        runtime.event_token = None
    _EVENT_BRIDGE_READY = False
    for client in list(_CONNECTED_CLIENTS):
        try:
            await client.close()
        except Exception:
            continue
    _CONNECTED_CLIENTS.clear()


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.runtime = _RUNTIME
    await _ensure_event_bridge()
    try:
        yield
    finally:
        await _shutdown_event_bridge()


app = FastAPI(title="AURA Nexus UI", version=aura.__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    runtime = get_runtime()
    path = request.url.path
    if (
        runtime.auth_manager is not None
        and path not in AUTH_EXEMPT_PATHS
        and (path.startswith("/api/") or path.startswith("/a2a/") or path.startswith("/mcp/"))
    ):
        _require_token(request)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if INDEX_PATH.exists():
        return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(PLACEHOLDER_INDEX)


@app.get("/health")
async def health() -> dict[str, Any]:
    runtime = get_runtime()
    uptime_seconds = int((datetime.now(timezone.utc) - runtime.started_at).total_seconds())
    return {"status": "ok", "version": aura.__version__, "uptime_seconds": uptime_seconds}


@app.post("/auth/register")
async def auth_register(payload: dict[str, str]) -> dict[str, Any]:
    manager = _auth_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="authentication unavailable")
    if not payload.get("username") or not payload.get("password"):
        raise HTTPException(status_code=422, detail="username and password required")
    try:
        return manager.register(payload["username"], payload["password"])
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/auth/register")
async def api_auth_register(payload: dict[str, str]) -> dict[str, Any]:
    return await auth_register(payload)


@app.post("/auth/login")
async def auth_login(payload: dict[str, str]) -> dict[str, Any]:
    manager = _auth_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="authentication unavailable")
    if not payload.get("username") or not payload.get("password"):
        raise HTTPException(status_code=422, detail="username and password required")
    try:
        return manager.login(payload["username"], payload["password"])
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/auth/login")
async def api_auth_login(payload: dict[str, str]) -> dict[str, Any]:
    return await auth_login(payload)


@app.get("/auth/me")
async def auth_me(request: Request) -> dict[str, Any]:
    manager = _auth_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="authentication unavailable")
    user_id = _require_token(request)
    return {"user_id": user_id}


@app.get("/api/auth/me")
async def api_auth_me(request: Request) -> dict[str, Any]:
    return await auth_me(request)


@app.get("/api/state")
async def api_state() -> dict[str, Any]:
    return build_state_snapshot()


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    runtime = get_runtime()
    memory_ok = True
    try:
        list_memories(limit=1)
    except Exception:
        memory_ok = False
    model_name = str(getattr(getattr(runtime.config, "primary_model", None), "name", ""))
    local_pc_ok = not aegis_tools.HF_SPACE
    return {
        "router": {"ok": bool(model_name), "model": model_name},
        "memory": {"ok": memory_ok},
        "local_pc": {"ok": local_pc_ok},
        "status": "ok" if model_name and memory_ok else "degraded",
    }


@app.post("/api/message", response_model=None)
async def api_message(
    payload: MessageRequest, request: Request
) -> StreamingResponse | dict[str, Any]:
    runtime = get_runtime()
    user_id = _require_token(request) or "local"
    accept = request.headers.get("accept", "")

    def _result_value(result: Any, key: str, default: Any = None) -> Any:
        if isinstance(result, dict):
            return result.get(key, default)
        return getattr(result, key, default)

    async def _emit_result_events(result: Any):
        yield f"data: {json.dumps({'token': '', 'done': False}, ensure_ascii=True)}\n\n"
        for chunk in str(_result_value(result, "response", "") or "").split():
            yield f"data: {json.dumps({'token': chunk + ' ', 'done': False}, ensure_ascii=True)}\n\n"
        yield (
            f"data: {json.dumps({'token': '', 'done': True, 'tools_called': _result_value(result, 'tools_called', []), 'steps': _result_value(result, 'steps', []), 'reasoning_used': bool(_result_value(result, 'reasoning_used', False)), 'used_ensemble': bool(_result_value(result, 'used_ensemble', False))}, ensure_ascii=True)}\n\n"
        )

    async def event_stream():
        if runtime.orchestrator is not None:
            try:
                stream = await runtime.orchestrator.handle(
                    payload.text, user_id, {}, importance=payload.importance, stream=True
                )
            except TypeError:
                result = await runtime.orchestrator.handle(
                    payload.text, user_id, {}, importance=payload.importance
                )
                async for event in _emit_result_events(result):
                    yield event
                return
        else:
            try:
                stream = await runtime.agent_loop.handle_message(
                    payload.text, importance=payload.importance, stream=True
                )
            except TypeError:
                result = await runtime.agent_loop.handle_message(
                    payload.text, importance=payload.importance
                )
                async for event in _emit_result_events(result):
                    yield event
                return
        yield f"data: {json.dumps({'token': '', 'done': False}, ensure_ascii=True)}\n\n"
        async for event in stream:
            yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"

    if "text/event-stream" not in accept:
        if runtime.orchestrator is not None:
            result = await runtime.orchestrator.handle(
                payload.text, user_id, {}, importance=payload.importance
            )
        else:
            result = await runtime.agent_loop.handle_message(
                payload.text, importance=payload.importance
            )
        return {
            "response": _result_value(result, "response", ""),
            "used_ensemble": _result_value(result, "used_ensemble", False),
            "tools_called": _result_value(result, "tools_called", []),
            "reasoning_used": _result_value(result, "reasoning_used", False),
            "steps": _result_value(result, "steps", []),
        }

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/a2a/agents")
async def a2a_agents(include_hidden: bool = False) -> list[dict[str, Any]]:
    registry = AgentRegistry()
    cards = registry.list_all()
    if not include_hidden:
        cards = [c for c in cards if getattr(c, "id", "") not in {"mobile", "nexus"}]
    return [_serialize(c) for c in cards]


@app.get("/a2a/agents/{agent_id}")
async def a2a_agent(agent_id: str) -> dict[str, Any]:
    registry = AgentRegistry()
    try:
        return _serialize(registry.get(agent_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc


@app.post("/a2a/agents/{agent_id}/tasks")
async def a2a_agent_task(
    agent_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    runtime = get_runtime()
    _require_token(request)
    dispatcher = (
        runtime.orchestrator.dispatcher
        if runtime.orchestrator is not None
        else A2ADispatcher(AgentRegistry())
    )
    task = {
        "task_id": payload.get("task_id") or secrets.token_hex(16),
        "from_agent": payload.get("from_agent", "director"),
        "to_agent": agent_id,
        "instruction": payload.get("instruction", ""),
        "context": payload.get("context", {}),
        "priority": int(payload.get("priority", 2)),
        "callback_url": payload.get("callback_url"),
    }
    from aura.core.multiagent.models import A2ATask

    result = await dispatcher.dispatch(A2ATask(**task))
    return _serialize(result)


@app.get("/mcp/tools")
async def mcp_tools() -> list[dict[str, Any]]:
    return list_mcp_tools()


@app.post("/mcp/tools/{agent_id}/{tool_name}")
async def mcp_call(
    agent_id: str, tool_name: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    _require_token(request)
    return await call_mcp_tool(agent_id, tool_name, payload.get("arguments", {}))


@app.get("/api/workflows")
async def api_workflows() -> list[dict[str, Any]]:
    return [_serialize(w) for w in director_tools.list_workflows(status_filter=None, limit=100)]


@app.post("/api/workflows/{workflow_id}/pause")
async def api_pause_workflow(workflow_id: str) -> Any:
    return _serialize(director_tools.pause_workflow(workflow_id))


@app.post("/api/workflows/{workflow_id}/resume")
async def api_resume_workflow(workflow_id: str) -> Any:
    result = director_tools.resume_workflow(workflow_id)
    if asyncio.iscoroutine(result):
        result = await result
    return _serialize(result)


@app.post("/api/workflows/{workflow_id}/approve/{step_id}")
async def api_approve_step(workflow_id: str, step_id: str) -> Any:
    return _serialize(
        director_tools.approve_step(workflow_id, step_id, True, "Approved via NEXUS UI")
    )


@app.delete("/api/workflows/{workflow_id}")
async def api_cancel_workflow(workflow_id: str) -> Any:
    return _serialize(director_tools.cancel_workflow(workflow_id))


@app.get("/api/memories")
async def api_memories(
    query: str = "", category: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    if query:
        results = recall_memory(query, top_k=limit, category_filter=category)
        return [
            {
                "id": r.record.id,
                "key": r.record.key,
                "category": r.record.category,
                "preview": r.record.value[:160],
                "timestamp": r.record.updated_at,
                "similarity_score": r.similarity_score,
            }
            for r in results
        ]
    return [_memory_summary(m) for m in list_memories(category=category, limit=limit)]


@app.get("/api/memories/count")
async def api_memories_count() -> dict[str, int]:
    return {"count": len(list_memories(limit=1_000_000))}


@app.delete("/api/memories/{memory_id}")
async def api_delete_memory(memory_id: str) -> Any:
    return _serialize(delete_memory(memory_id))


@app.get("/api/oracle/{report_id}")
async def api_oracle_report(report_id: str) -> Any:
    report = oracle_tools.get_reasoning_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return _serialize(report)


@app.post("/api/oracle/analyze")
async def api_oracle_analyze(payload: OracleAnalyzeRequest) -> Any:
    return _serialize(
        await oracle_tools.analyze_decision(payload.question, payload.context, payload.use_iris)
    )


@app.post("/api/oracle/whatif")
async def api_oracle_whatif(payload: OracleWhatIfRequest) -> Any:
    return _serialize(await oracle_tools.what_if_scenario(payload.change, payload.base_state))


@app.get("/api/audit-log")
async def api_audit_log(limit: int = 100) -> list[dict[str, Any]]:
    audit_path = get_runtime().config.paths.data_dir / "audit.log"
    if not audit_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


@app.post("/api/lyra/speak")
async def api_lyra_speak(payload: dict[str, Any] = Body(...)) -> Any:
    return _serialize(lyra_tools.speak(str(payload.get("text", ""))))


@app.post("/api/lyra/voice-mode")
async def api_voice_mode(payload: VoiceModeRequest) -> dict[str, Any]:
    runtime = get_runtime()
    if runtime.config.lyra is None:
        raise HTTPException(status_code=400, detail="lyra configuration is unavailable")
    runtime.config.lyra.voice_mode = payload.enabled
    return {"enabled": runtime.config.lyra.voice_mode}


@app.get("/api/stream/sources")
async def api_stream_sources() -> list[dict[str, Any]]:
    return [_serialize(s) for s in stream_tools.list_stream_sources()]


@app.get("/api/stream/items")
async def api_stream_items(limit: int = 20) -> list[dict[str, Any]]:
    return [_serialize(i) for i in stream_tools.get_unread_items(limit=limit)]


@app.post("/api/stream/fetch")
async def api_stream_fetch(source_id: str | None = None) -> list[dict[str, Any]]:
    return [_serialize(i) for i in await stream_tools.fetch_stream(source_id)]


@app.post("/api/stream/digest")
async def api_stream_digest(date: str | None = None) -> dict[str, Any]:
    return _serialize(stream_tools.generate_daily_digest(date))


@app.post("/api/stream/read/{item_id}")
async def api_stream_read(item_id: str) -> Any:
    return _serialize(stream_tools.mark_item_read(item_id))


@app.get("/api/phantom/tasks")
async def api_phantom_tasks() -> list[dict[str, Any]]:
    return [_serialize(t) for t in phantom_tools.list_workflows()]


@app.post("/api/phantom/tasks/{task_id}/toggle")
async def api_phantom_toggle_task(
    task_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    result = phantom_tools.enable_task(task_id) if enabled else phantom_tools.disable_task(task_id)
    task = next(
        (t for t in phantom_tools.list_workflows() if getattr(t, "id", "") == task_id), None
    )
    return {"success": bool(result), "task": _serialize(task) if task is not None else None}


@app.post("/api/aegis/screenshot")
async def api_aegis_screenshot(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    path = aegis_tools.take_screenshot(payload.get("region"), payload.get("save_path"))
    return {"path": path}


@app.post("/api/mosaic/synthesize")
async def api_mosaic_synthesize(payload: dict[str, Any] = Body(...)) -> Any:
    sources = [mosaic_tools.SourceInput(**s) for s in payload.get("sources", [])]
    result = await mosaic_tools.synthesize(
        str(payload.get("task", "")),
        sources,
        str(payload.get("output_format", "markdown")),
        payload.get("max_length"),
    )
    return _serialize(result)


@app.post("/api/mosaic/merge-code")
async def api_mosaic_merge_code(payload: dict[str, Any] = Body(...)) -> Any:
    sources = [mosaic_tools.SourceInput(**s) for s in payload.get("sources", [])]
    result = await mosaic_tools.merge_code(
        sources, str(payload.get("task", "")), str(payload.get("language", "python"))
    )
    return _serialize(result)


@app.post("/api/mosaic/diff")
async def api_mosaic_diff(payload: dict[str, Any] = Body(...)) -> Any:
    return _serialize(
        mosaic_tools.diff_sources(
            mosaic_tools.SourceInput(**payload["source_a"]),
            mosaic_tools.SourceInput(**payload["source_b"]),
        )
    )


@app.get("/api/mosaic/{mosaic_id}")
async def api_mosaic_cite(mosaic_id: str) -> dict[str, Any]:
    return {"citations": mosaic_tools.cite_sources(mosaic_id)}


@app.websocket("/ws/client/{user_id}")
async def websocket_client(websocket: WebSocket, user_id: str) -> None:
    token = (
        websocket.query_params.get("token")
        or websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    manager = _auth_manager()
    if manager is not None:
        if not token:
            await websocket.close(code=4401)
            return
        try:
            verified_user_id = manager.verify_token(token)
        except AuthError:
            await websocket.close(code=4401)
            return
        if verified_user_id != user_id:
            await websocket.close(code=4403)
            return
    await websocket.accept()
    _CLIENT_CONNECTIONS[user_id] = websocket
    await websocket.send_json(
        {
            "type": "hello",
            "platform": "linux",
            "capabilities": ["atlas", "aegis", "hermes", "lyra"],
            "aura_version": aura.__version__,
        }
    )
    try:
        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("action") != "tool_result":
                continue
            call_id = str(data.get("call_id", ""))
            if not call_id:
                continue
            entry = _CLIENT_TOOL_FUTURES.get(call_id)
            if entry is None:
                continue
            future_user_id, future = entry
            if future_user_id != user_id or future.done():
                continue
            error = data.get("error")
            future.set_result(
                {"result": data.get("result"), "error": str(error) if error else None}
            )
    except WebSocketDisconnect:
        return
    finally:
        _CLIENT_CONNECTIONS.pop(user_id, None)
        for call_id, (fuid, future) in list(_CLIENT_TOOL_FUTURES.items()):
            if fuid != user_id:
                continue
            if not future.done():
                future.set_exception(ConnectionError("local client disconnected"))
            _CLIENT_TOOL_FUTURES.pop(call_id, None)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    token = (
        websocket.query_params.get("token")
        or websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    manager = _auth_manager()
    if manager is not None:
        if not token:
            await websocket.close(code=4401)
            return
        try:
            manager.verify_token(token)
        except AuthError:
            await websocket.close(code=4401)
            return
    await websocket.accept()
    _CONNECTED_CLIENTS.add(websocket)
    await websocket.send_json(
        {
            "type": "state_snapshot",
            "data": build_state_snapshot(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
    finally:
        _CONNECTED_CLIENTS.discard(websocket)


async def start_server() -> None:
    runtime = get_runtime()
    ui = getattr(runtime.config, "ui", None)
    if ui is None or not ui.enabled:
        return
    config = uvicorn.Config(
        app, host=ui.host, port=ui.port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    await server.serve()


def start_server_task() -> asyncio.Task[None] | None:
    runtime = get_runtime()
    ui = getattr(runtime.config, "ui", None)
    if ui is None or not ui.enabled:
        return None
    loop = asyncio.get_running_loop()
    return loop.create_task(start_server())
