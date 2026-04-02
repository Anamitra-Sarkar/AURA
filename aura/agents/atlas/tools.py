"""ATLAS file system tools."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tarfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.logging import get_logger
from aura.core.platform import open_path as platform_open_path
from aura.core.tools import ToolSpec, get_tool_registry

from .models import FileContent, FileEntry, FileMatch, OperationResult, WatchHandle

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover - optional dependency
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None  # type: ignore[assignment]

LOGGER = get_logger(__name__, component="atlas")
CONFIG: AppConfig = load_config()
_EVENT_BUS: EventBus = EventBus()
_WATCHERS: dict[str, Any] = {}
_WATCH_LOOP: asyncio.AbstractEventLoop | None = None

TEXT_EXTENSIONS = {".txt", ".py", ".js", ".ts", ".md", ".json", ".yaml", ".yml", ".csv"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}


class AtlasError(Exception):
    """Raised when an Atlas operation is invalid."""


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration."""

    global CONFIG
    CONFIG = config


def set_event_bus(event_bus: EventBus) -> None:
    """Override the event bus used by watchers."""

    global _EVENT_BUS
    _EVENT_BUS = event_bus


def _timestamp(stat_time: float | None = None) -> str:
    """Format a timestamp as ISO 8601."""

    return datetime.fromtimestamp(stat_time or time.time(), tz=timezone.utc).isoformat()


def _is_within(child: Path, parent: Path) -> bool:
    """Return True when child is within parent."""

    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _validate_allowed(path: Path) -> Path:
    """Validate that a path stays inside allowed roots and has no traversal."""

    candidate = path.expanduser()
    if any(part == ".." for part in candidate.parts):
        raise AtlasError(f"path traversal rejected: {path}")
    resolved = candidate.resolve(strict=False)
    allowed_roots = CONFIG.paths.allowed_roots or [CONFIG.paths.data_dir]
    if not any(_is_within(resolved, root) or resolved == root.resolve() for root in allowed_roots):
        raise AtlasError(f"path outside allowed roots: {resolved}")
    return resolved


def _file_meta(path: Path) -> tuple[int, str]:
    """Return file size and modification time."""

    stat = path.stat()
    return stat.st_size, _timestamp(stat.st_mtime)


def _read_text(path: Path, max_bytes: int | None = None) -> tuple[str, str]:
    """Read a text file using UTF-8 with a Latin-1 fallback."""

    data = path.read_bytes()
    if max_bytes is not None:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), "latin-1"


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF file."""

    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_docx(path: Path) -> str:
    """Extract text from a DOCX file."""

    from docx import Document  # type: ignore

    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _content_snippet(text: str, query: str) -> str:
    """Return the best single-line snippet for a query."""

    query_lower = query.lower()
    for line in text.splitlines():
        if query_lower in line.lower():
            return line.strip()
    return text[:200]


def _search_keyword(query: str, root_path: Path) -> list[FileMatch]:
    """Keyword search using rg when available, otherwise a Python fallback."""

    matches: list[FileMatch] = []
    rg = shutil.which("rg")
    if rg:
        proc = subprocess.run([rg, "-n", query, str(root_path)], capture_output=True, text=True, check=False)
        if proc.stdout:
            for line in proc.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_path = Path(parts[0])
                snippet = parts[2].strip()
                _, modified = _file_meta(file_path) if file_path.exists() else (0, _timestamp())
                matches.append(FileMatch(path=str(file_path), snippet=snippet, score=1.0, modified_date=modified))
            return matches
    query_lower = query.lower()
    for file_path in root_path.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            text, _ = _read_text(file_path, max_bytes=20000)
        except Exception:
            continue
        if query_lower in text.lower() or query_lower in file_path.name.lower():
            _, modified = _file_meta(file_path)
            matches.append(FileMatch(path=str(file_path), snippet=_content_snippet(text, query), score=1.0, modified_date=modified))
    return matches


def _search_semantic(query: str, root_path: Path) -> list[FileMatch]:
    """Simple free semantic scoring based on token overlap."""

    tokens = {token.lower() for token in query.split() if token.strip()}
    matches: list[FileMatch] = []
    for file_path in root_path.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            text, _ = _read_text(file_path, max_bytes=20000)
        except Exception:
            continue
        corpus = f"{file_path.name} {text[:2000]}".lower()
        score = sum(1 for token in tokens if token in corpus)
        if score:
            _, modified = _file_meta(file_path)
            matches.append(FileMatch(path=str(file_path), snippet=_content_snippet(text, query), score=float(score), modified_date=modified))
    return matches


def _merge_matches(*groups: list[FileMatch]) -> list[FileMatch]:
    """Merge and deduplicate matches, preferring the highest score."""

    dedup: dict[str, FileMatch] = {}
    for group in groups:
        for item in group:
            current = dedup.get(item.path)
            if current is None or item.score > current.score:
                dedup[item.path] = item
    return sorted(dedup.values(), key=lambda item: item.score, reverse=True)


def _backup_file(path: Path) -> Path:
    """Copy an existing file into a sibling backup directory."""

    backup_root = path.parent / ".aura_backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"{path.name}.{int(time.time())}.bak"
    if path.exists():
        shutil.copy2(path, backup_path)
    return backup_path


def _trash_file(path: Path) -> Path:
    """Return a sibling trash path."""

    trash_root = path.parent / ".aura_trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    return trash_root / f"{path.name}.{int(time.time())}.trash"


def _log_action(tool_name: str, path: str, user_confirmed: bool) -> None:
    """Log a tier-2/3 filesystem action."""

    LOGGER.info(
        "atlas-action",
        extra={"event": "atlas_action", "tool_name": tool_name, "path": path, "user_confirmed": user_confirmed},
    )


def _safe_return(op: str, path: Path, data: dict[str, Any] | None = None) -> OperationResult:
    """Helper for successful results."""

    return OperationResult(True, op, data or {"path": str(path)})


def search_files(query: str, root_path: str, mode: str) -> list[FileMatch]:
    """Search files by keyword, semantic score, or both."""

    resolved_root = _validate_allowed(Path(root_path))
    if not resolved_root.exists():
        raise AtlasError(f"root path does not exist: {resolved_root}")
    mode = mode.lower()
    if mode not in {"keyword", "semantic", "both"}:
        raise AtlasError(f"unsupported search mode: {mode}")
    keyword = _search_keyword(query, resolved_root) if mode in {"keyword", "both"} else []
    semantic = _search_semantic(query, resolved_root) if mode in {"semantic", "both"} else []
    return _merge_matches(keyword, semantic)


def read_file(path: str, max_bytes: int | None = None) -> FileContent:
    """Read a supported file from an allowed root."""

    resolved = _validate_allowed(Path(path))
    if not resolved.exists():
        raise AtlasError(f"file not found: {resolved}")
    extension = resolved.suffix.lower()
    size_bytes, modified_date = _file_meta(resolved)
    if extension == ".pdf":
        content = _read_pdf(resolved)
        encoding = "utf-8"
    elif extension == ".docx":
        content = _read_docx(resolved)
        encoding = "utf-8"
    elif extension in SUPPORTED_EXTENSIONS:
        content, encoding = _read_text(resolved, max_bytes=max_bytes)
    else:
        raise AtlasError(f"unsupported file type: {extension}")
    return FileContent(
        path=str(resolved),
        content=content,
        encoding=encoding,
        size_bytes=size_bytes,
        modified_date=modified_date,
        file_type=extension.lstrip("."),
    )


def write_file(path: str, content: str, mode: str = "overwrite") -> OperationResult:
    """Write, append, or patch a file with backup support."""

    resolved = _validate_allowed(Path(path))
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        if mode == "overwrite":
            if resolved.exists():
                _backup_file(resolved)
            resolved.write_text(content, encoding="utf-8")
        elif mode == "append":
            if resolved.exists():
                _backup_file(resolved)
            with resolved.open("a", encoding="utf-8") as handle:
                handle.write(content)
        elif mode == "patch":
            if not resolved.exists():
                return OperationResult(False, "target missing for patch", {"path": str(resolved)})
            _backup_file(resolved)
            patch_file = resolved.parent / f".{resolved.name}.patch"
            patch_file.write_text(content, encoding="utf-8")
            proc = subprocess.run(["patch", str(resolved), "-i", str(patch_file), "-s"], capture_output=True, text=True, check=False)
            patch_file.unlink(missing_ok=True)
            if proc.returncode != 0:
                return OperationResult(False, proc.stderr.strip() or proc.stdout.strip() or "patch failed", {"path": str(resolved)})
        else:
            return OperationResult(False, f"unsupported write mode: {mode}", {"path": str(resolved)})
        _log_action("write_file", str(resolved), True)
        return _safe_return("file written", resolved)
    except Exception as exc:
        return OperationResult(False, str(exc), {"path": str(resolved)})


def move_file(src: str, dst: str) -> OperationResult:
    """Move a file within allowed roots."""

    source = _validate_allowed(Path(src))
    target = _validate_allowed(Path(dst))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(target))
        _log_action("move_file", str(source), True)
        return OperationResult(True, "file moved", {"src": str(source), "dst": str(target)})
    except Exception as exc:
        return OperationResult(False, str(exc), {"src": str(source), "dst": str(target)})


def copy_file(src: str, dst: str) -> OperationResult:
    """Copy a file within allowed roots."""

    source = _validate_allowed(Path(src))
    target = _validate_allowed(Path(dst))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
        _log_action("copy_file", str(source), True)
        return OperationResult(True, "file copied", {"src": str(source), "dst": str(target)})
    except Exception as exc:
        return OperationResult(False, str(exc), {"src": str(source), "dst": str(target)})


def delete_file(path: str) -> OperationResult:
    """Move a file to a trash directory instead of deleting it."""

    resolved = _validate_allowed(Path(path))
    trash_path = _trash_file(resolved)
    try:
        if resolved.exists():
            shutil.move(str(resolved), str(trash_path))
        _log_action("delete_file", str(resolved), True)
        return OperationResult(True, "file trashed", {"path": str(resolved), "trash": str(trash_path)})
    except Exception as exc:
        return OperationResult(False, str(exc), {"path": str(resolved), "trash": str(trash_path)})


def rename_file(path: str, new_name: str) -> OperationResult:
    """Rename a file."""

    resolved = _validate_allowed(Path(path))
    target = _validate_allowed(resolved.with_name(new_name))
    try:
        resolved.rename(target)
        _log_action("rename_file", str(resolved), True)
        return OperationResult(True, "file renamed", {"src": str(resolved), "dst": str(target)})
    except Exception as exc:
        return OperationResult(False, str(exc), {"src": str(resolved), "dst": str(target)})


def open_file(path: str) -> OperationResult:
    """Open a file or folder with the platform default handler."""

    resolved = _validate_allowed(Path(path))
    result = platform_open_path(resolved)
    return OperationResult(result.ok, result.message, {"path": str(resolved), **(result.details or {})})


def list_directory(path: str, filters: dict[str, Any] | None = None) -> list[FileEntry]:
    """List directory entries with optional metadata filters."""

    resolved = _validate_allowed(Path(path))
    if not resolved.exists():
        raise AtlasError(f"directory not found: {resolved}")
    filters = filters or {}
    entries: list[FileEntry] = []
    extension = filters.get("extension")
    min_size = filters.get("min_size")
    max_size = filters.get("max_size")
    modified_after = filters.get("modified_after")
    modified_before = filters.get("modified_before")
    after_ts = datetime.fromisoformat(modified_after).timestamp() if modified_after else None
    before_ts = datetime.fromisoformat(modified_before).timestamp() if modified_before else None
    for child in resolved.iterdir():
        stat = child.stat()
        if extension and child.suffix.lower() != str(extension).lower():
            continue
        if min_size is not None and stat.st_size < int(min_size):
            continue
        if max_size is not None and stat.st_size > int(max_size):
            continue
        if after_ts is not None and stat.st_mtime < after_ts:
            continue
        if before_ts is not None and stat.st_mtime > before_ts:
            continue
        entries.append(
            FileEntry(
                path=str(child),
                name=child.name,
                size_bytes=stat.st_size,
                modified_date=_timestamp(stat.st_mtime),
                is_dir=child.is_dir(),
                extension=child.suffix,
            )
        )
    return entries


def compress_folder(path: str, archive_path: str) -> OperationResult:
    """Compress a folder into a zip archive."""

    source = _validate_allowed(Path(path))
    archive = _validate_allowed(Path(archive_path))
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for child in source.rglob("*"):
                if child.is_file():
                    zf.write(child, child.relative_to(source))
        _log_action("compress_folder", str(source), True)
        return OperationResult(True, "archive created", {"path": str(source), "archive": str(archive)})
    except Exception as exc:
        return OperationResult(False, str(exc), {"path": str(source), "archive": str(archive)})


def extract_archive(archive_path: str, dst: str) -> OperationResult:
    """Extract ZIP or TAR archives."""

    archive = _validate_allowed(Path(archive_path))
    destination = _validate_allowed(Path(dst))
    destination.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(destination)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                tf.extractall(destination)
        else:
            return OperationResult(False, "unsupported archive format", {"archive": str(archive)})
        _log_action("extract_archive", str(archive), True)
        return OperationResult(True, "archive extracted", {"archive": str(archive), "dst": str(destination)})
    except Exception as exc:
        return OperationResult(False, str(exc), {"archive": str(archive), "dst": str(destination)})


def watch_folder(path: str, callback_event: str) -> WatchHandle:
    """Watch a folder and publish create/modify/delete/move events."""

    if Observer is None:
        raise AtlasError("watchdog is unavailable")
    resolved = _validate_allowed(Path(path))
    watch_id = str(uuid.uuid4())
    global _WATCH_LOOP
    _WATCH_LOOP = asyncio.get_running_loop()

    class _Handler(FileSystemEventHandler):  # type: ignore[misc]
        def _publish(self, payload: dict[str, Any]) -> None:
            if _WATCH_LOOP is None:
                return
            asyncio.run_coroutine_threadsafe(_EVENT_BUS.publish(callback_event, payload), _WATCH_LOOP)

        def on_created(self, event):  # type: ignore[override]
            self._publish({"event": "create", "path": getattr(event, "src_path", None)})

        def on_modified(self, event):  # type: ignore[override]
            self._publish({"event": "modify", "path": getattr(event, "src_path", None)})

        def on_deleted(self, event):  # type: ignore[override]
            self._publish({"event": "delete", "path": getattr(event, "src_path", None)})

        def on_moved(self, event):  # type: ignore[override]
            self._publish({"event": "move", "path": getattr(event, "src_path", None), "dst": getattr(event, "dest_path", None)})

    observer = Observer()
    observer.schedule(_Handler(), str(resolved), recursive=True)
    observer.daemon = True
    observer.start()
    _WATCHERS[watch_id] = observer
    return WatchHandle(watch_id=watch_id, path=str(resolved), active=True)


def _tool_schema(arguments: dict[str, Any], returns: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return JSON-schema-like definitions for tools."""

    return arguments, returns


def register_atlas_tools() -> None:
    """Register Atlas tools in the global tool registry."""

    registry = get_tool_registry()
    registrations = [
        ToolSpec(
            name="search_files",
            description="Search files by keyword or semantic similarity.",
            tier=1,
            arguments_schema={"type": "object", "properties": {"query": {"type": "string"}, "root_path": {"type": "string"}, "mode": {"type": "string", "enum": ["keyword", "semantic", "both"]}}, "required": ["query", "root_path", "mode"], "additionalProperties": False},
            return_schema={"type": "array"},
            handler=lambda args: search_files(args["query"], args["root_path"], args["mode"]),
        ),
        ToolSpec("read_file", "Read a file from an allowed root.", 1, {"type": "object", "properties": {"path": {"type": "string"}, "max_bytes": {"type": ["integer", "null"]}}, "required": ["path"], "additionalProperties": False}, {"type": "object"}, lambda args: read_file(args["path"], args.get("max_bytes"))),
        ToolSpec("write_file", "Write, append, or patch a file.", 2, {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "mode": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}, {"type": "object"}, lambda args: write_file(args["path"], args["content"], args.get("mode", "overwrite"))),
        ToolSpec("move_file", "Move a file.", 2, {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"], "additionalProperties": False}, {"type": "object"}, lambda args: move_file(args["src"], args["dst"])),
        ToolSpec("copy_file", "Copy a file.", 2, {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"], "additionalProperties": False}, {"type": "object"}, lambda args: copy_file(args["src"], args["dst"])),
        ToolSpec("delete_file", "Move a file to trash.", 3, {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}, {"type": "object"}, lambda args: delete_file(args["path"])),
        ToolSpec("rename_file", "Rename a file.", 2, {"type": "object", "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["path", "new_name"], "additionalProperties": False}, {"type": "object"}, lambda args: rename_file(args["path"], args["new_name"])),
        ToolSpec("open_file", "Open a file or folder.", 1, {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}, {"type": "object"}, lambda args: open_file(args["path"])),
        ToolSpec("list_directory", "List a directory.", 1, {"type": "object", "properties": {"path": {"type": "string"}, "filters": {"type": ["object", "null"]}}, "required": ["path"], "additionalProperties": False}, {"type": "array"}, lambda args: list_directory(args["path"], args.get("filters"))),
        ToolSpec("compress_folder", "Compress a folder as zip.", 2, {"type": "object", "properties": {"path": {"type": "string"}, "archive_path": {"type": "string"}}, "required": ["path", "archive_path"], "additionalProperties": False}, {"type": "object"}, lambda args: compress_folder(args["path"], args["archive_path"])),
        ToolSpec("extract_archive", "Extract zip or tar archives.", 2, {"type": "object", "properties": {"archive_path": {"type": "string"}, "dst": {"type": "string"}}, "required": ["archive_path", "dst"], "additionalProperties": False}, {"type": "object"}, lambda args: extract_archive(args["archive_path"], args["dst"])),
        ToolSpec("watch_folder", "Watch a folder for changes.", 1, {"type": "object", "properties": {"path": {"type": "string"}, "callback_event": {"type": "string"}}, "required": ["path", "callback_event"], "additionalProperties": False}, {"type": "object"}, lambda args: watch_folder(args["path"], args["callback_event"])),
    ]
    for spec in registrations:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_atlas_tools()
