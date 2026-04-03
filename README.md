---
title: AI Agent
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

AURA doesn't generate your college logo. It finds it in your template, copies it to the right position, and moves on. That's what a human would do. That's what intelligence means.

AURA is a free, local-first personal AI firm. It is not a chatbot. It is a team of specialized agents that use files, browsers, memory, calendars, the system shell, and the UI around them to do real work on your PC.

## What it does

- `IRIS` researches the web and academic sources.
- `ATLAS` reads, writes, moves, and organizes files.
- `LOGOS` runs and debugs code locally.
- `AEGIS` inspects the system, clipboard, processes, and controls the PC.
- `CORTEX` compresses long context and relays it.
- `DIRECTOR` plans multi-step workflows with dependencies.
- `ECHO` manages events, reminders, and schedules.
- `ENSEMBLE` compares multiple model outputs in parallel.
- `HERMES` automates browser and desktop UI tasks via Playwright.
- `LYRA` handles voice input and speech output.
- `MNEME` stores and recalls memory locally via ChromaDB.
- `MOSAIC` synthesizes results from many sources.
- `ORACLE DEEP` reasons about tradeoffs and uncertainty.
- `PHANTOM` runs background automation and scheduled tasks.
- `STREAM` tracks world-awareness feeds and digests.
- `NEXUS` coordinates the whole system.
- `MOBILE` controls Android devices over ADB.

## Why it stays free

All model routing goes through `aura/core/llm_router.py` and prefers free tiers from providers like Groq, OpenRouter, Cerebras, Gemini, Mistral, Cloudflare, and XAI. Most tasks do not need an LLM at all.

## Architecture

```
User (browser UI)
      │
  FastAPI backend  ←── JWT auth, SSE streaming, WebSocket
      │
  NEXUS orchestrator
      │
  ┌───┴─────────────────────────────────────┐
  │  16 specialized sub-agents              │
  │  IRIS · ATLAS · LOGOS · AEGIS · ECHO    │
  │  HERMES · MNEME · PHANTOM · DIRECTOR    │
  │  CORTEX · ENSEMBLE · MOSAIC · LYRA      │
  │  ORACLE DEEP · STREAM · MOBILE          │
  └─────────────────────────────────────────┘
      │
  Free LLM Router
  Groq · OpenRouter · Cerebras · Gemini
  Mistral · Cloudflare · XAI
```

## Install and run

```bash
git clone https://github.com/Anamitra-Sarkar/AURA.git
cd AURA
pip install -r requirements.txt
python -m aura
```

### Local PC control (Aegis/Hermes tools)

```bash
pip install -e .
python -m aura.local_client --server wss://your-hf-space.hf.space --token YOUR_JWT
```

Open the UI in your browser after the daemon starts.

### Frontend

```bash
cd frontend
npm install
npm run dev      # development
npm run build    # production build
```

## Deployment

### HuggingFace Space

The repo auto-syncs to [Arko007/AI-agent](https://huggingface.co/spaces/Arko007/AI-agent) on every push to `main` via GitHub Actions.

To set up your own:
1. Add `HF_TOKEN` (Write access) to your GitHub repo → Settings → Secrets → Actions
2. Push to `main` — the workflow handles the rest

> **Note:** Runtime data files (`*.db`, `*.sqlite3`, `chroma/`) are excluded from the HF push automatically. They are generated fresh at runtime.

### Docker

```bash
docker build -t aura .
docker run -p 8000:8000 aura
```

## Example workflows

1. **Presentation from template** — read the template, copy the logo-heavy slide, fill text in place.
2. **Study mode** — search the web, save facts to memory, generate a short briefing.
3. **Form filling** — browse to a site, fill fields, upload files, and submit.
4. **Code review** — read a repo, run tests, and patch the broken file locally.
5. **Be me** — watch the system, keep reminders, handle repetitive tasks in the background.

## Testing

```bash
python -m pytest -q        # 114 tests
python -m ruff check .     # linting
```

## Philosophy

Act, don't generate.

AURA copies what already exists. It reuses templates. It opens the real app. It edits the real file. It only calls a model when a simpler action cannot solve the task.

## Contributing

Keep changes free-only, offline-friendly, and aligned with the existing agent architecture. Prefer surgical fixes, lazy imports where needed, and tests for new behavior.

## License

See `LICENSE`.
