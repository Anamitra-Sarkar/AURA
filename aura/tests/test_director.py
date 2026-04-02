from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import aura.agents.director.tools as director
from aura.agents.atlas.models import FileContent, OperationResult as AtlasOperationResult
from aura.agents.aegis.models import SystemSnapshot, GPUInfo
from aura.agents.logos.models import CodePatch, RunResult
from aura.browser.hermes.models import PageHandle, OperationResult as HermesOperationResult
from aura.core.tools import ToolSpec, ToolCallResult
from aura.memory.mneme.models import MemoryRecord, RecallResult
from aura.agents.director.models import WorkflowPlan, WorkflowStep


class FakeRegistry:
    def __init__(self) -> None:
        self.specs: dict[str, ToolSpec] = {}
        self.calls: list[str] = []
        self.failures: dict[str, int] = {}

    def add(self, name: str, tier: int, handler):
        self.specs[name] = ToolSpec(name=name, description=name, tier=tier, arguments_schema={"type": "object"}, return_schema={"type": "object"}, handler=handler)

    def list_tools(self):
        return list(self.specs.values())

    def get(self, name: str):
        return self.specs[name]

    async def execute(self, name: str, arguments: dict[str, object] | None = None, *, confirm: bool = False):
        self.calls.append(name)
        spec = self.get(name)
        if spec.tier >= 3 and not confirm:
            return ToolCallResult(ok=False, tool=name, tier=spec.tier, error="tier-3-confirmation-required")
        handler = spec.handler
        outcome = handler(arguments or {})
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
        return ToolCallResult(ok=True, tool=name, tier=spec.tier, result=outcome)


@pytest.fixture()
def director_registry(monkeypatch, tmp_path):
    registry = FakeRegistry()

    async def slow_system_info(args):
        await asyncio.sleep(0.05)
        return SystemSnapshot(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=92.0,
            cpu_count=8,
            ram_total_gb=16.0,
            ram_used_gb=14.0,
            ram_percent=87.5,
            disk_total_gb=100.0,
            disk_used_gb=50.0,
            disk_percent=50.0,
            gpu_info=[GPUInfo(name="GPU", memory_total_mb=1024.0, memory_used_mb=100.0, utilization_percent=10.0)],
            uptime_seconds=1,
            platform="linux",
            python_version="3.12",
        )

    registry.add("get_system_info", 1, slow_system_info)
    registry.add("conditional", 1, lambda args: {"passed": True, "value": 90.0, "threshold": 80.0})
    registry.add("alert", 1, lambda args: {"message": args.get("message", "Alert")})
    registry.add("recall_memory", 1, lambda args: [RecallResult(record=MemoryRecord(id="1", key="user", value="Student", category="personal", tags=[], embedding=[1.0], source="manual", confidence=1.0, created_at="2025-01-01T00:00:00+00:00", updated_at="2025-01-01T00:00:00+00:00", access_count=0, last_accessed="2025-01-01T00:00:00+00:00"), similarity_score=0.9, rank=1)])
    registry.add("read_file", 1, lambda args: FileContent(path=args["path"], content="template", encoding="utf-8", size_bytes=10, modified_date="2025-01-01T00:00:00+00:00", file_type="pptx"))
    registry.add("deep_research", 1, lambda args: {"answer": "research"})
    registry.add("generate_code", 1, lambda args: CodePatch(generated_code="print('pptx')", suggested_path="/tmp/NeuralNetworks.py", explanation="ok", language="python"))
    registry.add("run_code", 1, lambda args: RunResult(stdout="ok", stderr="", exit_code=0, execution_time_ms=1, language="python"))
    registry.add("rename_file", 2, lambda args: AtlasOperationResult(success=True, message="renamed", data={"src": args["path"], "dst": args["new_name"]}))
    registry.add("open_url", 1, lambda args: PageHandle(page_id="page-1", url=args["url"], title="Form", status_code=200))
    registry.add("fill_form", 1, lambda args: HermesOperationResult(success=True, message="filled", data={"page_id": args["page_id"]}))
    registry.add("upload_file", 2, lambda args: HermesOperationResult(success=True, message="uploaded", data={"page_id": args["page_id"], "path": args["file_path"]}))
    registry.add("click", 3, lambda args: HermesOperationResult(success=True, message="clicked", data={"page_id": args["page_id"]}))
    registry.add("take_screenshot", 1, lambda args: "/tmp/confirm.png")
    registry.add("save_memory", 1, lambda args: MemoryRecord(id="2", key=args["key"], value=args["value"], category=args["category"], tags=args.get("tags", []), embedding=[1.0], source=args.get("source", "manual"), confidence=float(args.get("confidence", 1.0)), created_at="2025-01-01T00:00:00+00:00", updated_at="2025-01-01T00:00:00+00:00", access_count=0, last_accessed="2025-01-01T00:00:00+00:00"))
    registry.add("generate_daily_briefing", 1, lambda args: {"summary": "brief"})
    monkeypatch.setattr(director, "get_tool_registry", lambda: registry)
    return registry



def test_plan_workflow_teacher_assignment_structure(director_registry):
    instruction = (
        "Professor gave topic 'Neural Networks' and a Google Form link https://forms.gle/xxx. "
        "Create a PPTX using the template at ~/templates/college_template.pptx, 10 slides, rename it to "
        "RollNo_Name_NeuralNetworks.pptx, open the form, fill my details, upload the file, and submit."
    )
    plan = director.plan_workflow(instruction)
    names = [step.name for step in plan.steps]
    assert len(plan.steps) == 12
    assert names == [
        "recall_memory",
        "read_file",
        "deep_research",
        "generate_code",
        "run_code",
        "rename_file",
        "open_url",
        "fill_form",
        "upload_file",
        "click",
        "take_screenshot",
        "save_memory",
    ]
    assert plan.steps[8].requires_approval is True
    assert plan.steps[9].requires_approval is True
    assert plan.steps[9].tier == 3
    assert director.get_workflow_status(plan.id).id == plan.id


@pytest.mark.asyncio
async def test_teacher_assignment_dry_run_and_approvals(director_registry):
    instruction = (
        "Professor gave topic 'Neural Networks' and a Google Form link https://forms.gle/xxx. "
        "Create a PPTX using the template at ~/templates/college_template.pptx, 10 slides, rename it to "
        "RollNo_Name_NeuralNetworks.pptx, open the form, fill my details, upload the file, and submit."
    )
    plan = director.plan_workflow(instruction)
    task = asyncio.create_task(director.execute_workflow(plan.id))
    deadline = asyncio.get_event_loop().time() + 2
    while True:
        current = director.get_workflow_status(plan.id)
        if current.steps[8].status == "waiting_approval":
            break
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("workflow did not reach approval step")
        await asyncio.sleep(0.01)
    director.approve_step(plan.id, current.steps[8].id, True, "ok")
    while True:
        current = director.get_workflow_status(plan.id)
        if current.steps[9].status == "waiting_approval":
            break
        await asyncio.sleep(0.01)
    director.approve_step(plan.id, current.steps[9].id, True, "ok")
    report = await task
    assert report.final_status == "done"
    assert [call for call in director_registry.calls[:12]] == [
        "recall_memory",
        "read_file",
        "deep_research",
        "generate_code",
        "run_code",
        "rename_file",
        "open_url",
        "fill_form",
        "upload_file",
        "click",
        "take_screenshot",
        "save_memory",
    ]


@pytest.mark.asyncio
async def test_pause_resume_and_retry(director_registry, monkeypatch):
    plan = director.plan_workflow("Check if RAM > 80% and alert")
    task = asyncio.create_task(director.execute_workflow(plan.id))
    await asyncio.sleep(0.01)
    director.pause_workflow(plan.id)
    paused = await task
    assert paused.final_status == "paused"
    assert director.get_workflow_status(plan.id).status == "paused"
    resumed = await director.resume_workflow(plan.id)
    assert resumed.final_status == "done"

    retry_plan = WorkflowPlan(
        id="retry-workflow",
        name="retry-workflow",
        description="retry",
        original_instruction="retry",
        steps=[WorkflowStep(id="step-1", name="alert", description="retry alert", tool_name="alert", tool_args={"message": "retry"}, depends_on=[], status="pending", max_retries=3, tier=1)],
        status="planned",
        created_at=datetime.now(timezone.utc),
        context={},
    )
    director._save_plan(retry_plan)
    attempts = {"count": 0}

    async def flaky_execute(name, arguments=None, *, confirm=False):
        attempts["count"] += 1
        if attempts["count"] < 4:
            return ToolCallResult(ok=False, tool=name, tier=1, error="boom")
        return ToolCallResult(ok=True, tool=name, tier=1, result={"message": "ok"})

    class RetryRegistry:
        def get(self, name):
            return retry_registry.get(name)

        def list_tools(self):
            return retry_registry.list_tools()

        async def execute(self, name, arguments=None, *, confirm=False):
            return await flaky_execute(name, arguments, confirm=confirm)

    retry_registry = FakeRegistry()
    retry_registry.add("alert", 1, lambda args: {"message": args["message"]})
    monkeypatch.setattr(director, "get_tool_registry", lambda: RetryRegistry())
    async def no_sleep(*_args, **_kwargs):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    retry_report = await director.execute_workflow("retry-workflow")
    assert retry_report.final_status == "done"
    assert attempts["count"] == 4
