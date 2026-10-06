"""Stage 6 (S-1, S-2): in-process, no model call. Length, character allow-list, the cheapest obvious patterns.
Apostrophes, #, $, :, ;, @ and ordinary punctuation are deliberately allowed (the legitimate set contains them)."""
import re

MAX_LEN = 1000
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CHEAP = [
    (re.compile(r"<\s*/?\s*(script|iframe|object|embed)\b", re.I), "markup tag"),
    (re.compile(r"\bon(error|load|click)\s*=", re.I), "inline event handler"),
    (re.compile(r"javascript\s*:", re.I), "javascript: URL"),
    (re.compile(r"\.\./"), "path traversal"),
]


def sanitize(message: str) -> tuple[str, str]:
    """Returns (status, detail): status is 'passed' or 'blocked'."""
    if len(message) > MAX_LEN:
        return "blocked", f"too long ({len(message)} > {MAX_LEN} chars)"
    if _CTRL.search(message):
        return "blocked", "control characters"
    for pattern, name in _CHEAP:
        if pattern.search(message):
            return "blocked", name
    return "passed", "length, characters and cheap patterns ok"
