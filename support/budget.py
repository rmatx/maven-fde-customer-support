"""Daily spend ceiling for model calls. Every ADK model call (support agent, Judge, Guardrail) goes through these two
callbacks. `after` adds the call's tokens to a ledger; `before` refuses the call once today's spend reaches the cap,
by raising, so the turn ends with an error event (fail loud) instead of silently continuing.
PRICES ARE AN ASSUMPTION: set PRICE_IN_PER_M / PRICE_OUT_PER_M (USD per million tokens) from your Google pricing page."""
import json, os, time
from datetime import date
from pathlib import Path

CAP_USD = float(os.getenv("DAILY_CAP_USD", "3.00"))
PRICE_IN = float(os.getenv("PRICE_IN_PER_M", "0.30"))     # assumed, verify
PRICE_OUT = float(os.getenv("PRICE_OUT_PER_M", "2.50"))   # assumed, verify
LEDGER = Path(__file__).resolve().parent.parent / ".run" / "spend.jsonl"
HIT = LEDGER.with_name("BUDGET_HIT")


class BudgetExceeded(Exception):
    pass


def today_spend() -> float:
    if not LEDGER.exists():
        return 0.0
    d, total = date.today().isoformat(), 0.0
    for line in LEDGER.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r["day"] == d:
            total += r["usd"]
    return total


def record(tokens_in: int, tokens_out: int, who: str):
    usd = tokens_in / 1e6 * PRICE_IN + tokens_out / 1e6 * PRICE_OUT
    LEDGER.parent.mkdir(exist_ok=True)
    with LEDGER.open("a") as f:   # one short append per call; safe across the web and Judge processes
        f.write(json.dumps({"day": date.today().isoformat(), "t": time.time(), "who": who, "in": tokens_in, "out": tokens_out, "usd": usd}) + "\n")
    if today_spend() >= CAP_USD:
        HIT.write_text(f"{date.today().isoformat()} daily cap ${CAP_USD:.2f} reached: ${today_spend():.4f}\n")


def before(callback_context, llm_request):
    spent = today_spend()
    if spent >= CAP_USD:
        raise BudgetExceeded(f"daily model spend cap ${CAP_USD:.2f} reached (${spent:.4f} today); no further model calls")
    return None


def after(callback_context, llm_response):
    u = getattr(llm_response, "usage_metadata", None)
    if u and not getattr(llm_response, "partial", False):
        record(u.prompt_token_count or 0, u.candidates_token_count or 0, getattr(callback_context, "agent_name", "?"))
    return None


def one_action_per_turn(tool, args, tool_context):
    """before_tool_callback (R-2: a rule that must hold is code, not a prompt). A second action-log call in the same
    turn is refused before it reaches the database, so a model that repeats itself cannot write duplicate rows."""
    if tool.name != "action-log":
        return None
    if tool_context.state.get("temp:action_logged"):
        return {"result": "Already recorded for this request. Do not call action-log again; just confirm to the customer."}
    tool_context.state["temp:action_logged"] = True
    return None
