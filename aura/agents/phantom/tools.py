"""PHANTOM background automation tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.logging import get_logger
from aura.core.platform import send_notification
from aura.core.tools import ToolSpec, get_tool_registry
from aura.agents.echo import tools as echo_tools
from aura.memory import list_memories, save_memory, consolidate_memory
from .models import Briefing, PhantomTask, WatchTarget

LOGGER = get_logger(__name__, component="phantom")
CONFIG: AppConfig = load_config()
_EVENT_BUS: EventBus = EventBus()
_PAUSED = False
_PAUSE_UNTIL: datetime | None = None
_DEFAULT_TASKS_LOADED = False
_REGISTERED_TASK_HANDLERS: dict[str, Callable[[], Any]] = {}
_RUNNING_TASKS: set[str] = set()


class PhantomError(Exception):
    """Raised when PHANTOM cannot complete an action."""



def set_config(config: AppConfig) -> None:
    global CONFIG
    CONFIG = config



def set_event_bus(event_bus: EventBus) -> None:
    global _EVENT_BUS
    _EVENT_BUS = event_bus



def _db_path() -> Path:
    path = CONFIG.paths.data_dir / "phantom.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path



def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            schedule TEXT NOT NULL,
            last_run TEXT,
            next_run TEXT,
            enabled INTEGER NOT NULL,
            handler_function TEXT NOT NULL,
            config TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            target TEXT NOT NULL,
            check_interval_minutes INTEGER NOT NULL,
            last_checked TEXT,
            last_hash TEXT NOT NULL,
            on_change_action TEXT NOT NULL,
            on_change_config TEXT NOT NULL,
            enabled INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection



def _now() -> datetime:
    return datetime.now(timezone.utc)



def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None



def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None



def _row_to_task(row: sqlite3.Row) -> PhantomTask:
    return PhantomTask(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        schedule=row["schedule"],
        last_run=_parse(row["last_run"]),
        next_run=_parse(row["next_run"]),
        enabled=bool(row["enabled"]),
        handler_function=row["handler_function"],
        config=json.loads(row["config"]),
    )



def _row_to_watch(row: sqlite3.Row) -> WatchTarget:
    return WatchTarget(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        target=row["target"],
        check_interval_minutes=int(row["check_interval_minutes"]),
        last_checked=_parse(row["last_checked"]),
        last_hash=row["last_hash"],
        on_change_action=row["on_change_action"],
        on_change_config=json.loads(row["on_change_config"]),
        enabled=bool(row["enabled"]),
    )



def _save_task(task: PhantomTask) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO tasks
            (id, name, description, schedule, last_run, next_run, enabled, handler_function, config)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task.id, task.name, task.description, task.schedule, _iso(task.last_run), _iso(task.next_run), int(task.enabled), task.handler_function, json.dumps(task.config, ensure_ascii=True)),
        )
        connection.commit()



def _save_watch(watch: WatchTarget) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO watches
            (id, name, type, target, check_interval_minutes, last_checked, last_hash, on_change_action, on_change_config, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (watch.id, watch.name, watch.type, watch.target, watch.check_interval_minutes, _iso(watch.last_checked), watch.last_hash, watch.on_change_action, json.dumps(watch.on_change_config, ensure_ascii=True), int(watch.enabled)),
        )
        connection.commit()



def _load_task(task_id: str) -> PhantomTask:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise PhantomError(f"task not found: {task_id}")
    return _row_to_task(row)



def _load_watch(watch_id: str) -> WatchTarget:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
    if row is None:
        raise PhantomError(f"watch not found: {watch_id}")
    return _row_to_watch(row)



def _set_state(key: str, value: str) -> None:
    with _connect() as connection:
        connection.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value))
        connection.commit()



def _get_state(key: str, default: str = "") -> str:
    with _connect() as connection:
        row = connection.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default



def _task_next_run(schedule: str, last_run: datetime | None = None) -> datetime:
    base = last_run or _now()
    if schedule.startswith("every:"):
        try:
            hours = float(schedule.split(":", 1)[1])
            return base + timedelta(hours=hours)
        except Exception:
            return base + timedelta(hours=1)
    if schedule == "hourly":
        return base + timedelta(hours=1)
    if schedule == "weekly":
        return base + timedelta(days=7)
    if schedule == "daily":
        return base + timedelta(days=1)
    if schedule.startswith("daily@"):
        return base + timedelta(days=1)
    if schedule == "@startup":
        return base + timedelta(days=3650)
    try:
        from schedule import every  # type: ignore

        _ = every
    except Exception:
        pass
    return base + timedelta(days=1)



def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()



def _initial_watch_hash(target: str, type: str) -> str:
    if type in {"url", "portal", "feed"}:
        from aura.agents.iris import tools as iris_tools

        content = iris_tools.fetch_url(target, extract_main_content=True)
        return _hash_text(content.main_text)
    if type == "folder":
        path = Path(target).expanduser()
        if not path.exists():
            return _hash_text("")
        listing = [str(item.relative_to(path)) for item in sorted(path.rglob("*"))]
        return _hash_text("\n".join(listing))
    return _hash_text(target)



def _trigger_watch_action(watch: WatchTarget, payload: dict[str, Any]) -> None:
    _EVENT_BUS.publish_sync("phantom.watch_triggered", {"watch_id": watch.id, "watch": watch.name, **payload})
    if watch.on_change_action == "alert":
        send_notification(watch.name, json.dumps(payload, ensure_ascii=True))
    elif watch.on_change_action == "save_memory":
        save_memory(watch.name, json.dumps(payload, ensure_ascii=True), "general", tags=["phantom", "watch"], source="phantom", confidence=0.8)
    else:
        _EVENT_BUS.publish_sync(watch.on_change_action, payload)



def _ensure_default_tasks() -> None:
    global _DEFAULT_TASKS_LOADED
    if _DEFAULT_TASKS_LOADED:
        return
    with _connect() as connection:
        existing = {row["handler_function"] for row in connection.execute("SELECT handler_function FROM tasks").fetchall()}
    defaults = [
        ("daily-briefing", "Daily Briefing", "daily briefing", "daily", "generate_daily_briefing"),
        ("memory-consolidation", "Memory Consolidation", "merge similar memories", "weekly", "mneme.consolidate_memory"),
        ("system-health", "System Health Check", "check system metrics", "hourly", "system_health_check"),
        ("workflow-recovery", "Stale Workflow Recovery", "resume interrupted workflows", "hourly", "workflow_recovery"),
    ]
    for task_id, name, description, schedule, handler in defaults:
        if handler in existing:
            continue
        task = PhantomTask(id=task_id, name=name, description=description, schedule=schedule, last_run=None, next_run=_task_next_run(schedule, _now() - timedelta(days=1)), enabled=True, handler_function=handler, config={})
        _save_task(task)
    _DEFAULT_TASKS_LOADED = True



def _ensure_ready() -> None:
    CONFIG.paths.data_dir.mkdir(parents=True, exist_ok=True)
    _connect().close()
    _ensure_default_tasks()



def _system_health_check() -> str:
    from aura.agents.aegis import tools as aegis_tools

    snapshot = aegis_tools.get_system_info()
    if snapshot.cpu_percent > 90:
        send_notification("AURA", "CPU above 90%")
    return "system-health-ok"



def _workflow_recovery() -> str:
    from aura.agents.director import tools as director_tools

    resumed = director_tools.resume_interrupted_workflows()
    return ",".join(resumed)



def _get_handler(name: str) -> Callable[[], Any]:
    if name in _REGISTERED_TASK_HANDLERS:
        return _REGISTERED_TASK_HANDLERS[name]
    if name == "generate_daily_briefing":
        return generate_daily_briefing
    if name == "mneme.consolidate_memory":
        return lambda: consolidate_memory()
    if name == "system_health_check":
        return _system_health_check
    if name == "workflow_recovery":
        return _workflow_recovery
    if "." in name:
        module_name, _, attr = name.rpartition(".")
        try:
            module = __import__(module_name, fromlist=[attr])
            handler = getattr(module, attr)
            if callable(handler):
                return handler
        except Exception:
            pass
    raise PhantomError(f"unknown handler: {name}")



def register_watch(name: str, type: str, target: str, check_interval_minutes: int, on_change_action: str, on_change_config: dict[str, Any] | None = None) -> WatchTarget:
    _ensure_ready()
    watch = WatchTarget(id=str(uuid.uuid4()), name=name, type=type, target=target, check_interval_minutes=check_interval_minutes, last_checked=_now(), last_hash="", on_change_action=on_change_action, on_change_config=on_change_config or {}, enabled=True)
    watch.last_hash = _initial_watch_hash(target, type)
    _save_watch(watch)
    if type == "folder":
        from aura.agents.atlas import tools as atlas_tools

        event_name = f"phantom.watch.{watch.id}"

        async def _handler(topic: str, payload: Any) -> None:
            _trigger_watch_action(watch, {"topic": topic, "payload": payload, "watch_id": watch.id})

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_EVENT_BUS.subscribe(event_name, _handler))
        except RuntimeError:
            pass
        try:
            atlas_tools.watch_folder(target, event_name)
        except Exception:
            pass
    return watch



def disable_watch(watch_id: str) -> Any:
    watch = _load_watch(watch_id)
    watch.enabled = False
    _save_watch(watch)
    return {"success": True, "message": "watch disabled", "data": {"watch_id": watch_id}}



def enable_watch(watch_id: str) -> Any:
    watch = _load_watch(watch_id)
    watch.enabled = True
    _save_watch(watch)
    return {"success": True, "message": "watch enabled", "data": {"watch_id": watch_id}}



def list_watches() -> list[WatchTarget]:
    _ensure_ready()
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM watches ORDER BY name ASC").fetchall()
    return [_row_to_watch(row) for row in rows]



def _task_due(task: PhantomTask) -> bool:
    return task.enabled and task.next_run is not None and task.next_run <= _now()



def run_scheduled_tasks() -> list[str]:
    _ensure_ready()
    if _PAUSED:
        return []
    ran: list[str] = []
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM tasks ORDER BY name ASC").fetchall()
    for row in rows:
        task = _row_to_task(row)
        if not _task_due(task):
            continue
        handler = _get_handler(task.handler_function)
        handler()
        task.last_run = _now()
        task.next_run = _task_next_run(task.schedule, task.last_run)
        _save_task(task)
        ran.append(task.name)
        _EVENT_BUS.publish_sync("phantom.task_run", {"task_id": task.id, "name": task.name, "schedule": task.schedule})
    return ran



def _check_watch(watch: WatchTarget) -> bool:
    if not watch.enabled:
        return False
    if watch.type in {"url", "portal", "feed"}:
        from aura.agents.iris import tools as iris_tools

        content = iris_tools.fetch_url(watch.target, extract_main_content=True)
        current_hash = _hash_text(content.main_text)
        if current_hash != watch.last_hash:
            watch.last_hash = current_hash
            watch.last_checked = _now()
            _save_watch(watch)
            _trigger_watch_action(watch, {"watch_id": watch.id, "target": watch.target, "hash": current_hash})
            if watch.on_change_action == "save_memory":
                save_memory(watch.name, content.main_text, "technical", tags=["phantom", "watch"], source="phantom", confidence=0.8)
            return True
        watch.last_checked = _now()
        _save_watch(watch)
        return False
    if watch.type == "folder":
        return False
    return False


async def check_all_watches() -> list[str]:
    if _PAUSED:
        return []
    triggered: list[str] = []
    for watch in list_watches():
        if _check_watch(watch):
            triggered.append(watch.name)
    return triggered



def generate_daily_briefing() -> Briefing:
    from aura.agents.aegis import tools as aegis_tools
    from aura.agents.iris import tools as iris_tools

    today = _now().date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    meetings = echo_tools.list_meetings({"start": start.isoformat(), "end": end.isoformat()})
    pending_tasks = [record.value for record in list_memories(category="tasks", limit=20)]
    preferences = list_memories(category="preferences", limit=10)
    interests = [record.value for record in preferences] or ["general AI research"]
    arxiv_papers = []
    for interest in interests[:3]:
        arxiv_papers.extend(iris_tools.search_academic(interest, source="arxiv", max_results=3))
    system_health = aegis_tools.get_system_info()
    summary_text = f"{len(meetings)} meetings, {len(pending_tasks)} pending tasks, {len(arxiv_papers)} papers."
    briefing = Briefing(
        generated_at=_now(),
        date=today.isoformat(),
        meetings_today=meetings,
        pending_tasks=pending_tasks,
        new_assignments=[],
        arxiv_papers=arxiv_papers,
        github_events=[],
        system_health=system_health,
        summary_text=summary_text,
    )
    send_notification("AURA Daily Briefing", summary_text)
    save_memory("daily-briefing", json.dumps({"summary": summary_text, "date": today.isoformat()}), "general", tags=["briefing"], source="phantom", confidence=0.8)
    _set_state("last_briefing_time", _now().isoformat())
    return briefing



def pause_all(duration_minutes: int | None = None) -> Any:
    global _PAUSED, _PAUSE_UNTIL
    _PAUSED = True
    _PAUSE_UNTIL = _now() + timedelta(minutes=duration_minutes) if duration_minutes is not None else None
    return {"success": True, "message": "phantom paused", "data": {"duration_minutes": duration_minutes}}



def resume_all() -> Any:
    global _PAUSED, _PAUSE_UNTIL
    _PAUSED = False
    _PAUSE_UNTIL = None
    return {"success": True, "message": "phantom resumed", "data": {}}



def get_phantom_status() -> dict[str, Any]:
    _ensure_ready()
    watches = list_watches()
    tasks = list_workflows()
    return {
        "is_running": not _PAUSED,
        "paused": _PAUSED,
        "active_watches": sum(1 for watch in watches if watch.enabled),
        "scheduled_tasks": len(tasks),
        "last_briefing_time": _get_state("last_briefing_time", ""),
    }



def list_workflows() -> list[PhantomTask]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM tasks ORDER BY name ASC").fetchall()
    return [_row_to_task(row) for row in rows]


def register_task(
    task_name: str,
    handler: Callable[[], Any],
    interval_hours: int | None = None,
    schedule: str | None = None,
    run_on_startup: bool = False,
    description: str | None = None,
) -> PhantomTask:
    """Register a reusable background task."""

    _ensure_ready()
    _REGISTERED_TASK_HANDLERS[task_name] = handler
    task_schedule = schedule or (f"every:{interval_hours}" if interval_hours is not None else "hourly")
    task = PhantomTask(
        id=task_name,
        name=task_name,
        description=description or (handler.__doc__ or task_name),
        schedule=task_schedule,
        last_run=None,
        next_run=_now() - timedelta(seconds=1) if run_on_startup else _task_next_run(task_schedule, _now()),
        enabled=True,
        handler_function=task_name,
        config={"run_on_startup": run_on_startup, "interval_hours": interval_hours},
    )
    _save_task(task)
    return task


def schedule_task(name: str, cron_expression: str, instruction: str, enabled: bool = True) -> PhantomTask:
    """Compatibility wrapper for the requested schedule API."""

    task = register_task(
        task_name=name,
        handler=lambda: instruction,
        schedule=cron_expression,
        description=instruction,
    )
    task.enabled = enabled
    _save_task(task)
    _EVENT_BUS.publish_sync("phantom.task_scheduled", {"task_id": task.id, "name": task.name, "schedule": task.schedule})
    return task


def enable_task(task_id: str) -> bool:
    task = _load_task(task_id)
    task.enabled = True
    _save_task(task)
    return True


def disable_task(task_id: str) -> bool:
    task = _load_task(task_id)
    task.enabled = False
    _save_task(task)
    return True


def delete_task(task_id: str) -> bool:
    with _connect() as connection:
        connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        connection.commit()
    return True


def get_task_log(task_id: str, limit: int = 50) -> list[dict[str, Any]]:
    log_path = CONFIG.paths.data_dir / "phantom_log.jsonl"
    if not log_path.exists():
        return []
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    filtered = [entry for entry in entries if entry.get("task_id") == task_id]
    return filtered[-limit:]


def _append_log(payload: dict[str, Any]) -> None:
    log_path = CONFIG.paths.data_dir / "phantom_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def run_task(task_id: str) -> dict[str, Any]:
    if task_id in _RUNNING_TASKS:
        return {"task_id": task_id, "status": "running"}
    task = _load_task(task_id)
    _RUNNING_TASKS.add(task_id)
    try:
        from aura.core.agent_loop import ReActAgentLoop
        from aura.core.llm_router import OllamaRouter

        loop = ReActAgentLoop(router=OllamaRouter(model=CONFIG.primary_model.name, host=CONFIG.primary_model.host))
        result = asyncio.run(loop.run(task.description))
        payload = {"timestamp": _now().isoformat(), "task_id": task.id, "name": task.name, "instruction": task.description, "result": getattr(result, "answer", str(result))}
        _append_log(payload)
        task.last_run = _now()
        task.next_run = _task_next_run(task.schedule, task.last_run)
        _save_task(task)
        return payload
    finally:
        _RUNNING_TASKS.discard(task_id)


def start_scheduler() -> None:
    async def _loop() -> None:
        while True:
            for task in list_workflows():
                if task.enabled and task.next_run is not None and task.next_run <= _now() and task.id not in _RUNNING_TASKS:
                    asyncio.create_task(asyncio.to_thread(run_task, task.id))
            await asyncio.sleep(60)

    try:
        asyncio.get_running_loop().create_task(_loop())
    except RuntimeError:
        return


async def phantom_loop() -> None:
    while True:
        if _PAUSED and _PAUSE_UNTIL is not None and _now() >= _PAUSE_UNTIL:
            resume_all()
        if not _PAUSED:
            run_scheduled_tasks()
            await check_all_watches()
        await asyncio.sleep(60)



def register_phantom_tools() -> None:
    registry = get_tool_registry()
    specs = [
        ToolSpec("register_watch", "Register a watch target.", 1, {"type": "object"}, {"type": "object"}, lambda args: register_watch(args["name"], args["type"], args["target"], args["check_interval_minutes"], args["on_change_action"], args.get("on_change_config"))),
        ToolSpec("disable_watch", "Disable a watch.", 1, {"type": "object"}, {"type": "object"}, lambda args: disable_watch(args["watch_id"])),
        ToolSpec("enable_watch", "Enable a watch.", 1, {"type": "object"}, {"type": "object"}, lambda args: enable_watch(args["watch_id"])),
        ToolSpec("list_watches", "List watches.", 1, {"type": "object"}, {"type": "array"}, lambda _args: list_watches()),
        ToolSpec("run_scheduled_tasks", "Run scheduled tasks.", 1, {"type": "object"}, {"type": "array"}, lambda _args: run_scheduled_tasks()),
        ToolSpec("generate_daily_briefing", "Generate a daily briefing.", 1, {"type": "object"}, {"type": "object"}, lambda _args: generate_daily_briefing()),
        ToolSpec("pause_all", "Pause all background automation.", 1, {"type": "object"}, {"type": "object"}, lambda args: pause_all(args.get("duration_minutes"))),
        ToolSpec("resume_all", "Resume all background automation.", 1, {"type": "object"}, {"type": "object"}, lambda _args: resume_all()),
        ToolSpec("get_phantom_status", "Return PHANTOM status.", 1, {"type": "object"}, {"type": "object"}, lambda _args: get_phantom_status()),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_phantom_tools()
