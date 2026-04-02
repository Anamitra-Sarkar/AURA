# AURA Implementation Playbook (Free-Model Edition)

## 0. Document Purpose and Conventions

This document is written so that **both humans and AI co-developers** can understand, extend, and implement AURA end-to-end.

- Every phase has:
  - **Objective**: what this phase must achieve.
  - **Dependencies**: which phases or tools must exist first.
  - **Status**: `NOT_STARTED`, `IN_PROGRESS`, or `DONE`.
  - **Tasks Checklist**: concrete steps that can be executed and then marked as done.
  - **Interfaces**: important functions/classes, with expected inputs/outputs.
  - **AI Notes**: explicit instructions for an AI reading this file.
- **Constraint**: The entire system must remain usable **for free** for both the developer and end users. No paid model APIs (GPT‑4o, Claude, commercial Gemini, etc.) are allowed in the default path.
- **Models**: Only use **open-weight / free models** that can run locally or on free community endpoints.
- When updating this plan, always update the **Status** and **Tasks Checklist** so future agents can see clearly what remains.

### Global Status Codes

For each phase, set one of:

- `Status: NOT_STARTED`
- `Status: IN_PROGRESS`
- `Status: DONE`

AI agents should **never assume** a phase is done. Always read the latest status and the checklist.

---

## 1. Model Stack (Free and Open Only)

### 1.1 Model Principles

- No paid, proprietary APIs in the default implementation path.
- Prefer **local models** via Ollama / llama.cpp / vLLM / LM Studio / text-generation-webui.
- Prefer models with:
  - Good reasoning and tool-calling ability.
  - Open weights and permissive license for personal and research use.
- Higher-parameter models are **optional upgrades**, not required for AURA to function.

### 1.2 Recommended Free Model Set

These are suggestions; exact choices can be swapped if better free models appear later.

- **Primary Orchestration / Reasoning Models** (for NEXUS, DIRECTOR, ORACLE DEEP):
  - Llama 3 8B Instruct (local)
  - Mistral 7B Instruct (local)
  - Mixtral 8x7B Instruct (local, if hardware allows)
  - Gemma 2 9B Instruct (local)
- **Lightweight Models** (fast tools, autocomplete, low-latency tasks):
  - Phi‑3 Mini (local)
  - Qwen 2 1.5B/7B Instruct (local)
- **Vision / Multimodal (optional)**:
  - LLaVA or InternVL (local) for screen understanding and screenshot analysis.

### 1.3 ENSEMBLE Model Set (All Free)

ENSEMBLE (multi-model debate) must only use **free models**:

- Llama 3 8B Instruct
- Mistral 7B Instruct
- Mixtral 8x7B Instruct (optional)
- Gemma 2 9B Instruct
- Qwen 2 7B Instruct

The judge model can be any of the above; start with Llama 3 8B Instruct.

**AI Note:** If you are an AI selecting models, **never introduce paid APIs** unless a human explicitly configures them in a separate, clearly marked optional config file (e.g., `config.paid.yaml`). Default config must remain free-only.

---

## 2. Global Architecture

- **NEXUS**: Central orchestrator that routes tasks to specialized agents.
- Agents (each one a module/package):
  - `ATLAS` — File system agent.
  - `LOGOS` — Code & logic agent.
  - `ECHO` — Calendar & meetings.
  - `MNEME` — Long-term memory.
  - `HERMES` — Browser automation.
  - `IRIS` — Research & knowledge.
  - `AEGIS` — System monitor & OS control.
  - `DIRECTOR` — Workflow engine.
  - `PHANTOM` — Background autopilot.
  - `ENSEMBLE` — Multi-model debate.
  - `ORACLE_DEEP` — Causal reasoning.
  - `LYRA` — Voice I/O.
  - `NEXUS_UI` — Frontend.
  - `CORTEX` — Infinite context.
- **Tools**: Python functions exposed with schemas for tool-calling.
- **Memory**: ChromaDB + SQLite.
- **Runtime**: Python, FastAPI backend, optional React frontend.

**AI Note:** Maintain a clear folder structure (see Phase 0). When adding new modules, always add an index/registry entry so NEXUS can discover and call them.

---

## Phase 0 — Foundation & Project Scaffold

**Status:** DONE — scaffold, core runtime, tests, and install artifacts implemented.

### Objective

Set up the base repository, environment, configuration system, logging, and a minimal agent loop that can call one or two test tools using a free local model.

### Dependencies

- Python 3.10+ environment.
- Git installed.
- At least one local model runtime (e.g., Ollama) installed and verified.

### Repository Structure

Suggested monorepo layout:

- `aura/`
  - `core/` — NEXUS orchestrator, LLM router, tool framework.
  - `agents/` — subfolders per agent (atlas, logos, echo, ...).
  - `tools/` — OS, file, calendar, browser tools.
  - `memory/` — MNEME implementation (ChromaDB + SQLite).
  - `browser/` — HERMES (Playwright scripts, helpers).
  - `ui/` — NEXUS UI frontend.
  - `api/` — FastAPI app, WebSocket endpoints.
  - `config/` — YAML/JSON configs.
  - `tests/` — pytest-based tests.

### Core Components

- `core/config.py` — loads global configuration from `config/config.yaml`.
- `core/logging.py` — JSON logging wrapper.
- `core/llm_router.py` — routes prompts to configured free models.
- `core/tools.py` — tool registration and schema management.
- `core/agent_loop.py` — ReAct loop implementation.

### Tasks Checklist

- [x] Initialize git repo and base folder structure.
- [x] Create `config/config.yaml` with:
  - [x] model choices (free-only),
  - [x] paths (data, logs, memory),
  - [x] feature flags.
- [x] Implement JSON logger with log levels and component tags.
- [x] Implement minimal `llm_router.py` supporting one free local model.
- [x] Implement base tool registry with:
  - [x] tool metadata (name, description, schema),
  - [x] registration decorator,
  - [x] listing and lookup.
- [x] Implement a minimal ReAct loop that:
  - [x] takes a user message,
  - [x] selects a tool,
  - [x] executes tool,
  - [x] returns final answer.
- [x] Add basic pytest tests for config loading, logging, tool registration.

### AI Notes

- When implementing the router, default to **one local model** (e.g., Llama 3 8B via Ollama) with a simple JSON tool-calling format.
- Keep this phase simple; the goal is to prove end-to-end flow, not performance.

---

## Phase 1 — ATLAS (File System Agent)

**Status:** DONE — ATLAS file tools, models, registry integration, and tests implemented.

### Objective

Provide robust, safe file system capabilities: search, read, write, move, delete, open, and watch.

### Dependencies

- Phase 0 core and tool framework.

### Interfaces

Module: `agents/atlas/`

Key functions (tools):

- `search_files(query, root_path, mode) -> List[FileMatch]`
- `read_file(path, max_bytes=None) -> FileContent`
- `write_file(path, content, mode) -> WriteResult`
- `move_file(src, dst) -> OperationResult`
- `delete_file(path) -> OperationResult`
- `open_file(path) -> OperationResult`
- `list_directory(path, filters) -> List[FileEntry]`
- `compress_folder(path, archive_path) -> OperationResult`
- `extract_archive(path, dst) -> OperationResult`

Each tool must:

- Declare a JSON schema for arguments.
- Be idempotent where possible.
- Respect permission tiers:
  - Read/list = Tier 1.
  - Write/move/copy = Tier 2.
  - Delete = Tier 3.

### Tasks Checklist

- [x] Design `FileMatch`, `FileContent`, `FileEntry` data models.
- [x] Implement keyword + extension filter search.
- [x] Integrate optional semantic search layer (e.g., local embedding model + Chroma index over filenames/paths).
- [x] Implement safe path handling (no directory traversal outside allowed roots).
- [x] Implement watch mechanism using `watchdog` for folder changes.
- [x] Add tests for each tool, including permission checks.

### AI Notes

- Always validate paths against an allowed root directory list before performing operations.
- Log every destructive action (delete/move) with timestamp and user confirmation.

---

## Phase 2 — LOGOS (Code & Logic Agent)

**Status:** DONE — LOGOS code execution, debugging, patching, linting, and git helpers implemented.

### Objective

Enable AURA to generate, run, debug, and refactor code across supported languages, using only free tools.

### Dependencies

- Phase 0 (core).
- Phase 1 (ATLAS) for file operations.

### Interfaces

Module: `agents/logos/`

Key tools:

- `run_code(code, language, context_dir) -> RunResult`
- `debug_code(code_or_path, error_message) -> SuggestedFix`
- `explain_code(path_or_snippet, mode) -> Explanation`
- `generate_code(description, language, context_files) -> CodePatch`
- `apply_code_patch(patch, target_path) -> OperationResult`
- `run_tests(test_command, context_dir) -> TestResult`
- `git_status(repo_path) -> StatusSummary`
- `git_diff(repo_path) -> DiffSummary`
- `git_commit(repo_path, message) -> OperationResult`

### Tasks Checklist

- [x] Implement sandboxed Python execution (e.g., subprocess with resource limits).
- [x] Add language routing (Python, JS, Bash at minimum).
- [x] Implement diff-based code writes instead of overwriting whole files.
- [x] Integrate with git if repo detected in `context_dir`.
- [x] Add code style enforcement (ruff/black for Python) via tools.

### AI Notes

- Prefer **patch-based edits**: read original file, generate diff, apply diff.
- Never run untrusted code without sandboxing and resource/time limits.

---

## Phase 3 — ECHO (Calendar & Meeting Agent)

**Status:** DONE — ECHO offline calendar, reminders, email drafts, and notification plumbing implemented.

### Objective

Manage calendar events, reminders, and meeting automation using free APIs.

### Dependencies

- Phase 0 (core).

### Interfaces

Module: `agents/echo/`

Tools:

- `list_meetings(date_range) -> List[Event]`
- `create_meeting(title, time, attendees, platform, description) -> Event`
- `update_meeting(event_id, changes) -> Event`
- `cancel_meeting(event_id) -> OperationResult`
- `set_reminder(text, time, repeat) -> Reminder`
- `join_meeting(link) -> OperationResult`

### Tasks Checklist

- [x] Implement Google Calendar integration (OAuth) with local token storage.
- [x] Optionally implement Microsoft Graph integration.
- [x] Implement OS notification reminders (Windows, Linux, Mac).
- [x] Implement mapping from natural language time to concrete timestamps.

### AI Notes

- Always confirm time zones explicitly when creating events.
- Treat email addresses and tokens as sensitive; never log them in plain text.

---

## Regression Fixes

- **Phase 0:** Added lazy builtin tool loading in `core/tools.py` so a fresh process sees the ATLAS, LOGOS, and ECHO tools without manual imports.
- **Phase 0:** Normalized platform helpers in `core/platform.py` to expose `detect_os`, `open_file`, and `send_notification` while keeping compatibility aliases for earlier code paths.
- **Phase 1-3 compatibility:** Kept `open_path` and `notify_user` aliases so existing tests and older call sites continue to work after the platform abstraction cleanup.
- **Phase 4:** Broke the Mneme/ECHO circular import by making ECHO load `save_memory` lazily inside `set_reminder()`.
- **Phase 5:** Added synchronous event publication support to `EventBus` so HERMES actions can be observed immediately from tests and replay consumers.
- **Phase 6:** Fixed IRIS cache lookups to match exact `search:{query}` keys so cached search results are reused correctly.
- **Phase 7:** Cleaned AEGIS imports and audit logging paths after the new system-control tests exposed unused dependencies.
- **Phase 8:** Fixed workflow serialization and pause/resume races so paused workflows persist correctly without deadlocking.
- **Phase 9:** Added deterministic Phantom test coverage for watch changes, briefing generation, recovery, and loop execution.

## Phase 4 — MNEME (Memory Agent)

**Status:** DONE — MNEME persistent memory, recall, consolidation, and background extraction implemented.

### Objective

Provide persistent long-term memory across sessions using only local/free storage.

### Dependencies

- Phase 0 (core).

### Architecture

- Vector store: ChromaDB (local persistent mode).
- Relational store: SQLite for structured facts.

### Interfaces

Module: `memory/`

Tools:

- `save_memory(key, value, category, tags) -> MemoryRecord`
- `recall_memory(query, top_k, category_filter) -> List[MemoryRecord]`
- `update_memory(id, new_value) -> MemoryRecord`
- `delete_memory(id) -> OperationResult`
- `consolidate_memory() -> SummaryReport`

### Tasks Checklist

- [x] Define memory schema (categories, tags, timestamps, source).
- [x] Implement embedding generation using a free local embedding model.
- [x] Implement recall with cosine similarity and scoring.
- [x] Implement automatic memory creation from conversations (opt-in).
- [x] Add tools to inspect and edit memories via UI.

### AI Notes

- Only persist information that will be genuinely useful later.
- Do not store secrets (passwords, raw tokens) in MNEME; use OS keychain instead.

---

## Phase 5 — HERMES (Browser Agent)

**Status:** DONE — HERMES browser automation, extraction, file transfer, and safety checks implemented.

### Objective

Allow AURA to operate a browser like a human: click, type, scroll, upload/download, and extract data.

### Dependencies

- Phase 0 (core).
- Phase 1 (ATLAS) for file paths.

### Stack

- Playwright (Python bindings) in headed/headless modes.

### Interfaces

Module: `browser/hermes/`

Tools:

- `open_url(url, check_malicious=True) -> PageHandle`
- `click(selector_or_description) -> OperationResult`
- `type_text(selector_or_description, text) -> OperationResult`
- `scroll(direction, amount) -> OperationResult`
- `extract_data(schema) -> StructuredData`
- `download_file(target, save_path) -> OperationResult`
- `upload_file(input_selector, file_path) -> OperationResult`
- `take_screenshot(region=None) -> ImagePath`

### Tasks Checklist

- [x] Initialize Playwright context with persistent profile.
- [x] Implement simple selector + text-based element targeting.
- [x] Implement optional URL safety check (e.g., free VirusTotal tier if within free limits).
- [x] Implement robust error handling and timeouts.
- [x] Log all actions for DIRECTOR replay.

### AI Notes

- For forms received from trusted sources (e.g., professor), URL safety checks can be skipped or logged as informational.
- Avoid infinite click loops; set sane limits per workflow.

---

## Phase 6 — IRIS (Research & Knowledge Agent)

**Status:** DONE — IRIS search, fetch, summarization, fact-checking, and academic lookup implemented.

### Objective

Provide deep research capabilities across the open web and scientific sources using free APIs/search.

### Dependencies

- Phase 0 (core).

### Interfaces

Module: `agents/iris/`

Tools:

- `web_search(query, num_results, date_filter) -> List[SearchResult]`
- `fetch_url(url) -> PageContent`
- `search_academic(query, source) -> List[Paper]`
- `summarize_content(content, style, length) -> Summary`
- `compare_sources(sources, question) -> ComparativeSummary`
- `fact_check(claim) -> FactCheckReport`

### Tasks Checklist

- [x] Integrate a free web search API or meta-search on top of standard engines within ToS.
- [x] Implement HTML parsing and main-content extraction.
- [x] Implement citation extraction and formatting utilities.
- [x] Implement multi-hop research loop (query → read → refine → repeat).

### AI Notes

- Always cross-check important claims with multiple sources.
- Track URLs and timestamps for every factual conclusion.

---

## Phase 7 — AEGIS (System Monitor & Control Agent)

**Status:** DONE — AEGIS system metrics, process control, shell execution, clipboard, screenshots, networking, and monitors implemented.

### Objective

Monitor and control system resources and OS-level actions safely.

### Dependencies

- Phase 0.

### Interfaces

Module: `agents/aegis/`

Tools:

- `get_system_info() -> SystemSnapshot`
- `list_processes() -> List[ProcessInfo]`
- `kill_process(name_or_pid) -> OperationResult`
- `run_shell_command(cmd) -> CommandResult`
- `open_application(name) -> OperationResult`
- `clipboard_read() -> ClipboardContent`
- `clipboard_write(content) -> OperationResult`
- `take_screenshot() -> ImagePath`
- `get_network_info() -> NetworkSnapshot`

### Tasks Checklist

- [x] Implement system info gathering (psutil or equivalent).
- [x] Implement cross-platform app launching.
- [x] Implement safe shell command execution with Tier 3 gate.
- [x] Implement per-action logging with user ID and timestamp.

### AI Notes

- Treat `run_shell_command` and `kill_process` as **dangerous**; always confirm with user.

---

## Phase 8 — DIRECTOR (Workflow Engine)

**Status:** DONE — DIRECTOR workflow planning, execution, persistence, approvals, retries, and replay implemented.

### Objective

Translate high-level human instructions into executable workflows (DAGs), execute them, and provide live replay with pause/resume.

### Dependencies

- Phase 0 (core).
- Phases 1, 3, 5, 7 at minimum for meaningful workflows.

### Architecture

- Workflow: graph of **steps**; each step = tool call + parameters + success criteria.
- Execution engine: walks the graph, handles retries, errors, and approvals.
- State persistence: store workflow state in SQLite/JSON so it can be resumed.

### Interfaces

Module: `agents/director/`

Tools/functions:

- `plan_workflow(natural_language_task, context) -> WorkflowPlan`
- `execute_workflow(workflow_id) -> ExecutionReport`
- `pause_workflow(workflow_id) -> OperationResult`
- `resume_workflow(workflow_id) -> OperationResult`
- `get_workflow_status(workflow_id) -> WorkflowStatus`

### Tasks Checklist

- [x] Define workflow schema: steps, edges, metadata.
- [x] Implement planner using NEXUS + free reasoning model.
- [x] Implement executor with:
   - [x] retries,
   - [x] timeouts,
   - [x] approval hooks.
- [x] Implement event log suitable for replay (UI and textual).
- [x] Implement example workflow: **teacher assignment flow** (PPTX + Google Form submission).

### AI Notes

- Prefer many small, simple steps over a few giant ones.
- Mark any ambiguous step as requiring human approval.

---

## Phase 9 — PHANTOM (Background Autopilot)

**Status:** DONE — PHANTOM scheduler, watches, briefing generation, pause/resume, and recovery hooks implemented.

### Objective

Provide always-on background automation for life and work: schedules, portals, repos, and feeds.

### Dependencies

- Phases 1, 3, 4, 5, 6, 7, 8.

### Responsibilities

- Academic autopilot: watch portals for new assignments; create tasks and time blocks.
- GitHub watcher: detect important repo events.
- HF/Kaggle watcher: detect new models/competitions.
- Daily briefings: morning summary of tasks, meetings, and relevant news.

### Interfaces

Module: `agents/phantom/`

Tools/services:

- `run_scheduled_tasks() -> Summary`
- `generate_daily_briefing() -> Briefing`
- `register_watch(target, type, handler) -> WatchId`
- `disable_watch(watch_id) -> OperationResult`

### Tasks Checklist

- [x] Implement simple scheduler (cron-like) for PHANTOM.
- [x] Implement portal watcher for at least one target (e.g., college portal or LMS) using HERMES.
- [x] Implement daily briefing generator using MNEME + IRIS.
- [x] Implement toggles to pause all PHANTOM activity.

### AI Notes

- All PHANTOM actions should be **reviewable**; keep a clear log.
- Never submit anything on behalf of the user without DIRECTOR-like explicit instructions or templates.

---

## Phase 10 — ENSEMBLE (Multi-Model Debate Engine)

**Status:** NOT_STARTED

### Objective

Increase reliability by using multiple **free** models to debate and synthesize answers.

### Dependencies

- Phase 0 (LLM router).

### Interfaces

Module: `agents/ensemble/`

Tools:

- `ensemble_answer(task, models, importance_level) -> EnsembleResult`

### Behavior

- For high-importance tasks (configurable), route prompt to 3–5 free models.
- Collect responses; analyze agreements/disagreements.
- Synthesize final answer; attach confidence score.
- Optionally return the raw per-model outputs for transparency.

### Tasks Checklist

- [ ] Define importance levels and thresholds.
- [ ] Implement parallel model invocation using the router.
- [ ] Implement judge component (can be one of the same models) to synthesize.
- [ ] Integrate confidence scoring.

### AI Notes

- Never add paid models into the ENSEMBLE configuration by default.
- If no diversity of models is available locally, ENSEMBLE can gracefully degrade to a single-model path.

---

## Phase 11 — ORACLE DEEP (Causal Reasoning Engine)

**Status:** NOT_STARTED

### Objective

Provide transparent causal reasoning with uncertainty estimates and counter-arguments.

### Dependencies

- Phase 0.
- Phase 6 (IRIS) for evidence gathering.

### Interfaces

Module: `agents/oracle_deep/`

Tools:

- `analyze_decision(question, context) -> ReasoningReport`
- `what_if_scenario(change_description, base_state) -> ScenarioAnalysis`

### Behavior

- Generate a reasoning chain (steps, assumptions, evidence).
- Attach confidence levels to key claims.
- Generate the strongest counter-argument.
- Link conclusions back to specific evidence items (URLs, papers, data).

### Tasks Checklist

- [ ] Define ReasoningReport schema.
- [ ] Implement chain-of-thought style internal reasoning (not exposed fully to user by default).
- [ ] Implement uncertainty quantification (low/medium/high + reason).
- [ ] Implement counter-argument generation.

### AI Notes

- Be explicit about assumptions; list them clearly.
- Mark any conclusion as low confidence if evidence is weak or conflicting.

---

## Phase 12 — LYRA (Voice Interface)

**Status:** NOT_STARTED

### Objective

Enable full voice I/O with local/free components.

### Dependencies

- Phase 0.

### Stack

- STT: Whisper local (e.g., via `whisper.cpp` or faster-whisper).
- TTS: Coqui TTS or another free local TTS.

### Interfaces

Module: `agents/lyra/`

Tools/services:

- `listen_and_transcribe() -> Text`
- `speak(text) -> OperationResult`
- `set_wake_word(phrase) -> OperationResult`
- `start_continuous_listening() -> OperationResult`

### Tasks Checklist

- [ ] Integrate Whisper for STT (local model files).
- [ ] Integrate free local TTS engine.
- [ ] Implement wake word detection using a free library (e.g., Porcupine if license allows, or alternative).
- [ ] Handle interruptions (stop speaking on user input).

### AI Notes

- Audio processing must run efficiently; avoid blocking the main agent loop.

---

## Phase 13 — NEXUS UI (Frontend Interface)

**Status:** NOT_STARTED

### Objective

Provide a clean, fast UI to interact with AURA: chat, workflows, logs, memory, and settings.

### Dependencies

- Phase 0 (API server).
- Several agents for meaningful data.

### Stack

- Backend: FastAPI.
- Frontend: React + Tailwind (or simple HTML/JS).

### Features

- Chat interface with markdown rendering and code blocks.
- Workflow viewer for DIRECTOR (steps, status, replay timeline).
- PHANTOM dashboard (scheduled tasks, briefings).
- MNEME explorer (search, inspect, edit memories).
- System monitor widget from AEGIS.
- Settings page for models, permissions, feature toggles.

### Tasks Checklist

- [ ] Implement WebSocket endpoint for streaming tokens and events.
- [ ] Build chat UI with message history.
- [ ] Build workflow status and replay components.
- [ ] Build simple memory browser.
- [ ] Add dark/light mode toggle.

### AI Notes

- Do not hardcode backend URLs; read from config.

---

## Phase 14 — CORTEX (Infinite Context Engine)

**Status:** NOT_STARTED

### Objective

Allow AURA to handle inputs far larger than any single model context, by chunking, parallel processing, and refinement.

### Dependencies

- Phase 0.
- Phase 4 (MNEME) for storage.

### Components

- **SHARD** — intelligent chunking with semantic overlap.
- **RELAY** — chain-of-agents state passing.
- **SWARM** — parallel processing of chunks.
- **ANCHOR** — global always-present context injection.
- **FORGE** — coarse-to-fine refinement.
- **VERDICT** — anti-hallucination checking against source chunks.

### Interfaces

Module: `agents/cortex/`

Tools:

- `analyze_large_corpus(documents, task) -> Result`
- `summarize_large_document(path, style, length) -> Summary`

### Tasks Checklist

- [ ] Implement SHARD: semantic text splitter with overlap.
- [ ] Implement SWARM: process shards in parallel with selected free models.
- [ ] Implement FORGE: second-pass refinement using shard outputs.
- [ ] Implement VERDICT: verify claims by checking back against original shards.

### AI Notes

- Never trust a final answer that contradicts the source shards.

---

## Phase 15 — Security, Privacy & Packaging

**Status:** NOT_STARTED

### Objective

Make AURA safe, private, and easy to install and run locally.

### Dependencies

- Most earlier phases.

### Responsibilities

- Secure storage of secrets (OS keychain, not plain files).
- Audit logging for Tier 2/3 actions.
- Sandboxed execution environments.
- Local-only mode (no network calls).
- Cross-platform install and auto-update checks.

### Tasks Checklist

- [ ] Integrate OS keychain API (Windows Credential Manager, macOS Keychain, Linux keyring).
- [ ] Implement per-action audit logs for destructive operations.
- [ ] Implement "offline mode" flag that disables all external HTTP calls.
- [ ] Provide a one-command installer (e.g., script or bundled binary via PyInstaller/Nuitka).

### AI Notes

- When in offline mode, gracefully degrade features that require the internet.

---

## 3. Progress Tracking and Usage by AI

1. Before doing anything, an AI agent must:
   - Read this document fully.
   - Identify the current `Status` for each phase.
   - List all unchecked tasks in the **Tasks Checklist** sections.
2. Pick a phase with `Status: NOT_STARTED` or `IN_PROGRESS` and tasks that match its capabilities.
3. For each completed task:
   - Update the checklist from `[ ]` to `[x]`.
   - If a phase is fully complete, update `Status` to `DONE` and briefly note what was implemented.
4. Never silently change the **requirements**; only mark actual progress.
5. Humans can review the git diff of this file to see exactly what the AI has done.

This playbook is the single source of truth for AURA's implementation state. EOF
