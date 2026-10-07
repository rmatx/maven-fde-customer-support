#!/bin/bash
# Reset demo state: DB, and memories for the demo users. Run from the project root.
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
./run.sh reset >/dev/null 2>&1
MEM0_TELEMETRY=False .venv/bin/python - 2>&1 <<'E' | grep -v "PostHog\|spaCy\|fastembed"
import asyncio
from support import memory as m
async def go():
    for u in ["alice.jones@example.com","diana.prince@hero.net","bob.smith@techmail.com"]: await m.clear(u)
asyncio.run(go())
E
./run.sh up >/dev/null 2>&1
./run.sh status | tr '\n' ' '; echo
