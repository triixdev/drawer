from drawer import ai
from drawer.redact import scrub


def test_scrub_removes_personal_details():
    t = scrub("Call me on +91 98300 11122 or a.das@mail.com, card 4111 1111 1111 1111, "
              "Flat 4B, 22 Park Street, Kolkata 700016, PAN ABCDE1234F")
    for bad in ("98300", "a.das", "4111", "4B", "Park Street", "700016", "ABCDE"):
        assert bad not in t, t


def test_template_when_ai_off(monkeypatch):
    monkeypatch.delenv("DRAWER_AI", raising=False)
    text, src = ai.draft_claim({"name": "Bosch washing machine", "store": "Croma",
        "purchased_on": "2026-10-15", "problem": "it leaks from the door", "coverage": "warranty runs to 2028-10-15"})
    assert src == "template" and "Bosch" in text and "2028-10-15" in text


class Fake:
    def __init__(self): self.seen = None
    def converse(self, **kw):
        self.seen = kw
        return {"output": {"message": {"content": [{"text": "Hello Croma, my machine leaks. Please advise."}]}}}


def test_bedrock_path_sends_scrubbed_text(monkeypatch):
    monkeypatch.setenv("DRAWER_AI", "bedrock"); monkeypatch.setenv("DRAWER_BEDROCK_MODEL", "test-model")
    fake = Fake()
    text, src = ai.draft_claim({"name": "Bosch washing machine", "store": "Croma", "purchased_on": "2026-10-15",
        "problem": "leaks, call 98300 11122 or a@b.com"}, client=fake)
    sent = fake.seen["messages"][0]["content"][0]["text"]
    assert src == "bedrock" and "98300" not in sent and "a@b.com" not in sent and fake.seen["modelId"] == "test-model"


def test_bedrock_failure_falls_back(monkeypatch):
    monkeypatch.setenv("DRAWER_AI", "bedrock"); monkeypatch.setenv("DRAWER_BEDROCK_MODEL", "x")
    class Boom:
        def converse(self, **kw): raise RuntimeError("no access")
    _, src = ai.draft_claim({"name": "Kettle", "purchased_on": "2026-10-01", "problem": "dead"}, client=Boom())
    assert src == "template"
