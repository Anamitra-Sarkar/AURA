# AURA Repo Audit

## Summary

- Total scanned files: 153
- Implemented/real: 141
- Scaffolds: 2
- Stubs/empty: 10

## File-by-file audit

| File | Status | Notes |
|---|---:|---|
| `.gitignore` | real | looks implemented |
| `AURA_free_full_playbook.md` | real | contains pass statements |
| `Dockerfile` | real | looks implemented |
| `README.md` | real | looks implemented |
| `aura/__init__.py` | real | looks implemented |
| `aura/agents/__init__.py` | stub | empty file; empty package initializer |
| `aura/agents/aegis/__init__.py` | real | looks implemented |
| `aura/agents/aegis/models.py` | real | looks implemented |
| `aura/agents/aegis/tools.py` | real | contains pass statements |
| `aura/agents/atlas/__init__.py` | real | looks implemented |
| `aura/agents/atlas/models.py` | real | looks implemented |
| `aura/agents/atlas/tools.py` | real | contains pass statements |
| `aura/agents/cortex/__init__.py` | stub | empty package initializer |
| `aura/agents/director/__init__.py` | real | looks implemented |
| `aura/agents/director/models.py` | real | looks implemented |
| `aura/agents/director/tools.py` | real | contains pass statements |
| `aura/agents/echo/__init__.py` | real | looks implemented |
| `aura/agents/echo/models.py` | real | looks implemented |
| `aura/agents/echo/tools.py` | real | contains pass statements |
| `aura/agents/ensemble/__init__.py` | real | looks implemented |
| `aura/agents/ensemble/models.py` | real | looks implemented |
| `aura/agents/ensemble/tools.py` | real | contains pass statements |
| `aura/agents/hermes/__init__.py` | stub | empty package initializer |
| `aura/agents/iris/__init__.py` | real | looks implemented |
| `aura/agents/iris/models.py` | real | looks implemented |
| `aura/agents/iris/tools.py` | real | contains pass statements |
| `aura/agents/logos/__init__.py` | real | looks implemented |
| `aura/agents/logos/models.py` | real | contains pass statements |
| `aura/agents/logos/tools.py` | real | contains pass statements |
| `aura/agents/lyra/__init__.py` | real | looks implemented |
| `aura/agents/lyra/models.py` | real | looks implemented |
| `aura/agents/lyra/tools.py` | real | contains pass statements |
| `aura/agents/mneme/__init__.py` | stub | empty package initializer |
| `aura/agents/mosaic/__init__.py` | real | looks implemented |
| `aura/agents/mosaic/models.py` | real | looks implemented |
| `aura/agents/mosaic/tools.py` | real | contains pass statements |
| `aura/agents/oracle_deep/__init__.py` | real | looks implemented |
| `aura/agents/oracle_deep/models.py` | real | looks implemented |
| `aura/agents/oracle_deep/tools.py` | real | contains pass statements |
| `aura/agents/phantom/__init__.py` | real | looks implemented |
| `aura/agents/phantom/models.py` | real | looks implemented |
| `aura/agents/phantom/tools.py` | real | contains pass statements |
| `aura/agents/stream/__init__.py` | real | looks implemented |
| `aura/agents/stream/models.py` | real | looks implemented |
| `aura/agents/stream/tools.py` | real | contains pass statements |
| `aura/api/__init__.py` | stub | empty file; empty package initializer |
| `aura/browser/__init__.py` | real | looks implemented |
| `aura/browser/hermes/__init__.py` | real | looks implemented |
| `aura/browser/hermes/models.py` | real | looks implemented |
| `aura/browser/hermes/tools.py` | real | contains pass statements |
| `aura/config/__init__.py` | stub | empty file; empty package initializer |
| `aura/config/config.paid.yaml` | real | looks implemented |
| `aura/config/config.yaml` | real | looks implemented |
| `aura/core/__init__.py` | stub | empty file; empty package initializer |
| `aura/core/agent_loop.py` | real | contains pass statements |
| `aura/core/auth/__init__.py` | real | looks implemented |
| `aura/core/auth/manager.py` | real | contains pass statements |
| `aura/core/config.py` | real | looks implemented |
| `aura/core/event_bus.py` | real | looks implemented |
| `aura/core/hotkey.py` | real | looks implemented |
| `aura/core/ipc.py` | real | looks implemented |
| `aura/core/llm_router.py` | real | looks implemented |
| `aura/core/logging.py` | real | looks implemented |
| `aura/core/multiagent/__init__.py` | real | looks implemented |
| `aura/core/multiagent/dispatcher.py` | real | looks implemented |
| `aura/core/multiagent/mcp_server.py` | real | looks implemented |
| `aura/core/multiagent/models.py` | real | looks implemented |
| `aura/core/multiagent/orchestrator.py` | real | contains pass statements |
| `aura/core/multiagent/registry.py` | real | looks implemented |
| `aura/core/platform.py` | real | looks implemented |
| `aura/core/router/__init__.py` | real | looks implemented |
| `aura/core/router/failover.py` | real | looks implemented |
| `aura/core/router/models.py` | real | looks implemented |
| `aura/core/router/providers/__init__.py` | real | looks implemented |
| `aura/core/router/providers/_http.py` | real | looks implemented |
| `aura/core/router/providers/base.py` | real | looks implemented |
| `aura/core/router/providers/cerebras.py` | real | looks implemented |
| `aura/core/router/providers/cloudflare.py` | real | looks implemented |
| `aura/core/router/providers/gemini.py` | real | looks implemented |
| `aura/core/router/providers/groq.py` | real | looks implemented |
| `aura/core/router/providers/mistral.py` | real | looks implemented |
| `aura/core/router/providers/openrouter.py` | real | looks implemented |
| `aura/core/router/providers/xai.py` | real | looks implemented |
| `aura/core/router/quota_tracker.py` | real | contains pass statements |
| `aura/core/router/registry.py` | real | looks implemented |
| `aura/core/router/smart_router.py` | real | looks implemented |
| `aura/core/router/task_classifier.py` | real | looks implemented |
| `aura/core/tools.py` | real | looks implemented |
| `aura/core/tray.py` | real | looks implemented |
| `aura/daemon.py` | real | contains pass statements |
| `aura/install/__init__.py` | stub | empty file; empty package initializer |
| `aura/install/aura.service` | real | looks implemented |
| `aura/install/install.bat` | real | looks implemented |
| `aura/install/install.sh` | real | looks implemented |
| `aura/memory/__init__.py` | real | looks implemented |
| `aura/memory/mneme/__init__.py` | real | looks implemented |
| `aura/memory/mneme/models.py` | real | looks implemented |
| `aura/memory/mneme/tools.py` | real | contains pass statements |
| `aura/tests/__init__.py` | stub | empty file; empty package initializer |
| `aura/tests/conftest.py` | real | looks implemented |
| `aura/tests/test_aegis.py` | real | looks implemented |
| `aura/tests/test_agent_loop.py` | real | looks implemented |
| `aura/tests/test_atlas.py` | real | looks implemented |
| `aura/tests/test_branch_compression.py` | real | looks implemented |
| `aura/tests/test_config.py` | real | looks implemented |
| `aura/tests/test_core_runtime_branches.py` | real | contains pass statements |
| `aura/tests/test_daemon.py` | real | looks implemented |
| `aura/tests/test_director.py` | real | contains pass statements |
| `aura/tests/test_echo.py` | real | contains pass statements |
| `aura/tests/test_ensemble.py` | real | looks implemented |
| `aura/tests/test_event_bus.py` | real | looks implemented |
| `aura/tests/test_hermes.py` | real | looks implemented |
| `aura/tests/test_hotkey.py` | real | looks implemented |
| `aura/tests/test_ipc.py` | real | looks implemented |
| `aura/tests/test_iris.py` | real | looks implemented |
| `aura/tests/test_llm_router.py` | real | looks implemented |
| `aura/tests/test_logging.py` | real | looks implemented |
| `aura/tests/test_logos.py` | real | contains pass statements |
| `aura/tests/test_lyra.py` | real | looks implemented |
| `aura/tests/test_mneme.py` | real | looks implemented |
| `aura/tests/test_mosaic.py` | real | looks implemented |
| `aura/tests/test_multiagent.py` | real | looks implemented |
| `aura/tests/test_nexus_ui.py` | real | looks implemented |
| `aura/tests/test_oracle_deep.py` | real | looks implemented |
| `aura/tests/test_phantom.py` | real | looks implemented |
| `aura/tests/test_phase10_coverage_boost.py` | real | looks implemented |
| `aura/tests/test_platform.py` | real | looks implemented |
| `aura/tests/test_router.py` | real | looks implemented |
| `aura/tests/test_runtime_branches.py` | real | looks implemented |
| `aura/tests/test_stream.py` | real | looks implemented |
| `aura/tests/test_tools.py` | real | looks implemented |
| `aura/tests/test_tray.py` | real | looks implemented |
| `aura/ui/__init__.py` | real | looks implemented |
| `aura/ui/server.py` | real | contains pass statements |
| `client/README.md` | real | looks implemented |
| `client/aura_client/__init__.py` | real | looks implemented |
| `client/aura_client/connection.py` | real | looks implemented |
| `client/aura_client/executor.py` | real | looks implemented |
| `client/aura_client/main.py` | real | looks implemented |
| `client/aura_client/security.py` | real | looks implemented |
| `client/aura_client/tools/__init__.py` | stub | empty package initializer |
| `client/aura_client/tools/aegis.py` | real | looks implemented |
| `client/aura_client/tools/atlas.py` | real | looks implemented |
| `client/aura_client/tools/hermes.py` | real | looks implemented |
| `client/aura_client/tools/lyra.py` | real | looks implemented |
| `client/setup.py` | real | looks implemented |
| `daemon.py` | real | looks implemented |
| `frontend/build.js` | scaffold | looks implemented |
| `frontend/package.json` | scaffold | looks implemented |
| `pytest.ini` | real | looks implemented |
| `requirements.txt` | real | looks implemented |
| `spaces_README.md` | real | looks implemented |
| `vercel.json` | real | looks implemented |
