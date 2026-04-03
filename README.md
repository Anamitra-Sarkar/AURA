AURA doesn't generate your college logo. It finds it in your template, copies it to the right position, and moves on. That's what a human would do. That's what intelligence means.

# AURA

AURA is a free, local-first personal AI firm. It is not a chatbot. It is a team of specialized agents that use files, browsers, memory, calendars, the system shell, and the UI around them to do real work on your PC.

## What it does

- `IRIS` researches the web and academic sources.
- `ATLAS` reads, writes, moves, and organizes files.
- `LOGOS` runs and debugs code locally.
- `AEGIS` inspects the system, clipboard, and processes.
- `CORTEX` compresses long context and relays it.
- `DIRECTOR` plans multi-step workflows with dependencies.
- `ECHO` manages events, reminders, and schedules.
- `ENSEMBLE` compares multiple model outputs in parallel.
- `HERMES` automates browser and desktop UI tasks.
- `LYRA` handles voice input and speech output.
- `MNEME` stores and recalls memory locally.
- `MOSAIC` synthesizes results from many sources.
- `ORACLE DEEP` reasons about tradeoffs and uncertainty.
- `PHANTOM` runs background automation and scheduled tasks.
- `STREAM` tracks world-awareness feeds and digests.
- `NEXUS` coordinates the whole system.
- `MOBILE` controls Android devices over ADB.

## Why it stays free

All model routing goes through `aura/core/llm_router.py` and prefers free tiers from providers like Groq, OpenRouter, Cerebras, Gemini, Mistral, Cloudflare, and XAI. Most tasks do not need an LLM at all.

## Install and run

```bash
git clone https://github.com/Anamitra-Sarkar/AURA.git
cd AURA
pip install -r requirements.txt
python aura/daemon.py --once
python -m aura
```

Open the UI in your browser after the daemon starts.

## Example workflows

1. Make a presentation from a template by reading the template, copying the logo-heavy slide, and filling text in place.
2. Study mode: search the web, save facts to memory, and generate a short briefing.
3. Form filling: browse to a site, fill fields, upload files, and submit.
4. Code review: read a repo, run tests, and patch the broken file locally.
5. "Be me": watch the system, keep reminders, and handle repetitive tasks in the background.

## Philosophy

Act, don't generate.

AURA copies what already exists. It reuses templates. It opens the real app. It edits the real file. It only calls a model when a simpler action cannot solve the task.

## Contributing

Keep changes free-only, offline-friendly, and aligned with the existing agent architecture. Prefer surgical fixes, lazy imports where needed, and tests for new behavior.

## License

See `LICENSE`.
