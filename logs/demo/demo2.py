"""Headless demo: Playwright records its own video (no screen capture), terminal steps are real command output on a terminal-style page.
Usage: demo2.py   (run from anywhere; writes logs/demo/demo.mp4)"""
import html, json, pathlib, re, subprocess, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = "/Users/rmani/claude-code-projects/maven-fde/4-Customer/Assignment-3-CS-selfhost"
OUT = pathlib.Path(ROOT) / "logs/demo"
WEB, PHX, PROJ, VOICE = "http://localhost:8100", "http://localhost:6007", "UHJvamVjdDox", "Samantha"
src = open(OUT / "demo.py").read()
exec(src[src.index("NARR = {"):src.index("def say_files")])   # reuse the narration text
W, H = 1440, 810
CUES = []

def narration():
    d = {}
    for k, t in NARR.items():
        f = OUT / f"n_{k}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", "175", "-o", str(f), t], check=True)
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]))
        d[k] = (f, dur)
    return d

def run(cmd):
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=120)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr).strip()

def term_page(page, cmds):
    body = ""
    for c in cmds:
        shown = c[1] if isinstance(c, tuple) else c
        real = c[0] if isinstance(c, tuple) else c
        body += f'<div class="p">$ {html.escape(shown)}</div><div class="o">{html.escape(run(real))}</div>'
    page.set_content(f"""<body style="margin:0;background:#1e1e1e;color:#d4d4d4;font:22px/1.45 Menlo,monospace;padding:28px">
<style>.p{{color:#7ee787;margin-top:14px}}.o{{white-space:pre-wrap}}</style>{body}</body>""")

def latest_trace(before=None):
    for _ in range(20):
        d = json.load(urllib.request.urlopen(f"{PHX}/v1/projects/default/spans?limit=40"))["data"]
        roots = [s for s in d if s["name"] == "agent.turn"]
        if roots and roots[0]["context"]["trace_id"] != before:
            return roots[0]["context"]["trace_id"]
        time.sleep(1)
    return before

def main():
    narr = narration()
    T = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        ctx = br.new_context(viewport={"width": W, "height": H}, record_video_dir=str(OUT / "vid"), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        T["0"] = time.time()

        def scene(key, actions):
            f, dur = narr[key]
            start = time.time() - T["0"]
            CUES.append((start, f))
            s0 = time.time()
            actions()
            rest = dur + 1.0 - (time.time() - s0)
            if rest > 0: time.sleep(rest)
            print(f"scene {key}: narration {dur:.0f}s scene {time.time() - s0:.0f}s @ {start:.0f}s", flush=True)

        def sendmsg(text):
            before = latest_trace()
            with page.expect_response(lambda r: "/api/chat" in r.url, timeout=120000) as ri:
                page.fill("#msg", "")
                page.type("#msg", text, delay=35)
                page.press("#msg", "Enter")
            try: ri.value.finished()
            except Exception: pass
            time.sleep(1.2)
            return latest_trace(before)
        def login(email, pw):
            page.goto(WEB); page.wait_for_selector("#email")
            page.fill("#email", email); page.type("#pw", pw, delay=60); page.click("#go")
            page.wait_for_selector("#msg", state="visible")
        def phoenix(tid):
            page.goto(f"{PHX}/projects/{PROJ}/traces/{tid}"); time.sleep(3)

        scene("intro", lambda: term_page(page, ["./run.sh status"]))
        def A():
            login("alice.jones@example.com", "alice"); tid = sendmsg("What is the status of order 3?"); time.sleep(3); phoenix(tid); time.sleep(6)
        scene("A", A)
        def B():
            login("alice.jones@example.com", "alice"); sendmsg("What is the status of order 5?"); time.sleep(4)
            term_page(page, ["sed -n 22,30p mcp_toolbox/tools.yaml"])
        scene("B", B)
        def C():
            login("alice.jones@example.com", "alice"); tid = sendmsg("'; DROP TABLE users; --"); time.sleep(2); phoenix(tid); time.sleep(4)
        scene("C", C)
        def D():
            login("diana.prince@hero.net", "diana")
            sendmsg("Please remember I work from home, so leave packages at the back door"); time.sleep(3)
            sendmsg("Where should you leave my packages?"); time.sleep(5)
        scene("D", D)
        scene("E", lambda: (sendmsg("Write me a poem"), time.sleep(4)))
        def J():
            term_page(page, [("./run.sh stop judge >/dev/null; echo 'judge stopped'; ./run.sh status", "./run.sh stop judge; ./run.sh status")]); time.sleep(2)
            login("alice.jones@example.com", "alice"); tid = sendmsg("Where is my last order?"); time.sleep(3)
            phoenix(tid or latest_trace()); time.sleep(3)
            term_page(page, [("./run.sh up >/dev/null 2>&1; ./run.sh status", "./run.sh up; ./run.sh status")])
        scene("J", J)
        scene("CLI", lambda: (term_page(page, [('echo "What is the status of order 3?" | .venv/bin/python -m support.cli --user alice.jones@example.com 2>/dev/null',
                                               'echo "What is the status of order 3?" | python -m support.cli --user alice.jones@example.com')]), time.sleep(4)))
        scene("F", lambda: (phoenix("ca03a71b6c3a6a10e5538c5a4d29516d"), time.sleep(4)))
        scene("F2", lambda: (phoenix("c21d4103299b7037a4fa39d6036a5393"), time.sleep(4)))
        time.sleep(1.5)
        vid = page.video.path()
        ctx.close(); br.close()
    ins, flt, labels = ["-i", str(vid)], [], []
    for i, (t, f) in enumerate(CUES):
        ins += ["-i", str(f)]
        ms = int((t + 0.4) * 1000)
        flt.append(f"[{i+1}:a]aresample=44100,adelay={ms}|{ms}[a{i}]"); labels.append(f"[a{i}]")
    flt.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[aout]")
    r = subprocess.run(["ffmpeg", "-y", *ins, "-filter_complex", ";".join(flt), "-map", "0:v", "-map", "[aout]", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-r", "30", str(OUT / "demo.mp4")], capture_output=True, text=True)
    print(r.stderr[-500:] if r.returncode else "wrote demo.mp4")

main()
