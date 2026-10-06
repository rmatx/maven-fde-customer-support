"""One fresh-session ADK call, shared by the Guardrail and the Judge (GR-3). Retries only a transient 503/429
from the model API; any other failure, and a second failure, propagates so the caller fails the turn loudly."""
import asyncio, os, uuid
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


# Retry transient 429 (rate limit) and 503 (overload) inside the Gemini client, for every agent in the system.
# This waits and retries; it never turns a failure into an "allow". After the last attempt the error propagates.
_GEMINI = os.getenv("LLM_PROVIDER", "gemini").lower() != "openrouter"
_HTTP = types.HttpOptions(retry_options=types.HttpRetryOptions(
    attempts=int(os.getenv("LLM_ATTEMPTS", "5")), initial_delay=2.0, max_delay=20.0, exp_base=2.0, http_status_codes=[429, 503])) if _GEMINI else None
_kw = {"http_options": _HTTP} if _HTTP else {}   # OpenRouter retries inside LiteLlm (num_retries) instead
RETRY = types.GenerateContentConfig(temperature=0.0, **_kw)   # support agent: no sampling variance, so one request = one tool call
GUARD = types.GenerateContentConfig(temperature=0.0, **_kw)   # guards must decide the same way twice


async def ask(agent, text: str, retries: int = 0) -> str:
    for attempt in range(retries + 1):
        sessions = InMemorySessionService()
        runner = Runner(app_name="guard", agent=agent, session_service=sessions)
        sid, uid = uuid.uuid4().hex, "guard"
        await sessions.create_session(app_name="guard", user_id=uid, session_id=sid)   # fresh per check
        try:
            out = ""
            msg = types.Content(role="user", parts=[types.Part(text=text)])
            async for ev in runner.run_async(user_id=uid, session_id=sid, new_message=msg):
                if ev.is_final_response() and ev.content and ev.content.parts:
                    out = ev.content.parts[0].text or ""
            return out
        except Exception as e:
            transient = any(code in str(e) for code in ("503", "429", "UNAVAILABLE"))
            if not transient or attempt == retries:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))
        finally:
            await sessions.delete_session(app_name="guard", user_id=uid, session_id=sid)


def last_json(raw: str, key: str) -> dict:
    """Take the last JSON object in a model reply that contains `key`. Free models sometimes think out loud before
    the answer. If no valid object with the key exists this raises, so the caller fails the turn (never "allow")."""
    import json, re
    for m in reversed(re.findall(r"\{[^{}]*\}", raw, re.S)):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        if key in d:
            return d
    raise ValueError(f"no JSON object with {key!r} in model reply: {raw[:120]!r}")
