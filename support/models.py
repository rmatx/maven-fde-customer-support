"""One switch for the model provider. LLM_PROVIDER=gemini (default) or openrouter.
OpenRouter free models are reached through ADK's LiteLlm wrapper. Set OPENROUTER_API_KEY in .env.
OPENROUTER_MODEL is the support agent; OPENROUTER_GUARD_MODEL is the Judge and Guardrail."""
import os

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_AGENT = os.getenv("MODEL", "gemini-3.8-flash")
GEMINI_GUARD = "gemini-3.5-flash-lite"
OR_AGENT = os.getenv("OPENROUTER_MODEL", "qwen/qwen3.8-27b:free")
OR_GUARD = os.getenv("OPENROUTER_GUARD_MODEL", "google/gemma-4-26b-a4b-it:free")


def _or(model_id: str):
    from google.adk.models.lite_llm import LiteLlm
    extra = {"extra_body": {"reasoning": {"enabled": False}}} if model_id.endswith(":free") else {}   # free reasoning models
    # otherwise think out loud into the answer; paid Gemini endpoints refuse the setting ("reasoning is mandatory")
    return LiteLlm(model=f"openrouter/{model_id}", num_retries=4, **extra)   # retries 429/5xx with backoff, never turns one into "allow"


def agent_model():
    return _or(OR_AGENT) if PROVIDER == "openrouter" else GEMINI_AGENT


def guard_model(env_name: str):
    if PROVIDER == "openrouter":
        return _or(os.getenv(env_name, OR_GUARD))
    return os.getenv(env_name, GEMINI_GUARD)


def label() -> str:
    return f"openrouter/{OR_AGENT}" if PROVIDER == "openrouter" else GEMINI_AGENT
