"""The simulator: a plain rules-based stand-in for the voice assistant.

It turns a typed sentence into one Drawer tool call and sends it through the
real MCP endpoint with the signed-in person's own token. No AI model is used,
so nothing here leaves the server.
"""
import os
import re
from datetime import date, timedelta

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import auth

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
HELP = ("I can save purchases, places and phone numbers, tell you what is closing, find things, "
        "and help when something breaks. Try: the main water valve is behind the water heater.")


def parse_date(text: str, today: date) -> str:
    t = text.lower()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+) days? ago", t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (" + "|".join(MONTHS) + r")\b", t)
    if m:
        return date(today.year, MONTHS[m.group(2)], int(m.group(1))).isoformat()
    return today.isoformat()


def interpret(text: str, today: date):
    t = text.strip()
    low = t.lower().rstrip(".!?")
    if not low:
        return None
    if re.search(r"\bforget everything\b", low):
        return "forget_everything", {"confirm": low.startswith(("yes", "confirm"))}
    if "guest" in low and re.search(r"\b(end|stop|cancel)\b", low):
        return "end_guest_passes", {}
    if "guest" in low and re.search(r"\b(code|pass)\b", low):
        m = re.search(r"(\d+)\s*(day|hour)", low)
        hours = int(m.group(1)) * (24 if m and m.group(2) == "day" else 1) if m else 24
        return "make_guest_pass", {"hours": hours}
    if re.search(r"what happened|anything happen|while i was away", low):
        return "what_happened", {}
    if re.search(r"keep or return|should i keep|check.?in", low):
        return "keep_or_return", {}
    if re.search(r"closing|expir|running out|deadline", low):
        m = re.search(r"(\d+)\s*day", low)
        return "whats_closing", {"within_days": int(m.group(1)) if m else 14}
    m = re.search(r"draft (?:a )?claim (?:for|about) (?:my |the )?(.+?)(?:,| it | that | because )\s*(.*)", t, re.I)
    if m:
        return "draft_claim", {"item": m.group(1).strip(), "problem": m.group(2).strip() or "it stopped working"}
    m = re.search(r"\b(kept|keeping|keep|returned|returning|return)\b (?:the |my )?(.+)", low)
    if m and re.match(r"(i'?m |i |we )", low):
        out = "kept" if m.group(1).startswith("keep") or m.group(1) == "kept" else "returned"
        return "close_item", {"query": m.group(2), "outcome": out}
    if re.search(r"\b(leak|leaking|flood|burst|broke|broken|not working|stopped working|tripped|"
                 r"no power|sparks?|smoke|smell gas|gas smell|burning|dead)\b", low):
        return "something_wrong", {"problem": t}
    m = re.match(r"where (?:is|are|do i keep|did i put) (?:the |my )?(.+)", low)
    if m:
        return "where_is", {"query": m.group(1)}
    m = re.search(r"who (?:do i|should i) call (?:for |about )?(.+)", low)
    if m:
        return "where_is", {"query": m.group(1)}
    m = re.search(r"my (.+?)(?: is|'s) ([A-Z][\w ]+?)[, ]+(\+?[\d][\d ()-]{6,})", t)
    if m:
        return "remember_vendor", {"trade": m.group(1), "name": m.group(2).strip(), "phone": m.group(3).strip(),
                                   "guest_ok": "guest" in low}
    m = re.search(r"\b(?:bought|got|ordered)\s+(?:a |an |the |my )?(.+)", t, re.I)
    if m:
        body = m.group(1)
        name = re.split(r"\s+(?:from|at|on|today|yesterday|\d+ days? ago)\b|,", body)[0].strip()
        store = re.search(r"(?:from|at)\s+([A-Za-z0-9&' ]+?)(?=,| on | today| yesterday| \d+ days? ago| kept| with|$)", body)
        ret = re.search(r"(\d+)[ -]days? return", low)
        yrs = re.search(r"(\d+)[ -]years? warranty", low)
        mos = re.search(r"(\d+)[ -]months? warranty", low)
        loc = re.search(r"(?:kept|papers|receipt|bill|box) in (?:the )?(.+)$", t, re.I)
        return "remember_purchase", {
            "name": name, "purchased_on": parse_date(body, today),
            "store_name": store.group(1).strip() if store else "",
            "return_days": int(ret.group(1)) if ret else 0,
            "warranty_months": int(yrs.group(1)) * 12 if yrs else (int(mos.group(1)) if mos else 0),
            "location": loc.group(1).strip() if loc else ""}
    m = re.match(r"(?:remember |save )?(?:that )?(?:the |my )?(.+?) (?:is|are) ((?:in|at|behind|under|on|next to|inside|near) .+)", t, re.I)
    if m:
        where = re.sub(r"[,;]?\s*(?:and\s+)?(?:guests?|sitters?|the sitter)\b.*$", "", m.group(2), flags=re.I).strip()
        return "remember_place", {"what": m.group(1).strip(), "where": where,
                                  "guest_ok": bool(re.search(r"guest|sitter", low))}
    return None


async def run_tool(base_url: str, token: str, tool: str, args: dict) -> str:
    client = httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    async with streamable_http_client(base_url + "/mcp", http_client=client) as st:
        async with ClientSession(st[0], st[1]) as s:
            await s.initialize()
            r = await s.call_tool(tool, args)
            text = r.content[0].text if r.content else ""
            return "I can't do that with this sign-in." if r.is_error else text


def routes(store, today_fn):
    base = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"

    def who(request: Request):
        return auth.principal_from_headers(store, request.headers)

    async def page(request: Request):
        return FileResponse(os.path.join(os.path.dirname(__file__), "static", "sim.html"))

    async def say(request: Request):
        p = who(request)
        if not p:
            return JSONResponse({"error": "signed_out"}, status_code=401)
        body = await request.json()
        text = str(body.get("text", ""))[:500]
        hit = interpret(text, today_fn())
        if not hit:
            return JSONResponse({"reply": HELP, "tool": None})
        tool, args = hit
        token = request.headers["authorization"][7:].strip()
        return JSONResponse({"reply": await run_tool(base, token, tool, args), "tool": tool})

    async def shelf(request: Request):
        p = who(request)
        if not p:
            return JSONResponse({"error": "signed_out"}, status_code=401)
        guest = p.scope == "guest"
        es = store.entries(p.household_id, guest_only=guest)
        closing = [] if guest else [
            {"name": r["name"], "what": r["what"], "days_left": r["days_left"], "deadline": r["deadline"]}
            for r in store.closing(p.household_id, today_fn(), 30)]
        return JSONResponse({
            "scope": p.scope, "closing": closing,
            "places": [{"name": e["name"], "where": e["where"]} for e in es if e["kind"] == "place"],
            "vendors": [{"name": e["name"], "trade": e["trade"], "phone": e["phone"]}
                        for e in es if e["kind"] == "vendor"]})

    return [Route("/sim", page), Route("/sim/say", say, methods=["POST"]), Route("/sim/shelf", shelf)]
