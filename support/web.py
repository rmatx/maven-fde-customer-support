"""Stage 9: FastAPI front end. /api/chat streams the SAME generator the CLI uses, as NDJSON (W-1, W-2)."""
import asyncio, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from guards.sanitizer import MAX_LEN
from support import health, telemetry
from support.agent import MODEL, login, open_session
from support.pipeline import run_turn

telemetry.setup()   # global tracer provider before any agent is built
app = FastAPI(title="Support desk")
SESSIONS: dict = {}   # user_id -> (toolbox client, runner, session)
LOCKS: dict = {}      # user_id -> asyncio.Lock: one turn at a time per chat session, or two turns interleave in one history


class Login(BaseModel):
    email: str
    password: str


class Logout(BaseModel):
    user_id: str


class Chat(BaseModel):
    user_id: str
    message: str


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
async def health_route():
    h = await health.check()
    body = {"status": "ok" if all(v == "ok" for v in h.values()) else "degraded", "model": MODEL, **h}
    return JSONResponse(body, status_code=200 if body["status"] == "ok" else 503)


@app.post("/api/login")
async def login_route(body: Login):
    user = await login(body.email, body.password)
    if not user:
        return JSONResponse({"error": "Invalid email or password."}, status_code=401)
    if body.email in SESSIONS:
        await SESSIONS.pop(body.email)[0].close()
    SESSIONS[body.email] = await open_session(user["email"])
    return {"user_id": user["email"], "full_name": user["full_name"], "is_premium": user["is_premium_customer"]}


@app.post("/api/logout")
async def logout_route(body: Logout):
    if body.user_id in SESSIONS:
        await SESSIONS.pop(body.user_id)[0].close()
    return {"ok": True}


@app.post("/api/chat")
async def chat(body: Chat):
    if not body.message.strip():
        return JSONResponse({"error": "message is empty"}, status_code=400)
    if body.user_id not in SESSIONS:
        return JSONResponse({"error": "Not logged in."}, status_code=401)
    if len(body.message) > MAX_LEN:
        return JSONResponse({"error": "message too long"}, status_code=413)
    _, runner, session = SESSIONS[body.user_id]

    lock = LOCKS.setdefault(body.user_id, asyncio.Lock())

    async def stream():
        async with lock:
            async for e in run_turn(runner, session, body.user_id, body.message):
                yield json.dumps(e, default=str) + "\n"
    return StreamingResponse(stream(), media_type="application/x-ndjson")
