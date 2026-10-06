"""Dependency checks for /health and the CLI preflight (C-4)."""
import asyncio, os
import httpx
from support import telemetry
from support.agent import TOOLBOX_URL

JUDGE = os.getenv("JUDGE_URL", "http://127.0.0.1:10002/").rstrip("/")
MASKER = os.getenv("MASKER_URL", "http://127.0.0.1:10003/").rstrip("/")


async def _get(c, url):
    try:
        return "ok" if (await c.get(url, timeout=3)).status_code == 200 else "down"
    except Exception:
        return "down"


async def _db(c):   # the database is reached through a Toolbox tool, like everything else
    try:
        r = await c.post(f"{TOOLBOX_URL}/api/tool/get-user/invoke", json={"email": "alice.jones@example.com"}, timeout=5)
        return "ok" if r.status_code == 200 and "Alice" in r.text else "down"
    except Exception:
        return "down"


async def _mem0():
    try:
        from support.memory import client
        await asyncio.wait_for(client().search("health", filters={"user_id": "health@probe"}, top_k=1), 8)
        return "ok"
    except Exception:
        return "down"


async def check() -> dict:
    async with httpx.AsyncClient() as c:
        toolbox, judge, masker, phoenix, db, mem0 = await asyncio.gather(
            _get(c, f"{TOOLBOX_URL}/api/toolset"), _get(c, f"{JUDGE}/health"), _get(c, f"{MASKER}/health"),
            _get(c, f"{telemetry.PHOENIX}/healthz"), _db(c), _mem0())
    return {"db": db, "toolbox": toolbox, "judge": judge, "masker": masker, "mem0": mem0, "phoenix": phoenix}
