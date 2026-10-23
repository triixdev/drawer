"""Strip personal details before any text leaves the server.

This is a best-effort filter, not a guarantee. It runs only when the optional
AI helper is on, and it errs on the side of removing too much.
"""
import re

_RULES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"https?://\S+"), "[link]"),
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[card]"),
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[id number]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[tax id]"),
    (re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)"), "[phone]"),
    (re.compile(r"\b\d{6}\b"), "[postcode]"),
    (re.compile(r"\b(?:flat|apt|apartment|house|plot|door)\s*(?:no\.?)?\s*[\w/-]+", re.I), "[address]"),
    (re.compile(r"\b\d+[\w/-]*,?\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*)*\s+(?:street|st|road|rd|lane|ln|avenue|ave|nagar|sector)\b", re.I), "[address]"),
]


_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def scrub(text: str) -> str:
    # dates are not personal and the phone rule would otherwise eat them
    dates = _DATE.findall(text)
    text = _DATE.sub(lambda m: f"\x00{dates.index(m.group(0))}\x00", text)
    for rx, label in _RULES:
        text = rx.sub(label, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: dates[int(m.group(1))], text)
