"""Stage 4: the CLI is a renderer over pipeline events. --events prints raw NDJSON and nothing else (C-3)."""
import argparse, asyncio, getpass, json, sys
from dotenv import load_dotenv
load_dotenv()
from support import health, telemetry
from support.agent import login, open_session
from support.pipeline import run_turn


def render(e: dict) -> list[str]:
    """Two parts per step: a status line, then indented detail lines."""
    t = e["type"]
    if t == "trace":
        return [f"[trace] {e['turn_id']}", f"    {e['url']}"]
    if t == "step":
        lines = [f"[{e['key']}] {e['status']} · {e['ms']} ms · {e['span']}", f"    {e['detail']}"]
        for m in e.get("memories", []):
            lines.append(f"    memory {m['score']:.2f} {'inserted' if m['inserted'] else 'skipped (' + m['reason'] + ')'}: {m['memory'][:80]}")
        return lines
    if t == "llm":
        return [f"[llm] {e['decision']} · {e['ms']} ms", f"    {e['model']} · {e['tokens_in']} in / {e['tokens_out']} out"]
    if t == "tool_call":
        args = ", ".join(f"{k}={v}" for k, v in e["args"].items())
        return [f"[tool] {e['name']}({args})", f"    {e['info']['kind']} · {e['info']['access']} · {e['info']['statement']}"]
    if t == "tool_result":
        return [f"[tool] {e['name']} -> {'ok' if e['ok'] else 'FAILED'} · {e['ms']} ms", f"    {json.dumps(e['result'], default=str)[:300]}"]
    if t == "final":
        return [f"Agent: {e['response']}", f"    done: {e['terminated']} · {e['wall_clock_ms']} ms · {e['tokens']['in']} in / {e['tokens']['out']} out"]
    if t == "error":
        return [f"[{e['step']}] ERROR {e['status']}: {e['error']}"]
    return []   # "stage" starts are shown by their step line


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", help="scripted mode: skip the password prompt (local only)")
    ap.add_argument("--events", action="store_true", help="print raw NDJSON events only")
    a = ap.parse_args()
    out = sys.stderr if a.events else sys.stdout   # --events: stdout carries events only
    down = [k for k, v in (await health.check()).items() if v != "ok"]
    if down:   # C-4: refuse to start, naming what is missing
        return print(f"Cannot start: {', '.join(down)} not reachable. Run ./run.sh up", file=sys.stderr)
    telemetry.setup()   # before any agent is built
    email = a.user or input("Email: ").strip()
    user = await login(email) if a.user else await login(email, getpass.getpass("Password: "))
    if not user:
        return print("Invalid email or password.", file=out)
    client, runner, session = await open_session(user["email"])
    print(f"Hi {user['full_name']}. Type quit to leave.", file=out)
    try:
        while True:
            try:
                line = (input("You: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n") or None)
            except EOFError:
                break
            if line is None or line.strip().lower() in {"quit", "exit", "q"}:
                break
            if not line.strip():
                continue
            async for e in run_turn(runner, session, user["email"], line):
                if a.events:
                    print(json.dumps(e, default=str), flush=True)
                else:
                    print("\n".join(render(e)), flush=True)
    finally:
        await client.close()

asyncio.run(main())
