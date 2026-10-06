"""Stage 5 (O-1..O-4): export every span to the standalone Phoenix process. Call setup() BEFORE building agents."""
import os
import httpx
from opentelemetry import trace

PHOENIX = os.getenv("PHOENIX_URL", "http://127.0.0.1:6007")
PROJECT = "default"
_project_id = None


def setup():
    from phoenix.otel import register
    from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
    provider = register(project_name=PROJECT, endpoint=f"{PHOENIX}/v1/traces", batch=False,
                        set_global_tracer_provider=True, verbose=False)
    GoogleGenAIInstrumentor().instrument(tracer_provider=provider)   # O-3: prompts, outputs, token counts (Gemini path)
    return provider


def tracer():
    return trace.get_tracer("support-desk")


def trace_url(trace_id: str) -> str:
    """Link that opens this trace in Phoenix (O-4). The project id is looked up once."""
    global _project_id
    if _project_id is None:
        try:
            rows = httpx.get(f"{PHOENIX}/v1/projects", timeout=3).json()["data"]
            _project_id = next(p["id"] for p in rows if p["name"] == PROJECT)
        except Exception:
            _project_id = PROJECT
    return f"{PHOENIX}/projects/{_project_id}/traces/{trace_id}"


def phoenix_up() -> bool:
    try:
        return httpx.get(f"{PHOENIX}/healthz", timeout=2).status_code == 200
    except Exception:
        return False
