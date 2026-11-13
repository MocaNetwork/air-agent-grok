"""`air-kya` (or `python -m air_kya`): the commands the Grok Bot skill runs.

Every command prints exactly one JSON object on stdout. Exit code 0 on success (including `pending` and
`approval_required`), 1 on error. Settings come from AIR_KYA_* environment variables, all optional.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from . import __version__, air
from .kya import MOCK_PROFILES, ApprovalRequired, VisitError, site_client, visit

DEFAULT_AGENT_LABEL = "Grok Bot (AIR Agent KYA)"
ENDPOINT_SETTINGS = ("partner_id", "console_url", "api_url", "credential_api_url")
TRUE = {"1", "true", "yes", "on"}
MAX_WAIT = 600.0


def setting(name: str, default: str = "") -> str:
    return os.environ.get(f"AIR_KYA_{name.upper()}", default).strip()


def flag(name: str, default: bool) -> bool:
    value = setting(name)
    return default if not value else value.lower() in TRUE


def _env() -> air.AirEnv:
    return air.air_env({k: setting(k) for k in ENDPOINT_SETTINGS})


def _dir():
    return air.agent_dir(setting("dir") or None)


def _air_client(timeout: float = 20.0) -> httpx.Client:
    """Client for AIR endpoints (from settings, not the model). Model-chosen sites use `site_client`."""
    return httpx.Client(timeout=timeout, follow_redirects=False)


# --------------------------------------------------------------------------- commands


def whoami() -> dict:
    directory, env = _dir(), _env()
    d = air.load_delegation(directory)
    pending = (directory / air.PENDING_FILE).exists()
    if not d:
        return {"delegated": False, "login_pending": pending, "console": env.console_url,
                "hint": f"To delegate, {air.LOGIN_HINT}."}
    return {"delegated": True, "userId": d.user_id, "partnerId": d.partner_id(env), "console": env.console_url,
            "login_pending": pending}


def login_start(name: str) -> dict:
    with _air_client(15.0) as http:
        out = air.login_start(_env(), name, http=http, directory=_dir())
    out["next"] = ("Show the user verification_url and user_code. After they say they approved, "
                   "run `air-kya login finish`.")
    return out


def login_finish(wait: float) -> dict:
    with _air_client(15.0) as http:
        return air.login_poll(_env(), http=http, directory=_dir(), wait=max(0.0, min(wait, MAX_WAIT)))


def logout() -> dict:
    air.logout(_dir())
    return {"delegated": False, "note": "Local agent key removed. Also revoke the key in the AIR Console."}


def run_visit(site: str, mock: str | None, approved: bool) -> dict:
    # The model picks `site`: those requests only reach public addresses (loopback too in mock mode or with
    # AIR_KYA_ALLOW_LOCAL_SITES). AIR endpoints come from settings, so they keep a plain client.
    allow_local = bool(mock) or flag("allow_local_sites", False)
    # On by default: the Grok Bot computer resolves every hostname into 198.18.0.0/15 behind its egress proxy.
    allow_fake_ip = flag("allow_proxy_fake_ip", True)
    ask = flag("require_approval", True) and not approved

    def confirm(info: dict) -> None:
        if not ask:
            return
        claims = ", ".join(info["requested_fields"]) or "the claims it requests"
        raise ApprovalRequired({
            "approval_required": True, **info,
            "message": (f"Ask the user: \"Let AIR share {claims} from your credential with {info['site']}?\" "
                        "Only after an explicit yes in this chat, run the same visit with --approved. "
                        "A no means no; do not retry."),
        })

    with _air_client() as http, site_client(allow_local=allow_local, allow_fake_ip=allow_fake_ip) as site_http:
        try:
            return visit(site, http=http, site_http=site_http, mock=mock, env=_env(),
                         delegation=air.load_delegation(_dir()),
                         mock_air_url=setting("mock_air_url") or air.MOCK_AIR_URL,
                         allow_local=allow_local, confirm=confirm)
        except ApprovalRequired as exc:
            return exc.details


# --------------------------------------------------------------------------- argparse


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="air-kya", description="AIR Agent KYA for Grok Bot. Prints JSON.")
    p.add_argument("--version", action="version", version=f"air-kya {__version__}")
    subs = p.add_subparsers(dest="command", required=True)
    subs.add_parser("whoami", help="Show the stored delegation")
    p_login = subs.add_parser("login", help="Delegate the user's AIR identity (two steps)")
    login_subs = p_login.add_subparsers(dest="step", required=True)
    p_start = login_subs.add_parser("start", help="Get an AIR Console URL + code for the user to approve")
    p_start.add_argument("--name", default=DEFAULT_AGENT_LABEL, help="Agent label shown in the Console")
    p_finish = login_subs.add_parser("finish", help="Wait for the user's approval and store the delegation")
    p_finish.add_argument("--wait", type=float, default=120.0, help=f"Seconds to wait (max {int(MAX_WAIT)})")
    subs.add_parser("logout", help="Delete the local agent key (also revoke it in the AIR Console)")
    p_visit = subs.add_parser("visit", help="Enter a KYA site and return its catalog")
    p_visit.add_argument("site")
    p_visit.add_argument("--mock", choices=MOCK_PROFILES, help="Local mock-mode site only")
    p_visit.add_argument("--approved", action="store_true",
                         help="The user explicitly approved this disclosure in chat")
    return p


def run(args: argparse.Namespace) -> dict:
    if args.command == "whoami":
        return whoami()
    if args.command == "login":
        return login_start(args.name) if args.step == "start" else login_finish(args.wait)
    if args.command == "logout":
        return logout()
    return run_visit(args.site, args.mock, args.approved)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        out, code = run(args), 0
    except VisitError as exc:
        out, code = {"error": str(exc), **exc.extra}, 1
    except air.AirError as exc:
        out, code = {"error": str(exc), "code": exc.code, "retryable": exc.retryable}, 1
    except httpx.HTTPError as exc:
        out, code = {"error": f"{type(exc).__name__}: {exc}"}, 1
    print(json.dumps(out, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
