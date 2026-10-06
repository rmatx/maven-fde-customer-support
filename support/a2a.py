"""Client for the A2A guard services (method: message/send). Any failure raises GuardError so the caller fails the
turn loudly. There is deliberately no try/except-allow anywhere on this path (R-4)."""
import json, uuid
import httpx


class GuardError(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step, self.message = step, message


async def call(step: str, url: str, text: str, timeout: float = 120.0) -> dict:
    body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
            "params": {"message": {"kind": "message", "role": "user", "messageId": uuid.uuid4().hex,
                                   "parts": [{"kind": "text", "text": text}]}}}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise GuardError(step, f"{step} service unreachable or failed: {type(e).__name__}: {e}") from e
    if "error" in data:
        raise GuardError(step, f"{step} service error: {data['error'].get('message')}")
    try:
        return json.loads(data["result"]["parts"][0]["text"])
    except Exception as e:
        raise GuardError(step, f"{step} returned an unparseable reply") from e
