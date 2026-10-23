# Drawer

Your household's memory, spoken. Drawer is a self-hosted MCP server (Streamable HTTP, OAuth 2.1 with PKCE)
built for the Alexa+ track of the Amazon Developer Hackathon.

You tell it where the water valve is, who your plumber is, and what you bought with its return window and
warranty. When something breaks, you ask what to do. It answers with the saved shutoff location, the item,
whether it is still covered, where you kept the papers, and who to call, and it can draft (never send) a
claim message. A house sitter can get a temporary guest code that opens only the entries you marked guest-safe.

## Run it

Python 3.12 or newer.

    python -m venv venv
    venv\Scripts\activate          (Windows)   or   source venv/bin/activate
    pip install -r requirements.txt pytest
    python -m pytest -q            (expect 8 passed)

    set DRAWER_HOME=data           (Windows: $env:DRAWER_HOME="$PWD\data" in PowerShell)
    python -m drawer.server

Open http://127.0.0.1:8000/sim for the simulator. Create a household, then click the sample lines.
The simulator is a rules-based stand-in for the voice assistant. It calls the real MCP endpoint with the
signed-in person's own token. No AI model is involved.

## Tools

remember_purchase, remember_place, remember_vendor, where_is, whats_closing, keep_or_return, close_item,
something_wrong, draft_claim, what_happened, make_guest_pass, end_guest_passes, forget_everything.

## How the data is protected

- Names, stores, places, phone numbers, notes and incidents are encrypted (Fernet) before they reach SQLite.
- Each household has its own key, derived with HKDF from a master key. The master key comes from
  DRAWER_KEY or a 0600 file under DRAWER_HOME. It is never in the repository.
- Dates and incident times are stored readable so deadlines can be sorted. The privacy page says so.
- Passphrases are scrypt hashes. Tokens, auth codes and guest codes are stored only as SHA-256 hashes.
- Every tool call checks its own bearer token from the request headers. There is no shared identity state.
- Strangers get a bare 401 on /mcp. Redirect URIs must match exactly, PKCE S256 is required, and the
  `resource` parameter must equal this server's /mcp address.
- Guests see only entries marked guest-safe, cannot call owner tools, and lose access when the owner ends passes.
- forget_everything deletes the household, every entry, incident, code and token, then compacts the file.
- Safety advice for gas, smoke, fire and sparks is fixed text in code (drawer/triage.py), never model output.
- The tests assert that the raw database file contains none of the saved names, places or phone numbers.

## Optional AI helper (off by default)

DRAWER_AI=bedrock sends a claim-draft request to Amazon Bedrock after drawer/redact.py strips card numbers,
emails, phones, links and street addresses (best effort). Set DRAWER_BEDROCK_MODEL to a model or inference
profile ID that your account can use, plus AWS credentials or AWS_BEARER_TOKEN_BEDROCK. If the call fails,
Drawer falls back to a plain template. See SUBMISSION.md for the status of this feature.

## Connecting to Alexa+

Set DRAWER_PUBLIC_URL to the public HTTPS address of this server, and DRAWER_CLIENTS to
`clientid:secret:https://redirect1|https://redirect2` for the client Amazon gives you. Then follow Amazon's
MCP quickstart. This path is not tested against a real Alexa+ account.

## Reusable part

drawer/store.py is a small encrypted, per-household store with scoped tokens and expiring guest codes. It has
no dependency on the rest of the app, and it is meant to be lifted into other MCP servers.

## Limits

Return windows and warranty dates are exactly what you tell it. Drawer never invents one. It is a prototype,
not an emergency service, and it cannot call anyone.

License: MIT.
