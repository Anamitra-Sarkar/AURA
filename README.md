---
title: AURA Agent
emoji: 🤖
colorFrom: teal
colorTo: blue
sdk: docker
app_port: 7860
pinned: true
---

# AURA — Your Personal AI Agent

Free. Open. For everyone.

[Connect AURA to your PC →](pip install aura-client)

# AURA

AURA is a free, local-first AI agent stack with multi-provider routing, tool-calling, memory, browser/system/file automation, and a FastAPI control surface.

## What is included

- `aura/` — backend runtime, agents, router, memory, UI API, and daemon
- `frontend/` — web UI scaffold for the public app
- `client/` — lightweight local companion package for PC control
- `Dockerfile` — container build for cloud deployment

## Agents

- `IRIS` — web search and research
- `ATLAS` — file system operations
- `LOGOS` — code execution and debugging
- `AEGIS` — system monitoring and process control
- `CORTEX` — long-context chunking and relay workflows
- `DIRECTOR` — workflow planning and execution
- `ECHO` — calendar and reminders
- `ENSEMBLE` — multi-model debate and synthesis
- `HERMES` — browser automation
- `LYRA` — speech I/O
- `MNEME` — memory and recall
- `MOSAIC` — multi-source synthesis
- `ORACLE DEEP` — causal reasoning
- `PHANTOM` — background automation
- `STREAM` — world-awareness feeds and digests
- `NEXUS` — top-level orchestration

## Run locally

```bash
python -m aura
```

For a single smoke test:

```bash
python aura/daemon.py --once
```

## Run with Docker

```bash
docker build -t aura .
docker run -p 7860:7860 --env-file .env aura
```

## Environment variables

- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`
- `CEREBRAS_API_KEY`
- `GEMINI_API_KEY`
- `MISTRAL_API_KEY`
- `CF_API_TOKEN`
- `CF_ACCOUNT_ID`
- `XAI_API_KEY`
- `JWT_SECRET`
- `AURA_DATA_PATH`

## Notes

- All default workflows are designed to work without paid APIs.
- Free-model routing is handled by the multi-provider router.
- The frontend and client are intentionally lightweight so they can run on free infrastructure and user machines.
