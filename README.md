# AIR Agent KYA: Grok Bot template

Lets a Grok Bot prove who it acts for. You delegate your AIR identity (Moca Network) to the bot
once, approving it in the AIR Console. When the bot visits a Know-Your-Agent (KYA) store, AIR issues
a one-time proof that discloses only the claim the store asks for (for example your membership
tier). The store checks it and returns the catalog your credential unlocks: public pricing for
everyone, VIP for verified members.

Grok Bot port of [MocaNetwork/air-agent-hermes](https://github.com/MocaNetwork/air-agent-hermes),
which ports the agent in [mocaverse/air-kya](https://github.com/mocaverse/air-kya). Same protocol,
endpoints and headers.

- Demo store: https://kya.demo.air3.com
- License: MIT

## What's here

| Path | What it is |
|---|---|
| `bot/description.md` | The bot's description and standing rules. Paste into the Grok Bot |
| `bot/skills/air-agent-kya/SKILL.md` | The skill: install, login, visit, approval, reading results |
| `air_kya/` | The runner the skill installs on the bot's computer (`air-kya`, or `python -m air_kya`) |
| `tests/` | Offline tests (`pytest`) |

A Grok Bot template carries the description, skills and routines, not code. So the skill installs
`air_kya` from this repo on first use, into `~/.air-kya/venv` on the bot's cloud computer.

## Publish the template

1. Push this folder to `github.com/MocaNetwork/air-agent-grok` (public) and tag `v0.1.0`. The skill
   installs from exactly that URL and tag; change both in `SKILL.md` if you use another location.
2. In Grok Bot, create a bot named **AIR Agent KYA** and paste `bot/description.md` (below the line)
   as its description.
3. Add the skill: upload `bot/skills/air-agent-kya/SKILL.md` (or the folder zipped).
4. Test with the bot (below), then **Share as template** from the bot's settings. Review the draft:
   it must contain no keys, tokens or internal URLs. Publish for your team or publicly.

Releasing a new version: tag it, update the tag in `SKILL.md`, then update the bot and re-share.

## Try it in the bot

1. "What does Demo Merch sell and at what prices? https://kya.demo.air3.com": the bot installs the
   runner, visits, and answers from the Standard catalog (`verification: not_delegated`).
2. "Delegate my AIR identity": the bot runs `air-kya login start` and shows a Console link and
   code. Approve it there, tell the bot, and it runs `air-kya login finish`.
3. "Check Demo Merch's catalog again": the bot asks before AIR shares `tier`. Say yes and it shows
   the VIP catalog (needs Gold Membership).

## Commands

All print one JSON object; exit code 1 on error.

| Command | What it does |
|---|---|
| `air-kya whoami` | Stored delegation: `delegated`, `userId`, `partnerId`, Console, `login_pending` |
| `air-kya login start [--name <label>]` | New P-256 agent key + AIR Console device code. Returns `verification_url` and `user_code` for the user. Default label: `Grok Bot (AIR Agent KYA)` |
| `air-kya login finish [--wait <s>]` | Waits up to `--wait` seconds (default 120, max 600) for approval; `pending` means call again. Stores key + bundle (0600) |
| `air-kya logout` | Delete the local key, bundle and any pending login. Also revoke the key in the AIR Console |
| `air-kya visit <site>` | KYA handshake. If delegated, first returns `approval_required` without contacting AIR |
| `air-kya visit <site> --approved` | Same, after the user said yes: discloses and returns the catalog |
| `air-kya visit <site> --mock <profile>` | Against a local mock-mode site using `npm run mock-air` |

Mock profiles: `good`, `low-tier`, `wrong-class`, `expired`, `bad-signature`, `untrusted-issuer`,
`wrong-vct`, `missing-disclosure`, `overshare`, `unbound`, `no-credential`.

## Settings

Environment variables, all optional. Empty endpoint settings use the AIR sandbox; the delegation
bundle's `partnerId` wins over `AIR_KYA_PARTNER_ID`.

| Variable | Default |
|---|---|
| `AIR_KYA_REQUIRE_APPROVAL` | `1`: a delegated live visit stops with `approval_required` until run with `--approved` |
| `AIR_KYA_ALLOW_LOCAL_SITES` | `0`: allow localhost sites outside mock mode (private and link-local stay blocked) |
| `AIR_KYA_DIR` | `~/.air-kya/agent` |
| `AIR_KYA_PARTNER_ID` | AIR AI Studio sandbox partner `8ab60850-bdfa-4e48-8afa-d67a3d715224` |
| `AIR_KYA_CONSOLE_URL` | `https://sandbox.agents.air3.com` |
| `AIR_KYA_API_URL` | `https://air.api.sandbox.air3.com/v2` |
| `AIR_KYA_CREDENTIAL_API_URL` | `https://credential-testnet.api.sandbox.air3.com` |
| `AIR_KYA_MOCK_AIR_URL` | `http://127.0.0.1:8799` (mock-mode sites only) |

## Disclosures

Read before adding the template:

- **Installs code:** on first use the bot creates `~/.air-kya/venv` and installs this repo's tagged
  release and its dependencies (`httpx`, `httpcore`, `cryptography`) from GitHub and PyPI.
- **Network calls:** the AIR Console (`sandbox.agents.air3.com`, during login only), the AIR API
  (`air.api.sandbox.air3.com`) and credential API (`credential-testnet.api.sandbox.air3.com`), and
  each KYA site the bot visits (`/.well-known/air-kya`, `/kya/challenge`, `/catalog`). Sites: https
  only, public addresses only; each connection resolves the host, refuses private, loopback,
  link-local and cloud-metadata addresses, and connects to the address it checked.
- **Stored credentials:** a P-256 agent private key and the AIR delegation bundle in
  `~/.air-kya/agent/`, mode 0600, on the bot's cloud computer. `air-kya logout` deletes them; revoke
  the key in the AIR Console too.
- **Weaker than the Hermes plugin, by design of the platform:**
  - *Approval is enforced by the bot, not the platform.* Grok Bot has no tool-approval gate. The
    runner stops before every live disclosure and the skill tells the bot to ask you, but the bot
    itself passes `--approved`. It discloses only the fields the site requests, only to the origin
    that issued the nonce.
  - *The key is readable by every bot on your account.* All Grok Bots on an account share one cloud
    computer. File permissions don't separate them, and the bot could read the key if it ignored its
    rules. Delegate only to an account whose bots you trust, and revoke the key in the AIR Console
    if in doubt.
  - *The bot starts login.* It can't complete it: only you can approve in the AIR Console.
- **Does not:** sign transactions, pay, run background processes, read other credential stores, or
  send telemetry.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests -q
```

`air_kya/air.py` and `air_kya/kya.py` come from air-agent-hermes at commit `1755c4b`, with the
Hermes-specific parts replaced: key directory, hints, two-step login, and the approval checkpoint.
Port protocol fixes in both directions.
