"""One-off: transcribe the EVALS §3 tables into eval/gold/<set>.jsonl, verbatim (the items are not edited)."""
import json, re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
text = (root / "EVALS.md").read_text()
FIRST = {"alice": "alice.jones@example.com", "bob": "bob.smith@techmail.com", "charlie": "charlie.d@webmail.com",
         "diana": "diana.prince@hero.net", "evan": "evan.g@bizcorp.com", "fiona": "fiona.shrek@swamp.com",
         "george": "george.j@jungle.com", "hannah": "hannah.m@school.edu", "ian": "ian.malcolm@chaos.com",
         "julia": "julia.child@kitchen.com"}


def section(num):
    body = text.split(f"### {num} ")[1]
    return re.split(r"\n### |\n## ", body)[0]


def rows(sec):
    for line in sec.splitlines():
        if line.startswith("|") and not line.startswith("|---") and "| Id |" not in line:
            yield [c.strip() for c in line.strip().strip("|").split(" | ")]


def unq(s):
    return s[1:-1] if s.startswith("`") and s.endswith("`") else s


def write(name, items):
    (root / "eval" / "gold").mkdir(parents=True, exist_ok=True)
    (root / "eval" / "gold" / f"{name}.jsonl").write_text("\n".join(json.dumps(i) for i in items) + "\n")
    print(name, len(items))


write("attack", [{"id": r[0], "user": FIRST["alice"], "message": unq(r[1])} for r in rows(section("3.1"))])
write("legit", [{"id": r[0], "user": FIRST[r[1]], "message": r[2]} for r in rows(section("3.2"))])
write("offtopic", [{"id": r[0], "user": FIRST["alice"], "message": r[1]} for r in rows(section("3.3"))])
write("probe", [{"id": r[0], "user": FIRST[r[1]], "message": r[2], "markers": [m.strip() for m in re.split(r",|; or ", r[3])]} for r in rows(section("3.4"))])
write("order", [{"id": r[0], "user": FIRST[r[1]], "message": r[2], "contains": r[3], "tool": r[4]} for r in rows(section("3.5"))])
write("action", [{"id": r[0], "user": FIRST[r[1]], "message": r[2], "action_type": r[3]} for r in rows(section("3.6"))])
write("memory", [{"id": r[0], "user": FIRST[r[1]], "plant": r[2], "ask": r[3], "keyword": r[4]} for r in rows(section("3.7"))])
