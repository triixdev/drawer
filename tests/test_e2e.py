"""Real server, real OAuth + PKCE, real MCP client over Streamable HTTP."""
import asyncio, base64, hashlib, os, re, secrets, socket, subprocess, sys, time
from urllib.parse import parse_qs, urlparse

import httpx2 as httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

REDIRECT = "http://127.0.0.1:9/cb"


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    home = tmp_path_factory.mktemp("home")
    env = {**os.environ, "DRAWER_HOME": str(home), "PORT": str(port),
           "DRAWER_PUBLIC_URL": f"http://127.0.0.1:{port}", "DRAWER_TODAY": "2026-10-22"}
    p = subprocess.Popen([sys.executable, "-m", "drawer.server"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(url + "/health"); break
        except Exception:
            time.sleep(0.2)
    yield url, home
    p.terminate()


def login(base, mode, name, secret):
    verifier = secrets.token_urlsafe(40)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    c = httpx.Client(follow_redirects=False)
    r = c.post(base + "/authorize", data={
        "client_id": "drawer-sim", "redirect_uri": REDIRECT, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
        "resource": base + "/mcp", "mode": mode, "name": name, "secret": secret})
    assert r.status_code == 303, r.text
    qs = parse_qs(urlparse(r.headers["location"]).query)
    assert qs["state"] == ["xyz"]
    t = c.post(base + "/token", data={
        "grant_type": "authorization_code", "code": qs["code"][0], "code_verifier": verifier,
        "redirect_uri": REDIRECT, "client_id": "drawer-sim", "resource": base + "/mcp"})
    assert t.status_code == 200, t.text
    return t.json()


def call(base, token, tool, args=None):
    async def go():
        client = httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"})
        async with streamable_http_client(base + "/mcp", http_client=client) as st:
            async with ClientSession(st[0], st[1]) as s:
                await s.initialize()
                r = await s.call_tool(tool, args or {})
                return ("ERROR " if r.is_error else "") + r.content[0].text
    return asyncio.run(go())


def test_alexa_requirements(base):
    url, _ = base
    r = httpx.post(url + "/mcp", json={})
    assert r.status_code == 401 and "www-authenticate" not in r.headers
    bad = httpx.post(url + "/mcp", json={}, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    m = httpx.get(url + "/.well-known/oauth-authorization-server").json()
    assert m["code_challenge_methods_supported"] == ["S256"]
    # wrong resource must be refused
    r = httpx.get(url + "/authorize", params={
        "client_id": "drawer-sim", "redirect_uri": REDIRECT, "response_type": "code",
        "code_challenge": "x", "code_challenge_method": "S256", "resource": "http://evil/mcp"})
    assert r.status_code == 400
    # evil redirect refused
    r = httpx.get(url + "/authorize", params={
        "client_id": "drawer-sim", "redirect_uri": "https://evil.example/cb", "response_type": "code",
        "code_challenge": "x", "code_challenge_method": "S256"})
    assert r.status_code == 400
    assert "/privacy" in httpx.get(url + "/authorize", params={
        "client_id": "drawer-sim", "redirect_uri": REDIRECT, "response_type": "code",
        "code_challenge": "x", "code_challenge_method": "S256"}).text


def test_full_story(base):
    url, home = base
    pw = "river copper maple slate"
    owner = login(url, "create", "Das Home", pw)["access_token"]
    assert login(url, "open", "Das Home", pw)["access_token"]
    with pytest.raises(AssertionError):
        login(url, "open", "Das Home", "wrong wrong wrong wrong")

    call(url, owner, "remember_place", {"what": "main water valve", "where": "behind the water heater, blue handle", "guest_ok": True})
    call(url, owner, "remember_place", {"what": "fuse box", "where": "in the hallway cupboard", "guest_ok": True})
    call(url, owner, "remember_vendor", {"name": "Ravi", "trade": "plumber", "phone": "98300 11122", "guest_ok": True})
    call(url, owner, "remember_vendor", {"name": "Sen Cooling", "trade": "fridge repair", "phone": "98300 99999"})
    call(url, owner, "remember_place", {"what": "passport folder", "where": "grey steel almirah, top shelf"})
    out = call(url, owner, "remember_purchase", {"name": "Bosch washing machine", "purchased_on": "2026-10-15",
        "store_name": "Croma", "return_days": 10, "warranty_months": 24, "location": "blue file, study"})
    assert "2026-10-25" in out and "2028-10-15" in out

    closing = call(url, owner, "whats_closing", {"within_days": 7})
    assert "return window ends in 3 days" in closing
    assert "Have you used it" in call(url, owner, "keep_or_return")

    out = call(url, owner, "something_wrong", {"problem": "washing machine is leaking water"})
    assert "behind the water heater" in out and "Bosch" in out and "arranty runs to 2028-10-15" in out
    assert "Ravi" in out and "blue file" in out
    gas = call(url, owner, "something_wrong", {"problem": "I can smell gas"})
    assert "Leave the house" in gas and "Ravi" not in gas

    # raw database must not contain anything personal
    raw = open(home / "drawer.db", "rb").read()
    for secret_word in (b"Bosch", b"Croma", b"water heater", b"Ravi", b"98300", b"passport", b"Das Home"):
        assert secret_word not in raw

    # guest sees only guest-safe things
    code = re.search(r"Guest code: (\S+?)\.", call(url, owner, "make_guest_pass", {"hours": 2})).group(1)
    guest = login(url, "guest", "", code)
    assert guest["scope"] == "guest" and "refresh_token" not in guest
    g = guest["access_token"]
    assert "behind the water heater" in call(url, g, "where_is", {"query": "water valve"})
    assert "nothing saved" in call(url, g, "where_is", {"query": "passport"})
    assert "nothing saved" in call(url, g, "where_is", {"query": "washing machine"})
    assert call(url, g, "whats_closing").startswith("ERROR")
    assert call(url, g, "forget_everything", {"confirm": True}).startswith("ERROR")
    gw = call(url, g, "something_wrong", {"problem": "washing machine leaking water"})
    assert "Bosch" not in gw and "warranty" not in gw.lower() and "Ravi" in gw
    assert "(guest)" in call(url, owner, "what_happened")
    assert "Ended 1" in call(url, owner, "end_guest_passes")
    r = httpx.post(url + "/mcp", json={}, headers={"Authorization": f"Bearer {g}"})
    assert r.status_code == 401

    # a second household sees nothing of the first
    other = login(url, "create", "Someone Else", "pebble tundra heron quartz")["access_token"]
    assert "nothing saved" in call(url, other, "where_is", {"query": "water valve"})
    assert "Nothing closes" in call(url, other, "whats_closing", {"within_days": 60})

    # wipe
    assert "confirm" in call(url, owner, "forget_everything")
    # the wipe revokes the token, so the client's own follow-up request is refused: that is the point
    with pytest.raises(BaseException):
        call(url, owner, "forget_everything", {"confirm": True})
    import sqlite3
    db = sqlite3.connect(str(home / "drawer.db"))
    assert db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM households").fetchone()[0] == 1  # only the other household
    assert httpx.post(url + "/mcp", json={}, headers={"Authorization": f"Bearer {owner}"}).status_code == 401
