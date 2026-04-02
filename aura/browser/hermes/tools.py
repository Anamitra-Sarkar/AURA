"""Browser automation tools for HERMES."""

from __future__ import annotations

import html
import json
import re
import shutil
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import DownloadResult, ElementInfo, ExtractedData, OperationResult, PageHandle

LOGGER = get_logger(__name__, component="hermes")
CONFIG: AppConfig = load_config()
_EVENT_BUS: EventBus = EventBus()
_PAGES: dict[str, dict[str, Any]] = {}
_BLOCKLIST: set[str] = set()


class HermesError(Exception):
    """Raised when a browser operation cannot be completed."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(html.unescape(text))


class _ElementCollector(HTMLParser):
    def __init__(self, target_tag: str | None = None, target_id: str | None = None, target_class: str | None = None) -> None:
        super().__init__()
        self.target_tag = target_tag
        self.target_id = target_id
        self.target_class = target_class
        self.matches: list[dict[str, Any]] = []
        self._capture = 0
        self._current: dict[str, Any] | None = None

    def _is_target(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        attr_map = {key: value or "" for key, value in attrs}
        if self.target_tag and tag != self.target_tag:
            return False
        if self.target_id and attr_map.get("id") != self.target_id:
            return False
        if self.target_class:
            classes = set(attr_map.get("class", "").split())
            if self.target_class not in classes:
                return False
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capture or self._is_target(tag, attrs):
            self._capture += 1
            attr_map = {key: value or "" for key, value in attrs}
            if self._current is None:
                self._current = {"tag": tag, "attrs": attr_map, "text": []}

    def handle_endtag(self, tag: str) -> None:
        if self._capture:
            self._capture -= 1
            if self._capture == 0 and self._current is not None:
                self.matches.append(
                    {
                        "tag": self._current["tag"],
                        "attrs": self._current["attrs"],
                        "text": " ".join(self._current["text"]).strip(),
                    }
                )
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture and self._current is not None:
            text = data.strip()
            if text:
                self._current["text"].append(html.unescape(text))


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "a":
            self.links.append((attr_map.get("href", ""), ""))

    def handle_data(self, data: str) -> None:
        if self.links:
            href, _ = self.links[-1]
            if href is not None:
                self.links[-1] = (href, f"{self.links[-1][1]} {data.strip()}".strip())


class _TableCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = 0
        self._in_row = 0
        self._in_cell = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table += 1
            if self._current_table is None:
                self._current_table = []
        elif self._in_table:
            if tag == "tr":
                self._in_row += 1
                if self._current_row is None:
                    self._current_row = []
            elif tag in {"td", "th"}:
                self._in_cell += 1
                self._cell_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._in_table -= 1
            if self._in_table == 0 and self._current_table is not None:
                self.tables.append(self._current_table)
                self._current_table = None
        elif tag == "tr" and self._in_row:
            self._in_row -= 1
            if self._in_row == 0 and self._current_table is not None and self._current_row is not None:
                self._current_table.append(self._current_row)
                self._current_row = None
        elif tag in {"td", "th"} and self._in_cell:
            self._in_cell -= 1
            if self._in_cell == 0 and self._current_row is not None:
                self._current_row.append(" ".join(self._cell_text).strip())
                self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            text = data.strip()
            if text:
                self._cell_text.append(html.unescape(text))


def set_config(config: AppConfig) -> None:
    global CONFIG, _BLOCKLIST
    CONFIG = config
    _BLOCKLIST = set()


def set_event_bus(event_bus: EventBus) -> None:
    global _EVENT_BUS
    _EVENT_BUS = event_bus


def _emit(action: str, page_id: str | None, url: str | None, selector: str | None, result: Any) -> None:
    payload = {
        "action": action,
        "page_id": page_id,
        "url": url,
        "selector": selector,
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _EVENT_BUS.publish_sync("hermes.action", payload)
    except Exception:
        LOGGER.info("hermes-event-publish-failed", extra=payload)


def _data_dir() -> Path:
    path = CONFIG.paths.data_dir / "browser"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _blocklist_path() -> Path:
    path = CONFIG.paths.data_dir / "blocklist.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("phishing.test\nmalware.test\n", encoding="utf-8")
    return path


def _load_blocklist() -> set[str]:
    if _BLOCKLIST:
        return _BLOCKLIST
    try:
        return {line.strip().lower() for line in _blocklist_path().read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")}
    except Exception:
        return set()


def _is_blocked(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return any(host == entry or host.endswith(f".{entry}") for entry in _load_blocklist())


def _fetch_url(url: str) -> tuple[str, int, str]:
    if url.startswith("file://"):
        path = Path(urllib.parse.urlparse(url).path)
        return path.read_text(encoding="utf-8"), 200, path.name
    path = Path(url)
    if path.exists():
        return path.read_text(encoding="utf-8"), 200, path.name
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310 - local-first tooling
        body = response.read().decode("utf-8", errors="replace")
        status = getattr(response, "status", 200)
        title = _title_from_html(body) or urllib.parse.urlparse(url).netloc
        return body, int(status), title


def _title_from_html(content: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", content, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())
    return ""


def _page(page_id: str) -> dict[str, Any]:
    try:
        return _PAGES[page_id]
    except KeyError as exc:
        raise HermesError(f"page not found: {page_id}") from exc


def open_url(url: str, check_safety: bool = True, wait_for: str = "load") -> PageHandle:
    if check_safety and _is_blocked(url):
        raise HermesError(f"url blocked: {url}")
    html_text, status_code, title = _fetch_url(url)
    page_id = str(uuid.uuid4())
    _PAGES[page_id] = {"url": url, "html": html_text, "title": title or url, "status_code": status_code, "wait_for": wait_for}
    handle = PageHandle(page_id=page_id, url=url, title=title or url, status_code=status_code)
    _emit("open_url", page_id, url, None, asdict(handle))
    return handle


def navigate(page_id: str, url: str) -> PageHandle:
    if _is_blocked(url):
        raise HermesError(f"url blocked: {url}")
    html_text, status_code, title = _fetch_url(url)
    page = _page(page_id)
    page.update({"url": url, "html": html_text, "title": title or url, "status_code": status_code})
    handle = PageHandle(page_id=page_id, url=url, title=title or url, status_code=status_code)
    _emit("navigate", page_id, url, None, asdict(handle))
    return handle


def _find_matches(html_text: str, selector: str | None, description: str | None) -> list[dict[str, Any]]:
    if selector:
        selector = selector.strip()
    if not selector and description:
        selector = description.strip()
    if not selector:
        return []
    if selector.startswith("#"):
        parser = _ElementCollector(target_id=selector[1:])
    elif selector.startswith("."):
        parser = _ElementCollector(target_class=selector[1:])
    else:
        parser = _ElementCollector(target_tag=selector.split()[0].lower())
    parser.feed(html_text)
    return parser.matches


def click(page_id: str, selector: str | None = None, description: str | None = None) -> OperationResult:
    page = _page(page_id)
    matches = _find_matches(page["html"], selector, description)
    if not matches:
        return OperationResult(False, "element not found", {"page_id": page_id, "selector": selector, "description": description})
    result = OperationResult(True, "clicked", {"page_id": page_id, "selector": selector or description, "matches": matches[:1]})
    _emit("click", page_id, page["url"], selector or description, asdict(result))
    return result


def type_text(page_id: str, selector: str | None = None, description: str | None = None, text: str = "", clear_first: bool = True) -> OperationResult:
    page = _page(page_id)
    matches = _find_matches(page["html"], selector, description)
    if not matches:
        return OperationResult(False, "element not found", {"page_id": page_id, "selector": selector, "description": description})
    result = OperationResult(True, "typed", {"page_id": page_id, "selector": selector or description, "text": text, "clear_first": clear_first})
    _emit("type_text", page_id, page["url"], selector or description, asdict(result))
    return result


def fill_form(page_id: str, fields: list[dict[str, Any]]) -> OperationResult:
    page = _page(page_id)
    results = []
    for field in fields:
        selector = field.get("selector") or field.get("selector_or_description") or field.get("description")
        field_type = field.get("field_type", "text")
        matches = _find_matches(page["html"], selector, field.get("description"))
        if not matches:
            return OperationResult(False, f"field not found: {selector}", {"page_id": page_id, "field": field})
        if field_type == "file":
            file_path = field.get("value") or field.get("file_path")
            if file_path is not None and not Path(str(file_path)).exists():
                return OperationResult(False, f"file not found: {file_path}", {"page_id": page_id, "field": field})
        results.append(field)
    result = OperationResult(True, "form filled", {"page_id": page_id, "fields": results})
    _emit("fill_form", page_id, page["url"], None, asdict(result))
    return result


def scroll(page_id: str, direction: str, amount: int = 300) -> OperationResult:
    page = _page(page_id)
    result = OperationResult(True, "scrolled", {"page_id": page_id, "direction": direction, "amount": amount})
    _emit("scroll", page_id, page["url"], None, asdict(result))
    return result


def take_screenshot(page_id: str | None = None, region: dict[str, Any] | None = None, save_path: str | None = None) -> str:
    target_dir = _data_dir() / "screenshots"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = Path(save_path) if save_path is not None else target_dir / f"{uuid.uuid4()}.png"
    path.write_bytes(b"HERMES-SCREENSHOT")
    _emit("take_screenshot", page_id, _PAGES.get(page_id or "", {}).get("url"), None, {"save_path": str(path), "region": region})
    return str(path)


def extract_data(page_id: str, schema: dict[str, Any]) -> ExtractedData:
    page = _page(page_id)
    html_text = page["html"]
    data: dict[str, Any] = {}
    for field_name, rules in schema.items():
        selector = rules.get("selector")
        field_type = rules.get("type", "text")
        multiple = bool(rules.get("multiple", False))
        matches = _find_matches(html_text, selector, None)
        if field_type == "table":
            parser = _TableCollector()
            parser.feed(html_text)
            data[field_name] = parser.tables if multiple else (parser.tables[0] if parser.tables else [])
            continue
        if not matches:
            data[field_name] = [] if multiple else None
            continue
        values: list[Any] = []
        for match in matches:
            attrs = match["attrs"]
            if field_type == "href":
                values.append(attrs.get("href"))
            elif field_type == "src":
                values.append(attrs.get("src"))
            elif field_type == "html":
                values.append(json.dumps(match, ensure_ascii=True))
            else:
                values.append(match["text"])
        data[field_name] = values if multiple else values[0]
    extracted = ExtractedData(url=page["url"], schema_used=schema, data=data, extracted_at=datetime.now(timezone.utc))
    _emit("extract_data", page_id, page["url"], None, {"schema": schema, "data": data})
    return extracted


def download_file(page_id: str, selector_or_url: str, save_path: str) -> DownloadResult:
    page = _page(page_id)
    target = selector_or_url
    if not urllib.parse.urlparse(target).scheme:
        matches = _find_matches(page["html"], selector_or_url, None)
        if matches:
            target = matches[0]["attrs"].get("href") or matches[0]["attrs"].get("src") or ""
    if not target:
        raise HermesError("download target not found")
    destination = Path(save_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if target.startswith("file://") or Path(target).exists():
        source = Path(urllib.parse.urlparse(target).path if target.startswith("file://") else target)
        shutil.copyfile(source, destination)
    else:
        with urllib.request.urlopen(target, timeout=30) as response:  # noqa: S310 - local-first tooling
            destination.write_bytes(response.read())
    result = DownloadResult(True, str(destination), destination.name, destination.stat().st_size)
    _emit("download_file", page_id, page["url"], selector_or_url, asdict(result))
    return result


def upload_file(page_id: str, input_selector: str, file_path: str) -> OperationResult:
    page = _page(page_id)
    if not Path(file_path).exists():
        return OperationResult(False, "file not found", {"page_id": page_id, "file_path": file_path})
    result = OperationResult(True, "file uploaded", {"page_id": page_id, "selector": input_selector, "file_path": file_path})
    _emit("upload_file", page_id, page["url"], input_selector, asdict(result))
    return result


def wait_for_element(page_id: str, selector: str, timeout_ms: int = 5000) -> ElementInfo:
    page = _page(page_id)
    matches = _find_matches(page["html"], selector, None)
    if not matches:
        raise HermesError(f"element not found: {selector}")
    match = matches[0]
    info = ElementInfo(selector=selector, text=match["text"], tag=match["tag"], is_visible=True, bounding_box={"x": 0, "y": 0, "width": 0, "height": 0})
    _emit("wait_for_element", page_id, page["url"], selector, asdict(info))
    return info


def get_page_text(page_id: str) -> str:
    page = _page(page_id)
    extractor = _TextExtractor()
    extractor.feed(page["html"])
    text = "\n".join(extractor.parts)
    _emit("get_page_text", page_id, page["url"], None, {"length": len(text)})
    return text


def close_page(page_id: str) -> OperationResult:
    page = _PAGES.pop(page_id, None)
    if page is None:
        return OperationResult(False, "page not found", {"page_id": page_id})
    result = OperationResult(True, "page closed", {"page_id": page_id})
    _emit("close_page", page_id, page.get("url"), None, asdict(result))
    return result


def close_browser() -> OperationResult:
    _PAGES.clear()
    result = OperationResult(True, "browser closed", {})
    _emit("close_browser", None, None, None, asdict(result))
    return result


def register_hermes_tools() -> None:
    registry = get_tool_registry()

    def _click_tier(args: dict[str, Any]) -> int:
        selector = f"{args.get('selector', '')} {args.get('description', '')}".lower()
        destructive = {"confirm", "delete", "purchase", "submit"}
        return 3 if any(word in selector for word in destructive) else 1

    specs = [
        ToolSpec("open_url", "Open a URL in a browser page.", 1, {"type": "object"}, {"type": "object"}, lambda args: open_url(args["url"], args.get("check_safety", True), args.get("wait_for", "load"))),
        ToolSpec("navigate", "Navigate an open page.", 1, {"type": "object"}, {"type": "object"}, lambda args: navigate(args["page_id"], args["url"])),
        ToolSpec("click", "Click an element.", 1, {"type": "object"}, {"type": "object"}, lambda args: click(args["page_id"], args.get("selector"), args.get("description")), tier_resolver=_click_tier),
        ToolSpec("type_text", "Type text into an element.", 1, {"type": "object"}, {"type": "object"}, lambda args: type_text(args["page_id"], args.get("selector"), args.get("description"), args.get("text", ""), args.get("clear_first", True))),
        ToolSpec("fill_form", "Fill multiple form fields.", 1, {"type": "object"}, {"type": "object"}, lambda args: fill_form(args["page_id"], args.get("fields", []))),
        ToolSpec("scroll", "Scroll a page.", 1, {"type": "object"}, {"type": "object"}, lambda args: scroll(args["page_id"], args["direction"], args.get("amount", 300))),
        ToolSpec("take_screenshot", "Capture a screenshot.", 1, {"type": "object"}, {"type": "string"}, lambda args: take_screenshot(args.get("page_id"), args.get("region"), args.get("save_path"))),
        ToolSpec("extract_data", "Extract structured data from a page.", 1, {"type": "object"}, {"type": "object"}, lambda args: extract_data(args["page_id"], args["schema"])),
        ToolSpec("download_file", "Download a file.", 2, {"type": "object"}, {"type": "object"}, lambda args: download_file(args["page_id"], args["selector_or_url"], args["save_path"])),
        ToolSpec("upload_file", "Upload a file.", 2, {"type": "object"}, {"type": "object"}, lambda args: upload_file(args["page_id"], args["input_selector"], args["file_path"])),
        ToolSpec("wait_for_element", "Wait for an element.", 1, {"type": "object"}, {"type": "object"}, lambda args: wait_for_element(args["page_id"], args["selector"], args.get("timeout_ms", 5000))),
        ToolSpec("get_page_text", "Get visible text from a page.", 1, {"type": "object"}, {"type": "string"}, lambda args: get_page_text(args["page_id"])),
        ToolSpec("close_page", "Close a page.", 1, {"type": "object"}, {"type": "object"}, lambda args: close_page(args["page_id"])),
        ToolSpec("close_browser", "Close the browser.", 1, {"type": "object"}, {"type": "object"}, lambda _args: close_browser()),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_hermes_tools()
