"""Optional AI helper, off by default.

DRAWER_AI=bedrock turns it on. Text is scrubbed first (see redact.py), and
only the minimum goes out: item, store, dates and the problem in one line.
With it off, a plain template writes the draft and nothing leaves the server.
"""
import os

from .redact import scrub

SYSTEM = ("You write short, polite warranty claim messages for a customer. Use only the facts given. "
          "Never invent order numbers, prices or promises. Three to five sentences. Plain text.")


def template(f: dict) -> str:
    lines = [f"Hello {f.get('store') or 'team'},",
             f"I bought a {f['name']} on {f['purchased_on']}. {f['problem'].rstrip('.').capitalize()}."]
    if f.get("coverage"):
        lines.append(f"Under the terms I was given, {f['coverage']}.")
    lines.append("Please tell me how to start a claim and what you need from me.")
    return " ".join(lines)


def _bedrock_text(prompt: str, client=None) -> str:
    model = os.environ.get("DRAWER_BEDROCK_MODEL")
    if not model:
        raise RuntimeError("Set DRAWER_BEDROCK_MODEL to a model enabled in your AWS account.")
    if client is None:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    r = client.converse(modelId=model, system=[{"text": SYSTEM}],
                        messages=[{"role": "user", "content": [{"text": prompt}]}],
                        inferenceConfig={"maxTokens": 300, "temperature": 0.3})
    return r["output"]["message"]["content"][0]["text"].strip()


def draft_claim(facts: dict, client=None) -> tuple[str, str]:
    """Returns (draft, source) where source is 'bedrock' or 'template'."""
    safe = {k: scrub(str(v)) for k, v in facts.items() if v}
    if os.environ.get("DRAWER_AI") == "bedrock":
        prompt = (f"Item: {safe['name']}\nStore: {safe.get('store','unknown')}\nBought: {safe['purchased_on']}\n"
                  f"Problem: {safe['problem']}\nCoverage the customer stated: {safe.get('coverage','none stated')}")
        try:
            return _bedrock_text(prompt, client), "bedrock"
        except Exception:
            pass  # fall back to the template rather than fail while something is broken
    return template(safe), "template"
