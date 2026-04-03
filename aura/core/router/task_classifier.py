"""Deterministic task classification for router selection."""

from __future__ import annotations

from .models import RouterDecision


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


class TaskClassifier:
    """Classify tasks without model calls."""

    def classify(self, task: str, context: str = None) -> RouterDecision:
        text = f"{task} {context or ''}".lower()
        task_tags: list[str]
        best_models: list[str]
        rationale: str
        importance = 2

        if _contains_any(text, ["code", "script", "function", "implement", "debug", "fix"]):
            task_tags = ["coding"]
            best_models = [
                "openrouter:qwen/qwen3-coder-480b-a35b:free",
                "mistral:codestral-latest",
                "openrouter:minimax/minimax-m2.5:free",
            ]
            rationale = "coding keywords detected"
        elif _contains_any(text, ["analyze", "reason", "think", "decide", "plan"]):
            task_tags = ["reasoning"]
            best_models = [
                "groq:deepseek-r1-distill-llama-70b",
                "cerebras:deepseek-r1",
                "xai:grok-4",
                "openrouter:nvidia/nemotron-3-super-120b:free",
            ]
            rationale = "reasoning keywords detected"
        elif len(task) > 50000 or (context is not None and len(context) > 100000):
            task_tags = ["long_context"]
            best_models = [
                "gemini:gemini-2.5-pro",
                "gemini:gemini-2.5-flash",
                "xai:grok-4.1-fast",
                "openrouter:qwen/qwen3.6-plus:free",
            ]
            rationale = "long context detected"
        elif _contains_any(text, ["search", "research", "find", "latest", "news"]):
            task_tags = ["rag"]
            best_models = [
                "groq:llama-3.3-70b-versatile",
                "openrouter:qwen/qwen3-next-80b-a3b:free",
                "openrouter:nvidia/nemotron-3-super-120b:free",
            ]
            rationale = "research keywords detected"
        elif _contains_any(text, ["translate", "multilingual", "language"]):
            task_tags = ["multilingual"]
            best_models = [
                "openrouter:zhipuai/glm-4.5-air:free",
                "groq:qwen-qwen3-32b",
                "mistral:mistral-large-latest",
            ]
            rationale = "multilingual keywords detected"
        elif importance == 1:
            task_tags = ["fast"]
            best_models = [
                "cerebras:llama-4-scout",
                "groq:llama-3.1-8b-instant",
                "cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast",
            ]
            rationale = "low importance fast path"
        else:
            task_tags = ["general"]
            best_models = [
                "groq:llama-3.3-70b-versatile",
                "openrouter:openai/gpt-oss-120b:free",
                "openrouter:nvidia/nemotron-3-super-120b:free",
                "cerebras:llama-3.3-70b",
            ]
            rationale = "general fallback"

        fallback_chain = list(dict.fromkeys(best_models + ["openrouter:openrouter/auto"]))
        selected_provider, selected_model = best_models[0].split(":", 1)
        return RouterDecision(
            task=task,
            importance=importance,
            selected_provider=selected_provider,
            selected_model=selected_model,
            fallback_chain=fallback_chain,
            rationale=rationale,
            task_tags=task_tags,
        )
