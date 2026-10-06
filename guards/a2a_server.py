"""A minimal A2A server: an agent card plus a JSON-RPC `message/send` endpoint (J-1, K-1).
Wire format: the request is a JSON-RPC 2.0 call with params.message.parts[].text; the result is a Message
whose single text part is a JSON string carrying the structured verdict."""
import json, uuid
from fastapi import FastAPI, Request


def make_app(name: str, description: str, port: int, skill: str, handler) -> FastAPI:
    app = FastAPI(title=name)
    card = {
        "name": name, "description": description, "url": f"http://127.0.0.1:{port}/", "version": "1.0.0",
        "protocolVersion": "0.3.0", "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["application/json"],
        "skills": [{"id": skill, "name": skill, "description": description, "tags": [skill]}],
    }

    @app.get("/.well-known/agent-card.json")
    @app.get("/.well-known/agent.json")
    def agent_card():
        return card

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/")
    async def rpc(request: Request):
        body = await request.json()
        rid = body.get("id")
        if body.get("method") not in ("message/send", "tasks/send"):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}
        try:
            parts = body["params"]["message"]["parts"]
            text = next(p["text"] for p in parts if p.get("kind", "text") == "text")
            payload = await handler(text)
        except Exception as e:   # surface as a JSON-RPC error so the caller fails loud
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}}
        msg = {"kind": "message", "role": "agent", "messageId": uuid.uuid4().hex,
               "parts": [{"kind": "text", "text": json.dumps(payload)}]}
        return {"jsonrpc": "2.0", "id": rid, "result": msg}

    return app
