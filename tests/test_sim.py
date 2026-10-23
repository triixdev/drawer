from datetime import date

import httpx2 as httpx
from drawer.sim import interpret
from test_e2e import base, login  # noqa: F401  (fixture and helper)

T = date(2026, 10, 22)


def test_sentences_become_the_right_tool():
    assert interpret("the main water valve is behind the water heater", T) == (
        "remember_place", {"what": "main water valve", "where": "behind the water heater", "guest_ok": False})
    assert interpret("the main water valve is behind the water heater, guests can know", T) == (
        "remember_place", {"what": "main water valve", "where": "behind the water heater", "guest_ok": True})
    tool, a = interpret("my plumber is Ravi, 98300 11122, guests can call him", T)
    assert tool == "remember_vendor" and a["guest_ok"] and a["phone"] == "98300 11122"
    tool, a = interpret("my plumber is Ravi, 98300 11122", T)
    assert tool == "remember_vendor" and a["name"] == "Ravi" and a["trade"] == "plumber" and "98300" in a["phone"]
    tool, a = interpret("I bought a Bosch washing machine at Croma 5 days ago, 10 day return, "
                        "2 year warranty, papers in the blue file", T)
    assert tool == "remember_purchase" and a["name"] == "Bosch washing machine" and a["store_name"] == "Croma"
    assert a["purchased_on"] == "2026-10-17" and a["return_days"] == 10 and a["warranty_months"] == 24
    assert a["location"] == "the blue file" or a["location"] == "blue file"
    assert interpret("what's closing", T)[0] == "whats_closing"
    assert interpret("the washing machine is leaking water", T)[0] == "something_wrong"
    assert interpret("I can smell gas", T)[0] == "something_wrong"
    assert interpret("where is the fuse box", T) == ("where_is", {"query": "fuse box"})
    tool, a = interpret("draft a claim for the washing machine, it leaks from the door", T)
    assert tool == "draft_claim" and a["item"] == "washing machine" and "leaks" in a["problem"]
    assert interpret("make a guest code for 2 days", T) == ("make_guest_pass", {"hours": 48})
    assert interpret("forget everything", T) == ("forget_everything", {"confirm": False})
    assert interpret("yes forget everything", T) == ("forget_everything", {"confirm": True})
    assert interpret("blah blah", T) is None


def test_simulator_through_the_real_server(base):
    url, _ = base
    tok = login(url, "create", "Sim Home", "heron slate cedar amber")["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    assert httpx.post(url + "/sim/say", json={"text": "hi"}).status_code == 401
    assert httpx.get(url + "/sim/shelf").status_code == 401
    assert "sim" in httpx.get(url + "/sim").text.lower()

    def say(t):
        return httpx.post(url + "/sim/say", json={"text": t}, headers=H, timeout=20).json()["reply"]

    assert "water heater" in say("the main water valve is behind the water heater, guests can know")
    assert "Ravi" in say("my plumber is Ravi, 98300 11122, guests can call him")
    r = say("I bought a Bosch washing machine at Croma 5 days ago, 10 day return, 2 year warranty, papers in the blue file")
    assert "Saved Bosch washing machine" in r and "2026-10-27" in r
    assert "return window ends in 5 days" in say("what's closing")
    r = say("the washing machine is leaking water")
    assert "behind the water heater" in r and "Ravi" in r and "Bosch" in r
    assert "Here is a draft" in say("draft a claim for the washing machine, it leaks from the door")
    assert "Leave the house" in say("I smell gas")
    gc = say("make a guest code for 2 days")
    assert "Guest code" in gc
    code = gc.split("Guest code: ")[1].split(".")[0]
    g = login(url, "guest", "", code)["access_token"]
    GH = {"Authorization": f"Bearer {g}"}
    gsay = lambda t: httpx.post(url + "/sim/say", json={"text": t}, headers=GH, timeout=20).json()["reply"]
    assert "behind the water heater" in gsay("where is the water valve")
    assert "Ravi" in gsay("who do I call for the plumber") or "98300" in gsay("who do I call for the plumber")
    assert "water valve" not in gsay("who do I call for the plumber")
    assert "can't do that" in gsay("what's closing")
    assert "Bosch" not in gsay("where is the washing machine")
    shelf = httpx.get(url + "/sim/shelf", headers=H).json()
    assert shelf["closing"] and shelf["places"] and shelf["vendors"]
    assert "walk me" in say("zzz qqq").lower() or "I can save" in say("zzz qqq")
