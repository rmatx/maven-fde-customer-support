"""The Judge's deterministic tool (J-2): injection, markup, template, shell/path and prompt-extraction shapes."""
import re

_RULES = [
    ("sql injection", r"'\s*(;|--|or\b|and\b|union\b)|;\s*(drop|delete|update|insert|alter|truncate)\b|\bunion\s+select\b|"
                      r"\bor\s+1\s*=\s*1|\bdrop\s+table\b|\bdelete\s+from\b|\bupdate\s+\w+\s+set\b|\bselect\b.+\bfrom\b|--\s*$"),
    ("markup / xss", r"<\s*/?\s*(script|iframe|img|svg|object|embed)\b|\bon\w+\s*=|javascript\s*:"),
    ("template injection", r"\{\{.*\}\}|\$\{.*\}|\{%.*%\}"),
    ("shell / path traversal", r";\s*(cat|rm|ls|curl|wget|bash|sh|nc)\b|\$\(|`[^`]+`|/etc/(passwd|shadow)|\.\./"),
    ("prompt injection / extraction",
     r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|messages|rules)|forget\s+your\s+(rules|instructions)|"
     r"you\s+are\s+now\b|new\s+instructions|\bsystem\s*:|system\s+prompt|your\s+instructions|"
     r"repeat\s+everything\s+above|pretend\s+(that\s+)?the\b|answer\s+as\s+the\s+(database\s+)?administrator|"
     r"ignore\s+the\s+above"),
    ("bulk data / privilege request",
     r"\b(all|every)\s+(of\s+)?(the\s+)?(customers?|users?|clients?)\b|\bpasswords?\b.{0,30}\b(all|every)\b|\b(all|every)\b.{0,30}\bpasswords?\b|"
     r"\bexport\b.{0,40}\b(csv|emails?|addresses|customers?)\b|\bset\s+my\s+account\s+to\s+(premium|admin)|"
     r"\bapply\s+a?\s*\d+\s*%\s*discount|\bdump\b|\bwhose\s+name\s+starts"),
]
_COMPILED = [(name, re.compile(rx, re.I | re.S)) for name, rx in _RULES]


def scan_patterns(message: str) -> dict:
    """Scan a customer message for known attack shapes. Returns {"hits": [names]}; empty means nothing matched."""
    return {"hits": [name for name, rx in _COMPILED if rx.search(message)]}
