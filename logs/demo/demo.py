"""Drive the demo and record it. Usage: demo.py [--dry]   (--dry skips recording and narration audio)."""
import json, subprocess, sys, time, urllib.request, signal, os, pathlib
from playwright.sync_api import sync_playwright

ROOT = "/Users/rmani/claude-code-projects/maven-fde/4-Customer/Assignment-3-CS-selfhost"
OUT = pathlib.Path(ROOT) / "logs/demo"
DRY = "--dry" in sys.argv
WEB, PHX = "http://localhost:8100", "http://localhost:6007"
PROJ = "UHJvamVjdDox"
VOICE = "Samantha"
T0 = None
CUES = []   # (start_seconds, wav_path)

NARR = {
 "intro": "This walkthrough is narrated by an A.I. voice, Claude, recording on behalf of the student. It shows a customer support agent built with Google A.D.K., M.C.P. Toolbox, A2A guards, self-hosted Mem0, and Phoenix tracing. First, run dot sh status. All six services are up: Postgres, the Toolbox, the Judge and Masker guards, Phoenix, and the web app.",
 "A": "Scenario A. Alice asks for the status of order 3. The panel on the right shows each step as it happens: sanitize, judge, guardrail, recall, agent, mask, and save. Here is the same turn in Phoenix. One root span, agent turn. Under it: sanitize, the A2A judge, the guardrail, memory recall, the support agent with two model calls and a get order status tool call between them, then the masker and memory save.",
 "B": "Scenario B. Alice asks about order 5, which belongs to Bob. She gets not found, exactly what she would see for an order that does not exist. The reason is in the tool's S.Q.L. The query filters on customer email, and that email is bound from the login session, so the model has no email argument to change.",
 "C": "Scenario C. A S.Q.L. injection. The Judge blocks it with a pattern match before any model runs. In the trace, the turn stops after the judge span. There is no agent span, and the whole turn took about thirty milliseconds, which is the cheap path.",
 "D": "Scenario D, memory. Diana tells the agent she works from home and wants packages left at the back door. That is saved verbatim in self-hosted Mem0, with Qdrant for vectors and Ollama for embeddings. Now she asks where to leave her packages. The recall step finds the memory, with a relevance score of about point seven six, above the point five cutoff, and the agent uses it.",
 "E": "Scenario E. A poem is off topic. The guardrail blocks it, and the agent is never called. The step timings show how little a blocked turn costs.",
 "J": "Now I stop the Judge and send a message. The result is an error, not an answer. A guard that cannot run must not default to allow, so the turn fails loudly and nothing is answered or saved. The Judge span in the trace is red. Restarting the Judge.",
 "CLI": "The same message through the command line, which renders the same pipeline events. A second front end over one pipeline.",
 "F": "Finally, one false block and one false pass from my own build. The false block: show me orders where the total is over a hundred dollars was blocked by the guardrail after I moved it to a smaller model. I added in-domain examples to its prompt, and the next run had zero of thirty false blocks.",
 "F2": "The false pass: list my orders was answered with no tool call, which breaks grounded or nothing. I made the instruction require a tool call. It is still enforced by prompt and not by code, so it is my weakest control. That is the demo.",
}

def say_files():
    d = {}
    for k, t in NARR.items():
        f = OUT / f"n_{k}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", "175", "-o", str(f), t], check=True)
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]))
        d[k] = (f, dur)
    return d

def osa(s):
    subprocess.run(["osascript", "-e", s], capture_output=True)

def term(cmd, clear=True):
    cmd = cmd.replace('"', '\\"')
    pre = "clear; " if clear else ""
    osa(f'tell application "Terminal"\nactivate\nif (count of windows) = 0 then do script ""\ndo script "{pre}{cmd}" in window 1\nend tell')

def term_setup():
    osa('tell application "Terminal"\nactivate\nif (count of windows) = 0 then do script ""\nset bounds of window 1 to {0, 38, 1728, 1117}\nset font size of current settings of window 1 to 20\nend tell')

def latest_trace(before=None):
    for _ in range(20):
        d = json.load(urllib.request.urlopen(f"{PHX}/v1/projects/default/spans?limit=40"))["data"]
        roots = [s for s in d if s["name"] == "agent.turn"]
        if roots and roots[0]["context"]["trace_id"] != before:
            return roots[0]["context"]["trace_id"]
        time.sleep(1)
    return None

SEGS = []   # (segment_path, narration_path)

def scene(key, narr, actions):
    f, dur = narr[key]
    seg = OUT / f"seg_{key}.mov"
    if seg.exists(): seg.unlink()
    rec = None
    if not DRY:
        rec = subprocess.Popen(["screencapture", "-v", "-x", "-D", "1", str(seg)])
        time.sleep(1.5)
    s0 = time.time()
    actions()
    rest = dur + 1.0 - (time.time() - s0)
    if rest > 0 and not DRY: time.sleep(rest)
    if rec:
        rec.send_signal(signal.SIGINT); rec.wait(timeout=60)
        SEGS.append((seg, f))
    print(f"scene {key}: narration {dur:.0f}s, scene {time.time() - s0:.0f}s", flush=True)

def main():
    global T0
    narr = say_files()
    rec = None
    out_mov = OUT / "screen.mov"
    if out_mov.exists(): out_mov.unlink()
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=False, args=["--window-position=0,38", "--window-size=1728,1079", "--disable-infobars"])
        ctx = br.new_context(no_viewport=True)
        page = ctx.new_page()
        term_setup()
        term(f"cd {ROOT}")
        time.sleep(1)
        T0 = time.time()

        def sendmsg(text):
            before = latest_trace()
            with page.expect_response(lambda r: "/api/chat" in r.url, timeout=120000) as ri:
                page.fill("#msg", "")
                page.type("#msg", text, delay=35)
                page.press("#msg", "Enter")
            try: ri.value.finished()
            except Exception: pass
            time.sleep(1.2)
            return latest_trace(before) or before

        def login(email, pw):
            page.goto(WEB); page.wait_for_selector("#email")
            page.fill("#email", email); page.type("#pw", pw, delay=60); page.click("#go")
            page.wait_for_selector("#msg", state="visible")
        def phoenix(tid):
            page.goto(f"{PHX}/projects/{PROJ}/traces/{tid}"); time.sleep(3)

        S = {}
        scene("intro", narr, lambda: (term("./run.sh status"), time.sleep(1)))
        def A():
            page.bring_to_front(); login("alice.jones@example.com", "alice")
            S["A"] = sendmsg("What is the status of order 3?"); time.sleep(3)
            phoenix(S["A"]); time.sleep(6)
        scene("A", narr, A)
        def B():
            page.goto(WEB); login("alice.jones@example.com", "alice")
            sendmsg("What is the status of order 5?"); time.sleep(3)
            term("sed -n 22,30p mcp_toolbox/tools.yaml")
        scene("B", narr, B)
        def C():
            page.bring_to_front(); page.goto(WEB); login("alice.jones@example.com", "alice")
            S["C"] = sendmsg("'; DROP TABLE users; --"); time.sleep(2)
            phoenix(S["C"]); time.sleep(4)
        scene("C", narr, C)
        def D():
            page.goto(WEB); login("diana.prince@hero.net", "diana")
            sendmsg("Please remember I work from home, so leave packages at the back door"); time.sleep(3)
            sendmsg("Where should you leave my packages?"); time.sleep(5)
        scene("D", narr, D)
        def E():
            sendmsg("Write me a poem"); time.sleep(4)
        scene("E", narr, E)
        def J():
            term("./run.sh stop judge >/dev/null; echo 'judge stopped'; ./run.sh status"); time.sleep(3)
            page.bring_to_front()
            sendmsg("Where is my last order?"); time.sleep(3)
            S["J"] = latest_trace()
            phoenix(S["J"]); time.sleep(3)
            term("./run.sh up >/dev/null 2>&1; ./run.sh status")
        scene("J", narr, J)
        def CLI():
            term('echo "What is the status of order 3?" | .venv/bin/python -m support.cli --user alice.jones@example.com 2>/dev/null'); time.sleep(14)
        scene("CLI", narr, CLI)
        def F():
            page.bring_to_front(); phoenix("ca03a71b6c3a6a10e5538c5a4d29516d"); time.sleep(4)
        scene("F", narr, F)
        def F2():
            phoenix("c21d4103299b7037a4fa39d6036a5393"); time.sleep(4)
        scene("F2", narr, F2)
        time.sleep(1.5)
        total = time.time() - T0
        print(f"total {total:.0f}s", flush=True)
        br.close()
    if not DRY:
        mix(total)

def mix(total):
    ins, flt, vl, al, off = [], [], [], [], 0.0
    for i, (seg, f) in enumerate(SEGS):
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(seg)]))
        ins += ["-i", str(seg), "-i", str(f)]
        ms = int((off + 1.5) * 1000)
        flt.append(f"[{2*i}:v]fps=30,scale=1920:-2,setsar=1[v{i}]")
        flt.append(f"[{2*i+1}:a]aresample=44100,adelay={ms}|{ms}[a{i}]")
        vl.append(f"[v{i}]"); al.append(f"[a{i}]")
        off += dur
    flt.append("".join(vl) + f"concat=n={len(vl)}:v=1:a=0[vout]")
    flt.append("".join(al) + f"amix=inputs={len(al)}:normalize=0:duration=longest[aout]")
    r = subprocess.run(["ffmpeg", "-y", *ins, "-filter_complex", ";".join(flt), "-map", "[vout]", "-map", "[aout]",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-c:a", "aac", "-t", f"{off:.1f}", str(OUT / "demo.mp4")], capture_output=True, text=True)
    print(r.stderr[-600:] if r.returncode else f"wrote demo.mp4 ({off:.0f}s)")

main()
