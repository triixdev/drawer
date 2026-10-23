# Drawer

**Your household's memory, spoken.** Tell it where the water valve is and who your plumber is. When something breaks it tells you what to do first and whether you're still under warranty.

Drawer is a self-hosted MCP server for Alexa+, built for the Amazon Developer Hackathon. It is open source under the MIT license.

## Hackathon requirements at a glance

| Requirement | How Drawer meets it | Where to look |
|---|---|---|
| **Alexa+ track** | A self-hosted MCP server over Streamable HTTP. It registers 13 tools. | `drawer/server.py` |
| **MCP spec 2025-11-25 or later** | Built on the official Python SDK 2.3. Its latest supported protocol version is 2026-07-28. | `requirements.txt` |
| **Account linking** | OAuth 2.1 with PKCE (S256). Strangers get a bare 401. The metadata sits at `/.well-known/oauth-authorization-server`. The `resource` parameter is enforced. | `drawer/auth.py` |
| **Technology used at runtime** | `python -m drawer.server` starts the MCP server. The tests call it through a real MCP client. | `tests/test_e2e.py` |
| **Working demo** | A browser simulator at `/sim` calls the real MCP endpoint with the signed-in person's own token. | `drawer/sim.py` |
| **Open Source mini challenge** | A new public repo with an MIT license. The storage layer can be reused on its own. | `LICENSE`, `drawer/store.py` |
| **Run instructions** | Below. | this file |
| **Product feedback and friction log** | Written from what actually happened during the build. | `FRICTION_LOG.md` |

What this submission does **not** claim: the AWS Builder mini challenge, because my Amazon Bedrock access never worked. It also makes no claim of a test on a real Alexa+ device or account.

## See it work

This is real output from the simulator. The dates assume today is 2026-10-23.

```
YOU:    the main water valve is behind the water heater, guests can know
DRAWER: Got it. Main water valve is behind the water heater. Guests can ask about it.

YOU:    my plumber is Ravi, 98300 11122, guests can call him
DRAWER: Saved Ravi, plumber.

YOU:    I bought a Bosch washing machine at Croma 5 days ago, 10 day return,
        2 year warranty, papers in the blue file
DRAWER: Saved Bosch washing machine. Return window closes 2026-10-28, as you told me.
        Warranty runs to 2028-10-18, as you told me.

YOU:    the washing machine is leaking water
DRAWER: First, check the main water valve: it is behind the water heater. That looks
        like your Bosch washing machine from Croma. Warranty runs to 2028-10-18; you can
        still return it until 2026-10-28, as you told me. You kept the papers in the
        blue file. Call Ravi, 98300 11122. Want me to draft a claim message?

YOU:    I smell gas
DRAWER: Leave the house now and take everyone with you. Do not switch anything on or off.
        Do not use a lighter or a phone indoors if you smell gas. From outside, call your
        local emergency number.
```

Drawer never invents a return window or a warranty. It only uses the dates you gave it and says so each time. It drafts claim messages and never sends them.

## Run it

You need Python 3.12 or newer.

```
python -m venv venv
venv\Scripts\activate            (Windows)   or   source venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q              (expect: 8 passed)
```

Start the server. On Windows PowerShell use `$env:DRAWER_HOME="$PWD\data"` first. On Mac or Linux use `export DRAWER_HOME=data`.

```
python -m drawer.server
```

Open http://127.0.0.1:8000/sim. Click **Open your drawer** and choose **Start a new household**. Then click the sample lines under the input box.

To try the guest pass, say `make a guest code for 2 days`. Open a private window and sign in with **I have a guest code**. A guest can ask where the water valve is. A guest cannot ask what's closing.

## Why private facts are safe here

| Protection | How it works | Check it |
|---|---|---|
| Encrypted text | Names, places, phone numbers, notes and incidents are encrypted before they reach SQLite. | `test_full_story` opens the raw database file and finds none of them |
| One key per household | Each key is derived with HKDF from a master key kept outside the repo. | `drawer/store.py` |
| No shared identity | Every tool call verifies its own bearer token from the request headers. | `who()` in `drawer/server.py` |
| Hashed secrets | Passphrases use scrypt. Tokens and guest codes are stored only as SHA-256 hashes. | `drawer/store.py` |
| Scoped guests | A guest sees only entries marked guest-safe and loses access when passes end. | `test_full_story` |
| Isolation | A second household sees nothing of the first. | `test_full_story` |
| Deletion | `forget_everything` removes the household and revokes every token. | `test_full_story` |
| Fixed safety advice | Gas, smoke, fire and sparks get fixed text in code and no model writes it. | `drawer/triage.py` |

Dates and incident times stay readable so deadlines can be sorted. The privacy page at `/privacy` says so.

## The 13 tools

| Tool | What it does |
|---|---|
| `remember_purchase` | Saves an item with its return window and warranty |
| `remember_place` | Saves where something is, with an optional guest-safe flag |
| `remember_vendor` | Saves someone to call |
| `where_is` | Finds a place or a person to call |
| `whats_closing` | Lists return windows and warranties ending soon |
| `keep_or_return` | Asks about items whose return window closes within 3 days |
| `close_item` | Marks an item kept or returned |
| `something_wrong` | Answers when something breaks, in a fixed order |
| `draft_claim` | Drafts a claim message and never sends it |
| `what_happened` | Lists recent incidents, including ones a guest reported |
| `make_guest_pass` | Makes a temporary code for a house sitter |
| `end_guest_passes` | Ends every guest code at once |
| `forget_everything` | Deletes the household for good |

## Hosting a demo

These settings are read from the environment.

| Variable | Use |
|---|---|
| `DRAWER_PUBLIC_URL` | The public https address of the server |
| `DRAWER_KEY` | The master encryption key. Make one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DRAWER_CLIENTS` | Allowed sign-in clients, for example `drawer-sim::https://YOUR-HOST/sim` |
| `DRAWER_HOST` | Set to `0.0.0.0` on a hosting platform |
| `DRAWER_TRUST_PROXY` | Set to `1` behind a platform proxy so the sign-in rate limit sees real addresses |
| `DRAWER_MAX_HOUSEHOLDS` | Cap on new households. The default is 500. |
| `DRAWER_HOME` | Where the database and key file live |

Free hosting tiers often wipe local files when they restart. A hosted demo should be treated as disposable.

## Connecting to Alexa+

Set `DRAWER_PUBLIC_URL` and `DRAWER_CLIENTS` to the values Amazon gives you for account linking. Then follow Amazon's MCP quickstart. I have not tested this against a real Alexa+ account.

## Optional AI helper

`DRAWER_AI=bedrock` sends claim-draft requests to Amazon Bedrock after `drawer/redact.py` strips card numbers, emails, phone numbers, links and street addresses. It is a best-effort filter. Set `DRAWER_BEDROCK_MODEL` to a model your account can use. If the call fails Drawer falls back to a plain template. It is off by default. I could not get Bedrock access in time to run it against the real service, so it is tested only against a stand-in.

## Limits

- Return windows and warranty dates are exactly what you tell it.
- The simulator understands the sentence shapes in its sample lines. Anything else gets a short help reply.
- Drawer is a prototype and not an emergency service. It cannot call anyone.

## Layout

```
drawer/server.py   MCP server and the 13 tools
drawer/auth.py     OAuth 2.1 with PKCE and the auth gate
drawer/store.py    encrypted per-household storage (reusable)
drawer/triage.py   fixed-rule incident help
drawer/sim.py      the simulator backend
drawer/redact.py   personal detail filter for the optional AI helper
drawer/ai.py       optional Bedrock claim drafting with a template fallback
tests/             8 tests
```

License: MIT.
