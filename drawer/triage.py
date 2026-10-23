"""Incident triage. Deterministic on purpose: safety advice never comes from a model."""
from datetime import date

EMERGENCY = ("gas", "smoke", "fire", "burning", "burnt", "sparks", "sparking",
             "shock", "carbon monoxide", "explosion")
CATEGORIES = {
    "water": (("leak", "leaking", "flood", "burst", "dripping", "overflow", "water", "pipe"),
              ("water", "valve", "stopcock", "tap", "tank"), ("plumb", "water")),
    "power": (("power", "tripped", "trip", "fuse", "breaker", "outage", "electricity", "short"),
              ("fuse", "breaker", "mcb", "electric", "meter", "power"), ("electric",)),
}
STOP = set("the a an is are was my our it its not working stopped broken wont won't doesn't "
           "does what with this that has have have and for from into over under".split())


def classify(problem: str) -> str:
    p = problem.lower()
    if any(w in p for w in EMERGENCY):
        return "emergency"
    for cat, (words, _, _) in CATEGORIES.items():
        if any(w in p for w in words):
            return cat
    return "appliance"


def best_item(purchases, problem: str, hint: str = ""):
    words = {w for w in (problem + " " + hint).lower().replace(",", " ").split()
             if len(w) > 3 and w not in STOP}
    scored = []
    for e in purchases:
        hay = f"{e.get('name','')} {e.get('store','')}".lower()
        s = sum(1 for w in words if w in hay)
        if s:
            scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


def coverage(item, today: date) -> str:
    t = today.isoformat()
    bits = []
    if item.get("warranty_until"):
        bits.append(f"warranty runs to {item['warranty_until']}" if item["warranty_until"] >= t
                    else f"warranty ended {item['warranty_until']}")
    if item.get("return_by") and item["return_by"] >= t and item["status"] == "open":
        bits.append(f"you can still return it until {item['return_by']}")
    return "; ".join(bits)


def triage(entries, problem: str, today: date, guest: bool = False, hint: str = "") -> dict:
    cat = classify(problem)
    if cat == "emergency":
        return {"category": cat, "emergency": True, "steps": [
            "Leave the house now and take everyone with you.",
            "Do not switch anything on or off, and do not use a lighter or a phone indoors if you smell gas.",
            "From outside, call your local emergency number."], "item": None}
    _, place_hints, trades = CATEGORIES.get(cat, ((), (), ()))
    places = [e for e in entries if e["kind"] == "place" and (not guest or e["guest_ok"])]
    vendors = [e for e in entries if e["kind"] == "vendor" and (not guest or e["guest_ok"])]
    first = [p for p in places if any(h in f"{p['name']} {p.get('where','')}".lower() for h in place_hints)]
    item = None
    if not guest:
        item = best_item([e for e in entries if e["kind"] == "purchase"], problem, hint)
    call = [v for v in vendors if any(t in f"{v.get('trade','')} {v['name']}".lower() for t in trades)]
    if item and not call:
        call = [v for v in vendors if any(w in f"{v.get('trade','')} {v['name']}".lower()
                                          for w in item["name"].lower().split() if len(w) > 3)]
    return {"category": cat, "emergency": False, "item": item, "first": first, "call": call,
            "coverage": coverage(item, today) if item else ""}
