"""Stage 8: the Data Masker as its own A2A process (port 10003). It changes ONLY PII (K-2): emails other than the
user's own, phone numbers, card-like numbers. No case or whitespace changes. It reports what it changed (K-3)."""
import json, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import uvicorn
from guards.a2a_server import make_app

PORT = int(os.getenv("MASKER_PORT", "10003"))
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CARD = re.compile(r"(?<!\d)(?<!\d\.)(?:\d[ -]?){12,15}\d(?!\d|\.\d)")
PHONE = re.compile(r"(?<![\d.])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\d)|(?<![\d.-])\d{3}-\d{4}(?![\d-])")


def mask(text: str, own_email: str) -> dict:
    changes = {"email": 0, "phone": 0, "card": 0}

    def sub(kind, label):
        def f(m):
            if kind == "email" and m.group(0).lower() == own_email.lower():
                return m.group(0)   # the user's own email is theirs to see
            changes[kind] += 1
            return label
        return f
    out = CARD.sub(sub("card", "[card removed]"), text)
    out = EMAIL.sub(sub("email", "[email removed]"), out)
    out = PHONE.sub(sub("phone", "[phone removed]"), out)
    n = sum(changes.values())
    detail = "nothing to mask" if n == 0 else "masked " + ", ".join(f"{c} {k}{'s' if c > 1 else ''}" for k, c in changes.items() if c)
    return {"masked_text": out, "count": n, "detail": detail}


async def handler(raw: str) -> dict:
    req = json.loads(raw)
    return mask(req["text"], req.get("own_email", ""))

app = make_app("Data Masker", "Masks other people's emails, phone numbers and card numbers in a reply.",
               PORT, "data_masker", handler)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
