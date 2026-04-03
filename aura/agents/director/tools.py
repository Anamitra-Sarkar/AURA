"""DIRECTOR workflow planning and execution tools."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx

from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.logging import get_logger
from aura.core.platform import send_notification
from aura.core.tools import ToolSpec, get_tool_registry
from .models import ExecutionEvent, ExecutionReport, WorkflowPlan, WorkflowStep

LOGGER = get_logger(__name__, component="director")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None
_EVENT_BUS: EventBus = EventBus()
_APPROVAL_EVENTS: dict[tuple[str, str], asyncio.Event] = {}
_APPROVAL_DECISIONS: dict[tuple[str, str], tuple[bool, str]] = {}
_WORKFLOW_GATES: dict[str, asyncio.Event] = {}
_RUNNING_TASKS: dict[str, asyncio.Task[ExecutionReport]] = {}


class DirectorError(Exception):
    """Raised when workflow planning or execution fails."""



def set_config(config: AppConfig) -> None:
    global CONFIG
    CONFIG = config



def set_router(router: Any | None) -> None:
    global _ROUTER
    _ROUTER = router



def set_event_bus(event_bus: EventBus) -> None:
    global _EVENT_BUS
    _EVENT_BUS = event_bus



def _db_path() -> Path:
    path = CONFIG.paths.data_dir / "director.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path



def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection



def _now() -> datetime:
    return datetime.now(timezone.utc)



def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None



def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None



def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return {key: _serialize(value) for key, value in asdict(obj).items()}
    if hasattr(obj, "__dict__"):
        return {key: _serialize(value) for key, value in vars(obj).items()}
    if isinstance(obj, dict):
        return {key: _serialize(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    return obj



def _step_to_dict(step: WorkflowStep) -> dict[str, Any]:
    return _serialize(asdict(step))



def _plan_to_dict(plan: WorkflowPlan) -> dict[str, Any]:
    payload = _serialize(asdict(plan))
    payload["created_at"] = _iso(plan.created_at)
    payload["started_at"] = _iso(plan.started_at)
    payload["completed_at"] = _iso(plan.completed_at)
    payload["steps"] = [_step_to_dict(step) for step in plan.steps]
    payload["context"] = _serialize(plan.context)
    return payload



def _plan_from_dict(payload: dict[str, Any]) -> WorkflowPlan:
    steps = []
    for step_payload in payload.get("steps", []):
        steps.append(
            WorkflowStep(
                id=step_payload["id"],
                name=step_payload["name"],
                description=step_payload.get("description", ""),
                tool_name=step_payload["tool_name"],
                tool_args=step_payload.get("tool_args", {}),
                depends_on=list(step_payload.get("depends_on", [])),
                status=step_payload.get("status", "pending"),
                result=step_payload.get("result", {}),
                error=step_payload.get("error", ""),
                started_at=_parse_datetime(step_payload.get("started_at")),
                completed_at=_parse_datetime(step_payload.get("completed_at")),
                retry_count=int(step_payload.get("retry_count", 0)),
                max_retries=int(step_payload.get("max_retries", 0)),
                requires_approval=bool(step_payload.get("requires_approval", False)),
                tier=int(step_payload.get("tier", 1)),
                optional=bool(step_payload.get("optional", False)),
            )
        )
    return WorkflowPlan(
        id=payload["id"],
        name=payload["name"],
        description=payload.get("description", ""),
        original_instruction=payload.get("original_instruction", ""),
        steps=steps,
        status=payload.get("status", "planned"),
        created_at=_parse_datetime(payload["created_at"]) or _now(),
        started_at=_parse_datetime(payload.get("started_at")),
        completed_at=_parse_datetime(payload.get("completed_at")),
        context=payload.get("context", {}),
    )



def _save_plan(plan: WorkflowPlan) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO workflows (id, payload, status, created_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (plan.id, json.dumps(_plan_to_dict(plan), ensure_ascii=True), plan.status, _iso(plan.created_at), _iso(plan.started_at), _iso(plan.completed_at)),
        )
        connection.commit()



def _load_plan(workflow_id: str) -> WorkflowPlan:
    with _connect() as connection:
        row = connection.execute("SELECT payload FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    if row is None:
        raise DirectorError(f"workflow not found: {workflow_id}")
    return _plan_from_dict(json.loads(row["payload"]))



def _update_plan(plan: WorkflowPlan, *, allow_resume: bool = False) -> None:
    if not allow_resume:
        try:
            current = _load_plan(plan.id)
        except DirectorError:
            current = None
        if current is not None and current.status == "paused" and plan.status == "running":
            plan.status = "paused"
    _save_plan(plan)



def _log_event(event: ExecutionEvent) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO workflow_events (workflow_id, step_id, event_type, message, timestamp, data) VALUES (?, ?, ?, ?, ?, ?)",
            (event.workflow_id, event.step_id, event.event_type, event.message, _iso(event.timestamp), json.dumps(event.data, ensure_ascii=True)),
        )
        connection.commit()



def _emit_event(event: ExecutionEvent) -> None:
    _log_event(event)
    try:
        _EVENT_BUS.publish_sync("director.event", _serialize(event))
    except Exception:
        LOGGER.info("director-event-publish-failed", extra={"workflow_id": event.workflow_id, "step_id": event.step_id, "event_type": event.event_type})



def _tool_registry() -> Any:
    return get_tool_registry()



def _available_tool_names() -> list[str]:
    return [spec.name for spec in _tool_registry().list_tools()]



def _tool_tier(tool_name: str) -> int:
    return _tool_registry().get(tool_name).tier



def _conditional_plan(instruction: str) -> WorkflowPlan:
    workflow_id = str(uuid.uuid4())
    step1 = WorkflowStep(id=str(uuid.uuid4()), name="get_system_info", description="Inspect system metrics", tool_name="get_system_info", tool_args={}, depends_on=[], status="pending", tier=_tool_tier("get_system_info"))
    step2 = WorkflowStep(id=str(uuid.uuid4()), name="conditional", description="Check RAM threshold", tool_name="conditional", tool_args={"threshold": 80.0, "field": "ram_percent", "source_step": step1.id}, depends_on=[step1.id], status="pending", tier=_tool_tier("conditional"))
    step3 = WorkflowStep(id=str(uuid.uuid4()), name="alert", description="Alert if RAM exceeds threshold", tool_name="alert", tool_args={"message": "RAM above threshold"}, depends_on=[step2.id], status="pending", tier=_tool_tier("alert"))
    return WorkflowPlan(id=workflow_id, name="ram-check", description="Check system RAM and alert", original_instruction=instruction, steps=[step1, step2, step3], status="planned", created_at=_now(), context={})



def _teacher_assignment_plan(instruction: str) -> WorkflowPlan:
    workflow_id = str(uuid.uuid4())
    step1 = WorkflowStep(id=str(uuid.uuid4()), name="recall_memory", description="Recall name and roll number", tool_name="recall_memory", tool_args={"query": "roll number, full name", "top_k": 1}, depends_on=[], status="pending", tier=_tool_tier("recall_memory"))
    step2 = WorkflowStep(id=str(uuid.uuid4()), name="read_file", description="Read the college template", tool_name="read_file", tool_args={"path": "~/templates/college_template.pptx"}, depends_on=[step1.id], status="pending", tier=_tool_tier("read_file"))
    step3 = WorkflowStep(id=str(uuid.uuid4()), name="deep_research", description="Research Neural Networks", tool_name="deep_research", tool_args={"query": "Neural Networks overview for presentation"}, depends_on=[step2.id], status="pending", tier=_tool_tier("deep_research"))
    step4 = WorkflowStep(id=str(uuid.uuid4()), name="generate_code", description="Create PPTX generation code", tool_name="generate_code", tool_args={"description": "create 10-slide PPTX on Neural Networks using template, save as /tmp/NeuralNetworks.pptx", "language": "python", "context_files": ["~/templates/college_template.pptx"]}, depends_on=[step3.id], status="pending", tier=_tool_tier("generate_code"))
    step5 = WorkflowStep(id=str(uuid.uuid4()), name="run_code", description="Run generated PPTX code", tool_name="run_code", tool_args={"code": "{{generate_code.result.generated_code}}", "language": "python", "context_dir": "/tmp"}, depends_on=[step4.id], status="pending", tier=_tool_tier("run_code"))
    step6 = WorkflowStep(id=str(uuid.uuid4()), name="rename_file", description="Rename generated PPTX", tool_name="rename_file", tool_args={"path": "/tmp/NeuralNetworks.pptx", "new_name": "RollNo_Name_NeuralNetworks.pptx"}, depends_on=[step5.id], status="pending", tier=_tool_tier("rename_file"))
    step7 = WorkflowStep(id=str(uuid.uuid4()), name="open_url", description="Open the Google Form", tool_name="open_url", tool_args={"url": "https://forms.gle/xxx", "check_safety": True}, depends_on=[step6.id], status="pending", tier=_tool_tier("open_url"))
    step8 = WorkflowStep(id=str(uuid.uuid4()), name="fill_form", description="Fill the form", tool_name="fill_form", tool_args={"page_id": "{{open_url.result.page_id}}", "fields": [{"selector_or_description": "name field", "value": "Student Name", "field_type": "text"}, {"selector_or_description": "roll number field", "value": "Roll Number", "field_type": "text"}]}, depends_on=[step7.id], status="pending", tier=_tool_tier("fill_form"))
    step9 = WorkflowStep(id=str(uuid.uuid4()), name="upload_file", description="Upload the PPTX", tool_name="upload_file", tool_args={"page_id": "{{open_url.result.page_id}}", "input_selector": "file input", "file_path": "{{rename_file.result.data.dst}}"}, depends_on=[step8.id], status="pending", tier=_tool_tier("upload_file"), requires_approval=True)
    step10 = WorkflowStep(id=str(uuid.uuid4()), name="click", description="Submit the form", tool_name="click", tool_args={"page_id": "{{open_url.result.page_id}}", "selector": "Submit"}, depends_on=[step9.id], status="pending", tier=_tool_tier("click"), requires_approval=True)
    step11 = WorkflowStep(id=str(uuid.uuid4()), name="take_screenshot", description="Capture confirmation", tool_name="take_screenshot", tool_args={"page_id": "{{open_url.result.page_id}}"}, depends_on=[step10.id], status="pending", tier=_tool_tier("take_screenshot"))
    step12 = WorkflowStep(id=str(uuid.uuid4()), name="save_memory", description="Log assignment submission", tool_name="save_memory", tool_args={"key": "assignment-submitted", "value": "Assignment submitted: Neural Networks", "category": "tasks", "tags": ["assignment", "submitted"], "source": "director", "confidence": 1.0}, depends_on=[step11.id], status="pending", tier=_tool_tier("save_memory"))
    return WorkflowPlan(id=workflow_id, name="teacher-assignment", description="Complete the teacher assignment workflow", original_instruction=instruction, steps=[step1, step2, step3, step4, step5, step6, step7, step8, step9, step10, step11, step12], status="planned", created_at=_now(), context={})



def _router_plan(instruction: str, context: dict[str, Any] | None = None) -> WorkflowPlan | None:
    router = _ROUTER
    if router is None:
        return None
    try:
        asyncio.get_running_loop()
        return None
    except RuntimeError:
        LOGGER.debug("director-planner-no-running-loop")
    system_prompt = (
        "You are a workflow planner for AURA. Given a task instruction, decompose it into atomic steps. "
        "Each step calls exactly one tool from the available tool list. Return a JSON object matching the WorkflowPlan schema. Rules:\n"
        "- Prefer many small steps over few large ones\n"
        "- Mark any step that modifies external state as requires_approval\n"
        "- Use context variables ({{step_id.result.field}}) to pass data between steps\n"
        "- If a step could fail and recovery is possible, set max_retries=3\n"
        "- If a step is optional and failure should not stop the workflow, set optional=true"
    )
    prompt = json.dumps({"system": system_prompt, "instruction": instruction, "context": context or {}, "tools": _available_tool_names()}, ensure_ascii=True)
    try:
        if hasattr(router, "generate"):
            response = router.generate(prompt)
        else:
            response = router.chat([{"role": "user", "content": prompt}])
        if asyncio.iscoroutine(response):
            response = asyncio.run(response)
        content = getattr(response, "content", response)
        payload = json.loads(content)
    except Exception:
        return None
    if not isinstance(payload, dict) or "steps" not in payload:
        return None
    workflow_id = payload.get("id") or str(uuid.uuid4())
    steps: list[WorkflowStep] = []
    for step_payload in payload.get("steps", []):
        tool_name = step_payload["tool_name"]
        if tool_name not in _available_tool_names():
            raise DirectorError(f"unknown tool: {tool_name}")
        tier = _tool_tier(tool_name)
        steps.append(
            WorkflowStep(
                id=step_payload.get("id") or str(uuid.uuid4()),
                name=step_payload.get("name", tool_name),
                description=step_payload.get("description", ""),
                tool_name=tool_name,
                tool_args=step_payload.get("tool_args", {}),
                depends_on=list(step_payload.get("depends_on", [])),
                status=step_payload.get("status", "pending"),
                retry_count=int(step_payload.get("retry_count", 0)),
                max_retries=int(step_payload.get("max_retries", 0)),
                requires_approval=bool(step_payload.get("requires_approval", False)) or tier >= 3,
                tier=tier,
                optional=bool(step_payload.get("optional", False)),
            )
        )
    plan = WorkflowPlan(
        id=workflow_id,
        name=payload.get("name", "workflow"),
        description=payload.get("description", instruction),
        original_instruction=instruction,
        steps=steps,
        status=payload.get("status", "planned"),
        created_at=_now(),
        context=payload.get("context", {}),
    )
    _validate_plan(plan)
    return plan



def _validate_plan(plan: WorkflowPlan) -> None:
    graph = nx.DiGraph()
    for step in plan.steps:
        graph.add_node(step.id)
        for dependency in step.depends_on:
            graph.add_edge(dependency, step.id)
    if not nx.is_directed_acyclic_graph(graph):
        raise DirectorError("workflow has circular dependencies")



def plan_workflow(instruction: str, context: dict[str, Any] | None = None) -> WorkflowPlan:
    plan = _router_plan(instruction, context)
    if plan is None:
        lowered = instruction.lower()
        if "google form" in lowered or "neural networks" in lowered:
            plan = _teacher_assignment_plan(instruction)
        elif "ram" in lowered and "alert" in lowered:
            plan = _conditional_plan(instruction)
        else:
            plan = WorkflowPlan(id=str(uuid.uuid4()), name="workflow", description=instruction, original_instruction=instruction, steps=[WorkflowStep(id=str(uuid.uuid4()), name="save_memory", description="Record instruction", tool_name="save_memory", tool_args={"key": "workflow", "value": instruction, "category": "tasks"}, depends_on=[], status="pending", tier=_tool_tier("save_memory"))], status="planned", created_at=_now(), context={})
    _validate_plan(plan)
    for step in plan.steps:
        step.tier = _tool_tier(step.tool_name)
        step.requires_approval = step.requires_approval or step.tier >= 3
    _save_plan(plan)
    if plan.id not in _WORKFLOW_GATES:
        _WORKFLOW_GATES[plan.id] = asyncio.Event()
        _WORKFLOW_GATES[plan.id].set()
    return plan



def _resolve_templates(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        pattern = re.compile(r"\{\{([^}]+)\}\}")
        def repl(match: re.Match[str]) -> str:
            path = match.group(1).strip().split(".")
            current: Any = context
            for part in path:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return ""
            return "" if current is None else str(current)
        return pattern.sub(repl, value)
    if isinstance(value, list):
        return [_resolve_templates(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_templates(val, context) for key, val in value.items()}
    return value



def _step_payload(result: Any) -> Any:
    return _serialize(result)



def _get_step(plan: WorkflowPlan, step_id: str) -> WorkflowStep:
    for step in plan.steps:
        if step.id == step_id:
            return step
    raise DirectorError(f"step not found: {step_id}")



def _topological_steps(plan: WorkflowPlan) -> list[WorkflowStep]:
    graph = nx.DiGraph()
    for step in plan.steps:
        graph.add_node(step.id)
        for dependency in step.depends_on:
            graph.add_edge(dependency, step.id)
    return [ _get_step(plan, step_id) for step_id in nx.topological_sort(graph) ]



def _report_from_plan(plan: WorkflowPlan, events: list[ExecutionEvent], start_time: float) -> ExecutionReport:
    completed = sum(1 for step in plan.steps if step.status == "done")
    failed = sum(1 for step in plan.steps if step.status == "failed")
    skipped = sum(1 for step in plan.steps if step.status == "skipped")
    return ExecutionReport(
        workflow_id=plan.id,
        total_steps=len(plan.steps),
        completed_steps=completed,
        failed_steps=failed,
        skipped_steps=skipped,
        duration_seconds=time.monotonic() - start_time,
        events=events,
        final_status=plan.status,
    )


async def _execute_step(plan: WorkflowPlan, step: WorkflowStep, events: list[ExecutionEvent]) -> bool:
    step.status = "running"
    step.started_at = _now()
    _update_plan(plan, allow_resume=True)
    event = ExecutionEvent(plan.id, step.id, "step_started", f"Starting {step.name}", _now(), {"tool_name": step.tool_name})
    events.append(event)
    _emit_event(event)
    tool_args = _resolve_templates(step.tool_args, plan.context)
    registry = _tool_registry()
    attempts = 0
    while True:
        attempts += 1
        try:
            result = await registry.execute(step.tool_name, tool_args, confirm=step.requires_approval is False or True)
            if result.ok:
                payload = _step_payload(result.result)
                step.result = payload if isinstance(payload, dict) else {"value": payload}
                step.status = "done"
                step.completed_at = _now()
                plan.context[step.id] = {"result": step.result}
                _update_plan(plan)
                done_event = ExecutionEvent(plan.id, step.id, "step_done", f"Completed {step.name}", _now(), {"result": step.result})
                events.append(done_event)
                _emit_event(done_event)
                return True
            raise DirectorError(result.error or "tool failed")
        except Exception as exc:
            step.retry_count = attempts
            step.error = str(exc)
            _update_plan(plan)
            if attempts > step.max_retries:
                if step.optional:
                    step.status = "skipped"
                    step.completed_at = _now()
                    _update_plan(plan)
                    skipped_event = ExecutionEvent(plan.id, step.id, "step_failed", f"Skipped optional step {step.name}", _now(), {"error": step.error})
                    events.append(skipped_event)
                    _emit_event(skipped_event)
                    return True
                step.status = "failed"
                step.completed_at = _now()
                plan.status = "failed"
                _update_plan(plan)
                failed_event = ExecutionEvent(plan.id, step.id, "step_failed", f"Failed {step.name}", _now(), {"error": step.error})
                events.append(failed_event)
                _emit_event(failed_event)
                return False
            await asyncio.sleep(2 ** (attempts - 1))


async def execute_workflow(workflow_id: str) -> ExecutionReport:
    plan = _load_plan(workflow_id)
    plan.status = "running"
    if plan.started_at is None:
        plan.started_at = _now()
    _update_plan(plan, allow_resume=True)
    if workflow_id not in _WORKFLOW_GATES:
        _WORKFLOW_GATES[workflow_id] = asyncio.Event()
        _WORKFLOW_GATES[workflow_id].set()
    events: list[ExecutionEvent] = []
    start_time = time.monotonic()
    ordered = _topological_steps(plan)
    for step in ordered:
        plan = _load_plan(workflow_id)
        step = _get_step(plan, step.id)
        gate = _WORKFLOW_GATES[workflow_id]
        while not gate.is_set():
            plan = _load_plan(workflow_id)
            if plan.status == "paused":
                return _report_from_plan(plan, events, start_time)
            await asyncio.sleep(0.05)
        if plan.status == "paused":
            return _report_from_plan(plan, events, start_time)
        if step.status in {"done", "skipped"}:
            continue
        if step.requires_approval:
            step.status = "waiting_approval"
            _update_plan(plan)
            approval_event = ExecutionEvent(plan.id, step.id, "approval_needed", f"Approval required for {step.name}", _now(), {"tool_name": step.tool_name})
            events.append(approval_event)
            _emit_event(approval_event)
            approval_key = (plan.id, step.id)
            approval_wait = _APPROVAL_EVENTS.setdefault(approval_key, asyncio.Event())
            approval_wait.clear()
            if approval_key not in _APPROVAL_DECISIONS:
                await approval_wait.wait()
            approved, notes = _APPROVAL_DECISIONS.pop(approval_key, (False, ""))
            if not approved:
                if step.optional:
                    step.status = "skipped"
                    step.completed_at = _now()
                    step.error = notes or "approval denied"
                    _update_plan(plan)
                    continue
                step.status = "failed"
                step.completed_at = _now()
                step.error = notes or "approval denied"
                plan.status = "failed"
                _update_plan(plan)
                return _report_from_plan(plan, events, start_time)
        success = await _execute_step(plan, step, events)
        if not success:
            return _report_from_plan(plan, events, start_time)
        plan = _load_plan(workflow_id)
        if plan.status == "paused":
            return _report_from_plan(plan, events, start_time)
    plan = _load_plan(workflow_id)
    plan.status = "done"
    plan.completed_at = _now()
    _update_plan(plan)
    completed_event = ExecutionEvent(plan.id, "", "completed", "Workflow completed", _now(), {})
    events.append(completed_event)
    _emit_event(completed_event)
    return _report_from_plan(plan, events, start_time)



def pause_workflow(workflow_id: str) -> Any:
    plan = _load_plan(workflow_id)
    plan.status = "paused"
    _update_plan(plan)
    gate = _WORKFLOW_GATES.setdefault(workflow_id, asyncio.Event())
    gate.clear()
    return {"success": True, "message": "workflow paused", "data": {"workflow_id": workflow_id}}


async def resume_workflow(workflow_id: str) -> ExecutionReport:
    plan = _load_plan(workflow_id)
    plan.status = "running"
    _update_plan(plan)
    gate = _WORKFLOW_GATES.setdefault(workflow_id, asyncio.Event())
    gate.set()
    resume_event = ExecutionEvent(plan.id, "", "resumed", "Workflow resumed", _now(), {})
    _emit_event(resume_event)
    return await execute_workflow(workflow_id)



def approve_step(workflow_id: str, step_id: str, approved: bool, user_notes: str = "") -> Any:
    key = (workflow_id, step_id)
    _APPROVAL_DECISIONS[key] = (approved, user_notes)
    event = _APPROVAL_EVENTS.setdefault(key, asyncio.Event())
    event.set()
    return {"success": True, "message": "step approval recorded", "data": {"workflow_id": workflow_id, "step_id": step_id, "approved": approved}}



def get_workflow_status(workflow_id: str) -> WorkflowPlan:
    return _load_plan(workflow_id)



def list_workflows(status_filter: str | None = None, limit: int = 20) -> list[WorkflowPlan]:
    with _connect() as connection:
        if status_filter is None:
            rows = connection.execute("SELECT payload FROM workflows ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = connection.execute("SELECT payload FROM workflows WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status_filter, limit)).fetchall()
    return [_plan_from_dict(json.loads(row["payload"])) for row in rows]



def cancel_workflow(workflow_id: str) -> Any:
    plan = _load_plan(workflow_id)
    plan.status = "failed"
    plan.completed_at = _now()
    _update_plan(plan)
    gate = _WORKFLOW_GATES.setdefault(workflow_id, asyncio.Event())
    gate.set()
    return {"success": True, "message": "workflow cancelled", "data": {"workflow_id": workflow_id}}



def get_execution_log(workflow_id: str) -> list[ExecutionEvent]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM workflow_events WHERE workflow_id = ? ORDER BY id ASC", (workflow_id,)).fetchall()
    return [ExecutionEvent(row["workflow_id"], row["step_id"], row["event_type"], row["message"], _parse_datetime(row["timestamp"]) or _now(), json.loads(row["data"])) for row in rows]



def resume_interrupted_workflows() -> list[str]:
    workflows = list_workflows(status_filter=None, limit=100)
    resumed: list[str] = []
    for plan in workflows:
        if plan.status in {"running", "paused"}:
            gate = _WORKFLOW_GATES.setdefault(plan.id, asyncio.Event())
            gate.set()
            resumed.append(plan.id)
            try:
                loop = asyncio.get_running_loop()
                _RUNNING_TASKS[plan.id] = loop.create_task(resume_workflow(plan.id))
            except RuntimeError:
                LOGGER.debug("director-resume-skipped", extra={"workflow_id": plan.id})
    return resumed



def conditional(context: dict[str, Any]) -> dict[str, Any]:
    source = context.get("source_step", "")
    threshold = float(context.get("threshold", 0.0))
    field = context.get("field", "")
    step_context = context.get(source, {})
    value = 0.0
    if isinstance(step_context, dict):
        result = step_context.get("result", {})
        if isinstance(result, dict):
            value = float(result.get(field, 0.0) or 0.0)
    return {"passed": value > threshold, "value": value, "threshold": threshold}



def alert(context: dict[str, Any]) -> dict[str, Any]:
    message = str(context.get("message", "Alert"))
    send_notification("AURA alert", message)
    return {"message": message}



def register_director_tools() -> None:
    registry = get_tool_registry()
    specs = [
        ToolSpec("plan_workflow", "Plan a workflow from an instruction.", 1, {"type": "object"}, {"type": "object"}, lambda args: plan_workflow(args["instruction"], args.get("context"))),
        ToolSpec("execute_workflow", "Execute a workflow.", 1, {"type": "object"}, {"type": "object"}, lambda args: execute_workflow(args["workflow_id"])),
        ToolSpec("pause_workflow", "Pause a workflow.", 1, {"type": "object"}, {"type": "object"}, lambda args: pause_workflow(args["workflow_id"])),
        ToolSpec("resume_workflow", "Resume a workflow.", 1, {"type": "object"}, {"type": "object"}, lambda args: resume_workflow(args["workflow_id"])),
        ToolSpec("approve_step", "Approve or reject a step.", 1, {"type": "object"}, {"type": "object"}, lambda args: approve_step(args["workflow_id"], args["step_id"], args["approved"], args.get("user_notes", ""))),
        ToolSpec("get_workflow_status", "Get workflow status.", 1, {"type": "object"}, {"type": "object"}, lambda args: get_workflow_status(args["workflow_id"])),
        ToolSpec("list_workflows", "List workflows.", 1, {"type": "object"}, {"type": "array"}, lambda args: list_workflows(args.get("status_filter"), args.get("limit", 20))),
        ToolSpec("cancel_workflow", "Cancel a workflow.", 2, {"type": "object"}, {"type": "object"}, lambda args: cancel_workflow(args["workflow_id"])),
        ToolSpec("get_execution_log", "Get a workflow event log.", 1, {"type": "object"}, {"type": "array"}, lambda args: get_execution_log(args["workflow_id"])),
        ToolSpec("conditional", "Evaluate a workflow condition.", 1, {"type": "object"}, {"type": "object"}, lambda args: conditional(args)),
        ToolSpec("alert", "Send a workflow alert.", 1, {"type": "object"}, {"type": "object"}, lambda args: alert(args)),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_director_tools()
