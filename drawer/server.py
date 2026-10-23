"""Drawer: your household's memory, spoken. An MCP server for Alexa+."""
import os
from datetime import date
from urllib.parse import urlparse

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import ai, auth, legal, sim, triage
from .store import Store

store = Store()
STATIC = os.path.join(os.path.dirname(__file__), "static")


def today() -> date:
    return date.fromisoformat(os.environ["DRAWER_TODAY"]) if os.environ.get("DRAWER_TODAY") else date.today()


def who(ctx: Context, owner_only: bool = False) -> auth.Principal:
    p = auth.principal_from_headers(store, ctx.headers or {})
    if not p:
        raise ToolError("Sign in to Drawer first.")
    if owner_only and p.scope != "owner":
        raise ToolError("That one is only for the household owner.")
    return p


mcp = MCPServer(
    "Drawer",
    instructions=(
        "Drawer is a household's memory. Save purchases with warranty and return dates, where things are "
        "(shutoff valves, fuse box, spare keys), and who to call. When something goes wrong, use "
        "something_wrong first. Convert spoken dates to YYYY-MM-DD. Keep replies short, never read ids "
        "aloud, and never invent a return window or warranty the person did not state."),
)


def _name(e):
    return e["name"] + (f" from {e['store']}" if e.get("store") else "")


@mcp.tool()
def remember_purchase(ctx: Context, name: str, purchased_on: str, store_name: str = "",
                      return_days: int = 0, warranty_months: int = 0, note: str = "",
                      location: str = "") -> str:
    """Save something bought. purchased_on is YYYY-MM-DD. Only set return_days or warranty_months
    if the person said them."""
    p = who(ctx, owner_only=True)
    try:
        bought = date.fromisoformat(purchased_on)
    except ValueError:
        return "I need the purchase date as year, month, day."
    from datetime import timedelta
    return_by = (bought + timedelta(days=return_days)).isoformat() if return_days > 0 else None
    warranty = None
    if warranty_months > 0:
        m = bought.month - 1 + warranty_months
        warranty = date(bought.year + m // 12, m % 12 + 1, min(bought.day, 28)).isoformat()
    store.add_entry(p.household_id, "purchase",
                    {"name": name, "store": store_name, "note": note, "location": location},
                    purchased_on, return_by, warranty)
    out = [f"Saved {name}."]
    if return_by:
        out.append(f"Return window closes {return_by}, as you told me.")
    if warranty:
        out.append(f"Warranty runs to {warranty}, as you told me.")
    if not return_by and not warranty:
        out.append("No return or warranty dates saved. Tell me if there are any.")
    return " ".join(out)


@mcp.tool()
def remember_place(ctx: Context, what: str, where: str, guest_ok: bool = False) -> str:
    """Save where something is, like the main water valve or spare keys. guest_ok lets a house sitter ask."""
    p = who(ctx, owner_only=True)
    store.add_entry(p.household_id, "place", {"name": what, "where": where}, guest_ok=guest_ok)
    return f"Got it. {what} is {where}." + (" Guests can ask about it." if guest_ok else "")


@mcp.tool()
def remember_vendor(ctx: Context, name: str, trade: str, phone: str, guest_ok: bool = False) -> str:
    """Save someone to call, like a plumber. trade is what they do."""
    p = who(ctx, owner_only=True)
    store.add_entry(p.household_id, "vendor", {"name": name, "trade": trade, "phone": phone},
                    guest_ok=guest_ok)
    return f"Saved {name}, {trade}."


@mcp.tool()
def where_is(ctx: Context, query: str) -> str:
    """Find where something is kept, or who to call."""
    p = who(ctx)
    guest = p.scope == "guest"
    hits = store.search(p.household_id, query, guest_only=guest)
    out = []
    for h in hits[:4]:
        if h["kind"] == "place":
            out.append(f"{h['name']}: {h['where']}.")
        elif h["kind"] == "vendor":
            out.append(f"{h['name']}, {h['trade']}, {h['phone']}.")
        elif h.get("location"):
            out.append(f"{h['name']} is in {h['location']}.")
    return " ".join(out) or "I have nothing saved for that."


@mcp.tool()
def whats_closing(ctx: Context, within_days: int = 14) -> str:
    """List return windows and warranties ending soon."""
    p = who(ctx, owner_only=True)
    rows = store.closing(p.household_id, today(), max(1, min(within_days, 365)))
    if not rows:
        return f"Nothing closes in the next {within_days} days."
    parts = []
    for r in rows[:6]:
        when = "today" if r["days_left"] == 0 else f"in {r['days_left']} days"
        parts.append(f"{_name(r)}: {r['what']} ends {when}.")
    return " ".join(parts)


@mcp.tool()
def keep_or_return(ctx: Context) -> str:
    """Items whose return window closes within 3 days. Ask the person if they are keeping each one."""
    p = who(ctx, owner_only=True)
    rows = [r for r in store.closing(p.household_id, today(), 3) if r["what"] == "return window"]
    if not rows:
        return "No return windows are about to close."
    r = rows[0]
    left = "today" if r["days_left"] == 0 else f"in {r['days_left']} days"
    return (f"The return window for {_name(r)} closes {left}. Have you used it, and are you keeping it? "
            "Say kept or returned and I will stop reminding you.")


@mcp.tool()
def close_item(ctx: Context, query: str, outcome: str) -> str:
    """Mark a purchase 'kept' or 'returned' so it stops showing up."""
    p = who(ctx, owner_only=True)
    if outcome not in ("kept", "returned"):
        return "Say kept or returned."
    hits = [h for h in store.search(p.household_id, query, kinds=["purchase"]) if h["status"] == "open"]
    if len(hits) != 1:
        return f"I found {len(hits)} matches. Which one?" if hits else "No open purchase matches that."
    store.set_status(p.household_id, hits[0]["id"], outcome)
    return f"Marked {hits[0]['name']} as {outcome}."


@mcp.tool()
def something_wrong(ctx: Context, problem: str, item: str = "") -> str:
    """Use first when something breaks, leaks, trips or smells wrong. Says what to do right now."""
    p = who(ctx)
    guest = p.scope == "guest"
    entries = store.entries(p.household_id)
    t = triage.triage(entries, problem, today(), guest=guest, hint=item)
    if t["emergency"]:
        store.log_incident(p.household_id, {"problem": problem, "category": "emergency", "by": p.scope})
        return " ".join(t["steps"])
    out = []
    if t["first"]:
        out.append("First, " + " ".join(
            f"{e['name']} is {e['where']}." for e in t["first"][:2]))
    else:
        out.append("I have no saved shutoff for this. Switch off the nearest supply if it is safe to do so.")
    if t["item"]:
        out.append(f"That looks like your {_name(t['item'])}.")
        if t["coverage"]:
            out.append(t["coverage"][0].upper() + t["coverage"][1:] + ", as you told me.")
        if t["item"].get("location"):
            out.append(f"You kept the papers in {t['item']['location']}.")
    if t["call"]:
        v = t["call"][0]
        out.append(f"Call {v['name']}, {v['phone']}.")
    elif guest:
        out.append("Call the homeowner.")
    store.log_incident(p.household_id, {"problem": problem, "category": t["category"], "by": p.scope,
                                        "item": t["item"]["name"] if t["item"] else ""})
    if t["item"] and t["coverage"] and not guest:
        out.append("Want me to draft a claim message?")
    return " ".join(out)


@mcp.tool()
def draft_claim(ctx: Context, item: str, problem: str) -> str:
    """Draft (never send) a warranty claim message for something that broke."""
    p = who(ctx, owner_only=True)
    hits = [h for h in store.search(p.household_id, item, kinds=["purchase"])]
    if len(hits) != 1:
        return f"I found {len(hits)} matches for that. Which item?" if hits else "I have no purchase like that saved."
    h = hits[0]
    text, source = ai.draft_claim({"name": h["name"], "store": h.get("store", ""),
        "purchased_on": h["purchased_on"], "problem": problem,
        "coverage": triage.coverage(h, today())})
    return "Here is a draft. Read it before you send it: " + text


@mcp.tool()
def what_happened(ctx: Context) -> str:
    """Recent incidents, for example while the owner was away."""
    p = who(ctx, owner_only=True)
    rows = store.incidents(p.household_id)[:5]
    if not rows:
        return "Nothing has been reported."
    return " ".join(f"{r['at'][:10]}: {r['problem']}" + (" (guest)" if r["by"] == "guest" else "") + "."
                    for r in rows)


@mcp.tool()
def make_guest_pass(ctx: Context, hours: int = 24) -> str:
    """Make a temporary code for a house sitter. They only see entries marked guest-safe."""
    p = who(ctx, owner_only=True)
    hours = max(1, min(hours, 24 * 14))
    code = store.create_guest_pass(p.household_id, hours)
    return f"Guest code: {code}. It works for {hours} hours and opens only what you marked guest-safe."


@mcp.tool()
def end_guest_passes(ctx: Context) -> str:
    """End every guest code and sign guests out now."""
    p = who(ctx, owner_only=True)
    return f"Ended {store.end_guest_passes(p.household_id)} guest codes."


@mcp.tool()
def forget_everything(ctx: Context, confirm: bool = False) -> str:
    """Permanently delete the household and everything in it. Needs confirm=true."""
    p = who(ctx, owner_only=True)
    if not confirm:
        return "This deletes everything for good. Ask the person to confirm first."
    return f"Done. Deleted {store.wipe(p.household_id)} entries and closed the household."


def build_app():
    host = urlparse(auth.PUBLIC_URL).netloc
    app = mcp.streamable_http_app(
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, "127.0.0.1:*", "localhost:*"],
            allowed_origins=[auth.PUBLIC_URL, "http://127.0.0.1:*", "http://localhost:*"]),
    )
    page = lambda body: (lambda request: auth._page(body))
    app.router.routes.extend(auth.build_routes(store) + sim.routes(store, today) + [
        Route("/privacy", page(legal.PRIVACY)), Route("/terms", page(legal.TERMS)),
        Route("/health", lambda r: JSONResponse({"ok": True})),
        Mount("/static", StaticFiles(directory=STATIC)),
    ])
    app.add_middleware(auth.AuthGate, store=store)
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("DRAWER_HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
