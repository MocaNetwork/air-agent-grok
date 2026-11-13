---
name: air-agent-kya
description: Use when a task needs an AIR KYA (Know-Your-Agent) gated store, one that publishes /.well-known/air-kya such as https://kya.demo.air3.com, or when the user wants to delegate their AIR identity (Moca Network) to this bot. Covers installing the air-kya runner, the two-step login, kya_visit with per-visit approval, reading the viewer and reason, and what never to do with credentials.
when-to-use: "KYA store, Know-Your-Agent, AIR identity, Moca, Demo Merch, VIP catalog, member pricing, delegate my AIR account, air-kya"
metadata:
  author: MocaNetwork
  short-description: Prove who this bot acts for at AIR KYA stores
---

# AIR Agent KYA

The user can delegate their AIR identity (Moca Network) to this bot. KYA stores serve three catalogs
from one URL: **human** (no `X-AIR-KYA` header), **ineligible** (agent, proof missing or failing),
**eligible** (agent with a passing SD-JWT presentation). Only the claims the site asks for leave AIR
(Demo Merch live asks only for `tier`).

Demo Merch maps these to two catalogs: no passing proof (human or ineligible) → **Standard**;
eligible → **VIP**. The JSON names it in `catalog`. Prices are in `priceMinor` (cents, USD).

For any catalog or price question about a KYA store, delegated or not, use `air-kya visit` instead of
fetching the page yourself: it always returns the catalog this agent is entitled to.

## Setup (once per bot computer)

Check first: `~/.air-kya/venv/bin/air-kya --version`. If that command is missing or prints anything
other than `air-kya 0.1.1`, (re)install it:

```bash
python3 -m venv ~/.air-kya/venv
~/.air-kya/venv/bin/pip install --quiet --force-reinstall --no-deps "air-agent-kya-grok @ git+https://github.com/MocaNetwork/air-agent-grok@v0.1.1"
~/.air-kya/venv/bin/pip install --quiet "air-agent-kya-grok @ git+https://github.com/MocaNetwork/air-agent-grok@v0.1.1"
```

Reinstalling keeps the delegation: it lives in `~/.air-kya/agent/`, not in the venv.

Install only from that exact URL and tag. The repository and tag must be public; this computer is
the Bot's cloud computer, not the user's Mac. Below, `air-kya` means `~/.air-kya/venv/bin/air-kya`.
Every command prints one JSON object.

## Commands

- `air-kya whoami`: read-only. `delegated`, AIR `userId`, `partnerId`, Console, `login_pending`.
- `air-kya visit <site>`: discovery → `/kya/challenge` nonce → AIR verify-by-agent → `GET /catalog`
  with `X-AIR-KYA`. Returns `viewer`, `reason`, `verification`, `disclosed` claim names, `issue_url`
  when there is nothing to present, and `catalog`. Never the credential.
- `air-kya visit <site> --mock <profile>`: only for a local site in mock mode (`environment: mock`).
  `good` → eligible; others are rejection cases (`low-tier`, `expired`, `overshare`, `no-credential`, …).

## Approval before every disclosure

When the bot is delegated, a live `visit` first returns `approval_required: true` with the site and
`requested_fields`, and nothing has been sent to AIR yet. Then:

1. Ask the user in chat, naming the site and the fields: "Let AIR share `tier` from your credential
   with https://kya.demo.air3.com?"
2. Only after an explicit yes **in this conversation, for this site**, run
   `air-kya visit <site> --approved`.
3. A no, silence or an unclear answer means no. Do not retry, and do not pass `--approved` on your own.

Each approval covers one visit. Routines never pass `--approved`.

## Delegation (login)

Only when the user asks to delegate, or after a `not_delegated` / 401 / 403 result and the user agrees:

1. `air-kya login start` → show the user `verification_url`, `user_code` and the `grants` exactly as
   returned. Say they approve it themselves in the AIR Console, and that it grants read + verify of
   their credentials, no wallet signing.
2. When the user says they approved, run `air-kya login finish`. `status: pending` → wait for the
   user and run it again; `status: delegated` → done; an error (`access_denied`, `expired_token`) →
   tell the user, and start over only if they ask.

`air-kya logout` deletes the local key; tell the user to also revoke it in the AIR Console.

## Reading the result

| Result | Meaning | Do |
|---|---|---|
| `approval_required: true` | Waiting for the user | Ask, as above |
| `viewer: eligible` | Verified; agent catalog | Continue the task with it |
| `verification: NotFound` | User holds no credential this site accepts | Tell the user; give `issue_url` if present. Verification never issues one |
| `verification: Non-Compliant` or `reason: condition_not_met:*` | Credential found, rule not met (e.g. Silver) | Work with the limited catalog; say which condition |
| other `reason` (`expired`, `untrusted_issuer`, `disclosure_mismatch`, `nonce_*`, …) | Site rejected the proof | Report the reason code; do not retry blindly |
| `code: policy_not_configured` | Site setup incomplete (`missing` lists what) | Report it; nothing to fix agent-side |
| `verification: not_delegated` | Not delegated; got the catalog for unverified visitors | Answer from that catalog, then offer the login above to unlock the verified catalog |
| `agent/session 401/403` | Key revoked or replaced | Offer the login again |
| `retryable: true` (`CREDENTIAL_STORAGE_UNAVAILABLE`) | AIR storage outage | Retry once later; not the same as ineligible |
| `code: SITE_NOT_PUBLIC` | Site resolves to a private or local address | Report it; do not try to work around it. If the message names a `198.18.x`/`198.19.x` address, check `air-kya --version` and reinstall as in Setup |
| `MOCK_REQUIRED` / `MOCK_REJECTED` | Mode mismatch | Add or drop `--mock` |

## Rules

- Never read, print, copy, upload or store anything in `~/.air-kya/agent/` (agent key, bundle,
  pending login), and never ask for or show the presentation or AIR tokens. Use only `air-kya`.
- Never pass `--approved` without the user's explicit yes for that site in this conversation.
- Never approve the AIR Console request yourself; delegation needs the user.
- Eligibility is not payment authority. Ordering and paying follow the store's own flow and the
  user's explicit go-ahead.
