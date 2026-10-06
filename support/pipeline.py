"""One turn as an async generator of SPEC 7.1 events. The CLI and web only render these (P-1).
Order: sanitize -> judge -> guardrail -> recall -> agent -> mask -> save (P-2). A block ends the turn at once, and
nothing after it runs, including save (P-3). A guard that fails ends the turn with an error event (P-4, R-4)."""
import json, os, time, uuid
from contextlib import contextmanager
from pathlib import Path
from google.genai import types
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from guards.sanitizer import sanitize
from guards import guardrail
from support import memory, telemetry
from support.a2a import GuardError, call
from support.agent import MAX_TURNS_PER_SESSION, rows_from

RUNS = Path(__file__).resolve().parent.parent / "runs"
JUDGE_URL = os.getenv("JUDGE_URL", "http://127.0.0.1:10002/")
MASKER_URL = os.getenv("MASKER_URL", "http://127.0.0.1:10003/")
MAX_TOOLS, MAX_TOKENS = 6, 30_000   # T-BUD-TOOLS, T-BUD-TOKENS
ORIGINAL_WALL_S = 30                # T-BUD-WALL as declared in THRESHOLDS.md
MAX_WALL_S = int(os.getenv("WALL_BUDGET_S", ORIGINAL_WALL_S))   # override only with evidence; the eval report records it
TOOL_ACCESS = {"get-order-status": "READ", "find-customer-orders": "READ", "action-log": "WRITE"}
TOOL_SQL = {   # shown by the web UI (W-3); the real statements live in mcp_toolbox/tools.yaml
    "get-order-status": ("SELECT … FROM customer_orders WHERE order_id = $1 AND customer_email = $2", ["order_id", "customer_email"]),
    "find-customer-orders": ("SELECT … FROM customer_orders WHERE customer_email = $1 ORDER BY order_date DESC", ["customer_email"]),
    "action-log": ("INSERT INTO actions_log … SELECT … WHERE the order belongs to $1", ["user_email", "action_type", "parameters"]),
}
BLOCK_REPLY = {
    "sanitize": "Sorry, I can't process that message.",
    "judge": "Sorry, I can't help with that request.",
    "guardrail": "I can only help with your orders, deliveries, returns and account. Is there something like that I can do for you?",
}
ERROR_REPLY = "Sorry, your request could not be checked, so I haven't answered it. Please try again."


def _unwrap(response):
    r = response.get("result", response) if isinstance(response, dict) else response
    if not isinstance(r, str):
        return r
    try:
        return rows_from(r)
    except ValueError:   # a plain-text result (for example the one-action-per-turn refusal), not rows
        return r


def _decode_args(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        try:
            out[k] = json.loads(v) if isinstance(v, str) and v.lstrip()[:1] in "{[" else v
        except ValueError:
            out[k] = v
    return out


@contextmanager
def span(name: str, kind: str):
    with telemetry.tracer().start_as_current_span(name) as s:
        s.set_attribute("openinference.span.kind", kind)
        yield s


def _fail(s, err: str):
    s.set_status(Status(StatusCode.ERROR, err))
    s.record_exception(Exception(err))


async def run_turn(runner, session, user_email: str, message: str):
    turn_id, t0 = f"turn_{uuid.uuid4().hex[:12]}", time.monotonic()
    ms = lambda since: round((time.monotonic() - since) * 1000)
    st = {"steps": [], "tools": [], "llm": 0, "tin": 0, "tout": 0}

    def finish(terminated, blocked_at=None):
        wall = ms(t0)
        log = {"turn_id": turn_id, "trace_id": trace_id, "user": user_email, "message": message,
               "terminated": terminated, "blocked_at": blocked_at, "wall_clock_ms": wall,
               "tokens": {"in": st["tin"], "out": st["tout"]}, "steps": st["steps"],
               "tool_calls": st["tools"], "llm_calls": st["llm"]}
        RUNS.mkdir(exist_ok=True)
        (RUNS / f"{turn_id}.json").write_text(json.dumps(log, indent=2, default=str))   # before the terminal event
        return wall

    def record(key, status, started, **extra):
        st["steps"].append({"key": key, "status": status, "ms": ms(started), **extra})

    with span("agent.turn", "CHAIN") as root:
        root.set_attribute("input.value", message)
        root.set_attribute("user.id", user_email)
        trace_id = format(root.get_span_context().trace_id, "032x")
        yield {"type": "trace", "turn_id": turn_id, "trace_id": trace_id, "url": telemetry.trace_url(trace_id)}

        async def blocked(key, detail, started, span_name, kind_label, reply):
            record(key, "blocked", started)
            root.set_attribute("output.value", reply)
            wall = finish("blocked", key)
            return [{"type": "step", "key": key, "status": "blocked", "detail": detail, "ms": ms(started), "span": span_name, "kind": kind_label},
                    {"type": "final", "blocked": True, "blocked_at": key, "response": reply, "terminated": "blocked",
                     "wall_clock_ms": wall, "tokens": {"in": st["tin"], "out": st["tout"]}}]

        def errored(key, started, err, s):
            _fail(s, err)
            record(key, "error", started, error=err)
            root.set_attribute("output.value", ERROR_REPLY)
            _fail(root, err)
            finish("error")
            return {"type": "error", "step": key, "status": 502, "error": err, "terminated": "error", "response": ERROR_REPLY}

        # 1. sanitize (in-process, no model call)
        yield {"type": "stage", "key": "sanitize", "label": "Sanitizer"}
        t = time.monotonic()
        with span("security.sanitize", "GUARDRAIL"):
            status, detail = sanitize(message)
        if status == "blocked":
            for e in await blocked("sanitize", detail, t, "security.sanitize", "Python fn", BLOCK_REPLY["sanitize"]):
                yield e
            return
        record("sanitize", "passed", t)
        yield {"type": "step", "key": "sanitize", "status": "passed", "detail": detail, "ms": ms(t), "span": "security.sanitize", "kind": "Python fn"}

        # 2. judge (A2A service)
        yield {"type": "stage", "key": "judge", "label": "A2A Security Judge"}
        t = time.monotonic()
        with span("security.a2a_judge", "GUARDRAIL") as s:
            try:
                v = await call("judge", JUDGE_URL, message)
                if v.get("verdict") not in ("allow", "block"):
                    raise GuardError("judge", f"judge returned an unusable verdict: {v}")
            except GuardError as e:
                yield errored("judge", t, e.message, s)
                return
            s.set_attribute("judge.verdict", v["verdict"])
        if v["verdict"] == "block":
            for e in await blocked("judge", f"block: {v.get('reason', '')}", t, "security.a2a_judge", "A2A", BLOCK_REPLY["judge"]):
                yield e
            return
        record("judge", "passed", t)
        yield {"type": "step", "key": "judge", "status": "passed", "detail": f"allow: {v.get('reason', '')}", "ms": ms(t), "span": "security.a2a_judge", "kind": "A2A"}

        # 3. guardrail (in-process ADK agent)
        yield {"type": "stage", "key": "guardrail", "label": "Guardrail"}
        t = time.monotonic()
        with span("guardrail.check", "GUARDRAIL") as s:
            try:
                g = await guardrail.check(message)
            except Exception as e:
                yield errored("guardrail", t, f"Guardrail failed: {type(e).__name__}: {e}", s)
                return
        if g["decision"] == "unsafe":
            for e in await blocked("guardrail", f"unsafe: {g['reasoning']}", t, "guardrail.check", "in-process", BLOCK_REPLY["guardrail"]):
                yield e
            return
        record("guardrail", "passed", t)
        yield {"type": "step", "key": "guardrail", "status": "passed", "detail": f"safe: {g['reasoning']}", "ms": ms(t), "span": "guardrail.check", "kind": "in-process"}

        # 4. recall (a step, not a tool)
        yield {"type": "stage", "key": "recall", "label": "Memory recall (Mem0)"}
        t = time.monotonic()
        with span("memory.recall", "RETRIEVER") as s:
            try:
                cands = await memory.recall(user_email, message)
            except Exception as e:
                yield errored("recall", t, f"Memory recall failed: {type(e).__name__}: {e}", s)
                return
            s.set_attribute("input.value", message)
            for i, c in enumerate(cands):
                s.set_attribute(f"retrieval.documents.{i}.document.content", c["memory"])
                s.set_attribute(f"retrieval.documents.{i}.document.score", c["score"])
        ins = sum(c["inserted"] for c in cands)
        record("recall", "passed", t, inserted=ins, skipped=len(cands) - ins)
        yield {"type": "step", "key": "recall", "status": "passed", "detail": f"{ins} inserted, {len(cands) - ins} skipped",
               "ms": ms(t), "span": "memory.recall", "kind": "Python fn", "memories": cands}

        # 5. agent (ADK runs inside agent.turn so invoke_agent is its child)
        yield {"type": "stage", "key": "agent", "label": "Support agent"}
        if session.turns >= MAX_TURNS_PER_SESSION:
            await session.rotate()
        session.turns += 1
        t_agent = time.monotonic()
        pending, response, terminated, error, last = {}, "", "done", None, time.monotonic()
        msg = types.Content(role="user", parts=[types.Part(text=memory.with_memories(message, cands))])
        try:
            async for ev in runner.run_async(user_id=user_email, session_id=session.id, new_message=msg):
                if ev.usage_metadata and not ev.partial:
                    calls = ev.get_function_calls()
                    st["llm"] += 1
                    st["tin"] += ev.usage_metadata.prompt_token_count or 0
                    st["tout"] += ev.usage_metadata.candidates_token_count or 0
                    yield {"type": "llm", "model": getattr(runner.agent.model, "model", runner.agent.model), "decision": f"call {calls[0].name}" if calls else "final answer",
                           "tokens_in": ev.usage_metadata.prompt_token_count or 0, "tokens_out": ev.usage_metadata.candidates_token_count or 0,
                           "ms": ms(last), "span": "call_llm"}
                for i, c in enumerate(ev.get_function_calls(), start=len(st["tools"]) + len(pending) + 1):
                    pending[c.id] = (i, c.name, time.monotonic())
                    sql, params = TOOL_SQL.get(c.name, ("", []))
                    yield {"type": "tool_call", "id": i, "name": c.name, "args": _decode_args(dict(c.args or {})),
                           "info": {"kind": "MCP", "access": TOOL_ACCESS.get(c.name, "READ"), "statement": sql, "params": params,
                                    "bound": ["customer_email", "user_email"]},
                           "span": f"execute_tool {c.name}"}
                for r in ev.get_function_responses():
                    i, name, started = pending.pop(r.id)
                    st["tools"].append({"name": name, "ok": True, "ms": ms(started)})
                    yield {"type": "tool_result", "id": i, "name": name, "ok": True, "ms": ms(started), "result": _unwrap(r.response)}
                if ev.is_final_response() and ev.content and ev.content.parts:
                    response = ev.content.parts[0].text or ""
                last = time.monotonic()
                if len(st["tools"]) > MAX_TOOLS or st["tin"] + st["tout"] > MAX_TOKENS or time.monotonic() - t0 > MAX_WALL_S:
                    terminated, response = "cap", response or "Sorry, I couldn't finish that request."
                    break
        except Exception as e:
            error = f"Support agent failed: {type(e).__name__}: {e}"
        if error:
            yield errored("agent", t_agent, error, root)
            return
        record("agent", "passed", t_agent)
        yield {"type": "step", "key": "agent", "status": "passed", "detail": f"{st['llm']} model calls, {len(st['tools'])} tool calls",
               "ms": ms(t_agent), "span": "invoke_agent", "kind": "in-process"}

        # 6. mask (A2A service) — a cap-terminated reply is masked too
        yield {"type": "stage", "key": "mask", "label": "A2A Data Masker"}
        t = time.monotonic()
        with span("security.a2a_mask", "GUARDRAIL") as s:
            try:
                m = await call("mask", MASKER_URL, json.dumps({"text": response, "own_email": user_email}))
                masked, mdetail = m["masked_text"], m["detail"]
            except (GuardError, KeyError) as e:
                yield errored("mask", t, getattr(e, "message", f"masker returned an unusable reply: {e}"), s)
                return
        record("mask", "passed", t)
        yield {"type": "step", "key": "mask", "status": "passed", "detail": mdetail, "ms": ms(t), "span": "security.a2a_mask", "kind": "A2A"}

        # 7. save (only the user's message, only on a turn that was not blocked or errored)
        yield {"type": "stage", "key": "save", "label": "Memory save (Mem0)"}
        t = time.monotonic()
        with span("memory.save", "TOOL") as s:
            try:
                await memory.save(user_email, message)
            except Exception as e:
                yield errored("save", t, f"Memory save failed: {type(e).__name__}: {e}", s)
                return
        record("save", "passed", t)
        yield {"type": "step", "key": "save", "status": "passed", "detail": "saved the user's message", "ms": ms(t), "span": "memory.save", "kind": "Python fn"}

        root.set_attribute("output.value", masked)
        wall = finish(terminated)
        yield {"type": "final", "blocked": False, "blocked_at": None, "response": masked, "terminated": terminated,
               "wall_clock_ms": wall, "tokens": {"in": st["tin"], "out": st["tout"]}}
