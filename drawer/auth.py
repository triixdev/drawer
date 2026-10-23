"""OAuth 2.1 + PKCE for Drawer, shaped for Alexa+ account linking.

Alexa+ needs: 401 with no WWW-Authenticate for strangers, metadata at
/.well-known/oauth-authorization-server, and tokens bound to the MCP
server's canonical URI (the `resource` parameter).
"""
import base64
import collections
import hashlib
import hmac
import html
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from .store import Store

PUBLIC_URL = os.environ.get("DRAWER_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
RESOURCE = PUBLIC_URL + "/mcp"


@dataclass
class Principal:
    household_id: str
    scope: str  # "owner" or "guest"
    expires_at: float


def load_clients() -> dict:
    """DRAWER_CLIENTS="alexa:SECRET:https://a/cb|https://b/cb;other::https://x/cb" """
    clients = {"drawer-sim": {"secret": "", "redirects": []}}  # loopback only, no secret
    for part in filter(None, os.environ.get("DRAWER_CLIENTS", "").split(";")):
        cid, secret, redirects = (part.split(":", 2) + ["", ""])[:3]
        clients[cid] = {"secret": secret, "redirects": [r for r in redirects.split("|") if r]}
    return clients


def redirect_ok(client: dict, uri: str) -> bool:
    if uri in client["redirects"]:
        return True
    u = urlparse(uri)
    return not client["secret"] and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")


_fails = collections.defaultdict(list)


def _limited(key: str, limit=8, window=600) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < window]
    if recent:
        _fails[key] = recent
    else:
        _fails.pop(key, None)
    return len(recent) >= limit


def _page(body: str, status=200) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Drawer</title><link rel="stylesheet" href="/static/drawer.css"></head>'
        f"<body><main>{body}"
        '<footer><a href="/privacy">Privacy</a> &nbsp; <a href="/terms">Terms</a></footer>'
        "</main></body></html>", status_code=status)


def principal_from_headers(store: Store, headers) -> Principal | None:
    auth = headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    got = store.lookup_token(auth[7:].strip())
    return Principal(*got) if got else None


class AuthGate:
    """Pure ASGI middleware: strangers get a bare 401 before touching MCP."""

    def __init__(self, app, store: Store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].rstrip("/") == "/mcp":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if not principal_from_headers(self.store, headers):
                resp = JSONResponse({"error": "unauthorized"}, status_code=401)
                return await resp(scope, receive, send)
        await self.app(scope, receive, send)


class Headers:
    """Adds security headers to every response and stops caching of private pages."""

    CSP = (b"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
           b"frame-ancestors 'none'; base-uri 'none'")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]

        async def wrapped(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                         (b"referrer-policy", b"no-referrer"), (b"content-security-policy", self.CSP)]
                if path.startswith(("/authorize", "/sim", "/token", "/mcp")) and b"cache-control" not in have:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = list(message.get("headers", [])) + [
                    h for h in extra if h[0] not in have]
            await send(message)

        await self.app(scope, receive, wrapped)


def build_routes(store: Store):
    clients = load_clients()

    async def metadata(request: Request):
        return JSONResponse({
            "issuer": PUBLIC_URL,
            "authorization_endpoint": PUBLIC_URL + "/authorize",
            "token_endpoint": PUBLIC_URL + "/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
            "scopes_supported": ["owner", "guest"],
        })

    def _form(q, error=""):
        hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                         for k, v in q.items())
        err = f'<p class="err">{html.escape(error)}</p>' if error else ""
        return _page(f"""
<h1>Open your drawer</h1>
<p>Your household's notes stay encrypted on this server. There is no email and no account.
Only the passphrase below opens them.</p>{err}
<form method="post" action="/authorize">{hidden}
<label for="mode">What are you doing?</label>
<select id="mode" name="mode">
  <option value="open">Open my household</option>
  <option value="create">Start a new household</option>
  <option value="guest">I have a guest code</option>
</select>
<label for="name">Household name</label><input id="name" name="name" autocomplete="off" maxlength="80">
<label for="secret">Passphrase, or guest code</label>
<input id="secret" name="secret" type="password" autocomplete="off" maxlength="200">
<p class="small">Use a passphrase of four or more words. Nobody can reset it for you, because nobody else can read your data.</p>
<button type="submit">Continue</button></form>""")

    def _check_client(q):
        c = clients.get(q.get("client_id", ""))
        if not c or not redirect_ok(c, q.get("redirect_uri", "")):
            return None
        if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            return None
        if q.get("resource") and q["resource"].rstrip("/") != RESOURCE:
            return None
        return c

    KEEP = ("client_id", "redirect_uri", "response_type", "code_challenge",
            "code_challenge_method", "state", "resource", "scope")

    async def authorize(request: Request):
        if request.method == "GET":
            q = {k: request.query_params.get(k, "") for k in KEEP}
            if not _check_client(q):
                return _page("<h1>Link not valid</h1><p>This sign-in link is missing something or points "
                             "somewhere we do not trust.</p>", 400)
            return _form({k: v for k, v in q.items() if v})
        f = await request.form()
        q = {k: str(f.get(k, "")) for k in KEEP}
        if not _check_client(q):
            return _page("<h1>Link not valid</h1>", 400)
        keep = {k: v for k, v in q.items() if v}
        ip = request.client.host if request.client else "?"
        name = str(f.get("name", ""))[:80]
        secret = str(f.get("secret", ""))[:200]
        mode = str(f.get("mode", "open"))
        if _limited(ip):
            return _form(keep, "Too many tries. Wait ten minutes.")
        if mode == "create":
            _fails[ip].append(time.time())  # creating costs CPU, so it counts against the limit
        hid, scope = None, "owner"
        if mode == "create":
            if len(secret.split()) < 4 and len(secret) < 16:
                return _form(keep, "Choose a longer passphrase: four words or sixteen characters.")
            if not name.strip():
                return _form(keep, "Give your household a name.")
            if store.household_count() >= int(os.environ.get("DRAWER_MAX_HOUSEHOLDS", "500")):
                return _form(keep, "This demo is full for now. Try again later.")
            hid = store.create_household(name, secret)
            if not hid:
                return _form(keep, "That name is taken, or the details do not match. Try another name.")
        elif mode == "guest":
            got = store.use_guest_code(secret)
            if got:
                hid, scope = got[0], "guest"
        else:
            hid = store.verify_household(name, secret)
        if not hid:
            _fails[ip].append(time.time())
            return _form(keep, "Those details do not match.")
        store.purge_expired()
        code = store.create_code(hid, scope, q["code_challenge"], q["redirect_uri"], q["client_id"])
        params = {"code": code}
        if q.get("state"):
            params["state"] = q["state"]
        sep = "&" if "?" in q["redirect_uri"] else "?"
        return RedirectResponse(q["redirect_uri"] + sep + urlencode(params), status_code=303)

    def _err(msg, status=400):
        return JSONResponse({"error": msg}, status_code=status, headers={"Cache-Control": "no-store"})

    async def token(request: Request):
        f = await request.form()
        cid, secret = str(f.get("client_id", "")), str(f.get("client_secret", ""))
        basic = request.headers.get("authorization", "")
        if basic.lower().startswith("basic "):
            try:
                cid, secret = base64.b64decode(basic[6:]).decode().split(":", 1)
            except Exception:
                return _err("invalid_client", 401)
        client = clients.get(cid)
        if not client or not hmac.compare_digest(secret.encode(), client["secret"].encode()):
            return _err("invalid_client", 401)
        if f.get("resource") and str(f["resource"]).rstrip("/") != RESOURCE:
            return _err("invalid_target")
        grant = f.get("grant_type")
        if grant == "authorization_code":
            row = store.pop_code(str(f.get("code", "")))
            verifier = str(f.get("code_verifier", ""))
            want = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if (not row or row["client_id"] != cid or row["redirect_uri"] != str(f.get("redirect_uri", ""))
                    or not hmac.compare_digest(want.encode(), row["challenge"].encode())):
                return _err("invalid_grant")
            hid, scope = row["household_id"], row["scope"]
        elif grant == "refresh_token":
            old = str(f.get("refresh_token", ""))
            got = store.lookup_token(old, kind="refresh")
            if not got:
                return _err("invalid_grant")
            store.revoke_token(old)
            hid, scope = got[0], got[1]
        else:
            return _err("unsupported_grant_type")
        ttl = 900 if scope == "guest" else 3600
        out = {"token_type": "Bearer", "scope": scope}
        if scope == "owner":
            out["refresh_token"] = store.issue_token(hid, scope, "refresh", 30 * 86400)
        out["access_token"] = store.issue_token(hid, scope, "access", ttl)
        out["expires_in"] = ttl
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    return [
        Route("/.well-known/oauth-authorization-server", metadata),
        Route("/authorize", authorize, methods=["GET", "POST"]),
        Route("/token", token, methods=["POST"]),
    ]
