"""AIR Agent KYA for Grok Bot offline tests: AIR Console, AIR APIs and the KYA demo site mocked with
httpx.MockTransport. Ported from the air-agent-hermes test suite.

Run from the repo root:  python -m pytest tests -q
"""

import base64
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

import httpcore
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from air_kya import air, cli, kya  # noqa: E402
from air_kya.kya import ApprovalRequired, VisitError, visit  # noqa: E402

SITE = "https://shop.example"
USER = "018f9a2b-7c3d-7e10-9a4b-2c1d5e6f7a8b"
BUNDLE_PARTNER = "11111111-2222-4333-8444-555555555555"
DISC = base64.urlsafe_b64encode(json.dumps(["salt", "tier", "Gold"]).encode()).decode().rstrip("=")
SDJWT = f"data:application/dc+sd-jwt,eyJiss.jwt~{DISC}~eyJkb.jwt"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """AIR_KYA_* settings as the bot's shell would set them; the agent dir points at a temp dir."""
    for name in ("REQUIRE_APPROVAL", "ALLOW_LOCAL_SITES", "PARTNER_ID", "CONSOLE_URL", "API_URL",
                 "CREDENTIAL_API_URL", "MOCK_AIR_URL"):
        monkeypatch.delenv(f"AIR_KYA_{name}", raising=False)
    monkeypatch.setenv("AIR_KYA_DIR", str(tmp_path))
    return tmp_path


def delegate(store, partner=BUNDLE_PARTNER):
    key = ec.generate_private_key(ec.SECP256R1())
    (store / air.KEY_FILE).write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
    bundle = {"agentPublicKey": air.public_pem(key), "userId": USER}
    if partner:
        bundle["partnerId"] = partner
    (store / air.BUNDLE_FILE).write_text(json.dumps(bundle))
    return air.load_delegation(store)


def site_and_air(*, environment="sandbox", configured=True, verify=None, verify_only_ok=True, seen=None):
    seen = seen if seen is not None else {}
    verify = verify or {"verificationResult": {"status": "Compliant",
                                               "verifiablePresentation": {"verifiableCredential": [{"id": SDJWT}]}}}

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u == f"{SITE}/.well-known/air-kya":
            d = {"environment": environment, "programId": "01M6WS5Y09GJ5ZSZ6Q3BEQ", "fieldsToDisclose": ["tier"],
                 "issueUrl": "https://issue.example/gold"}
            if not configured:
                d.update(configured=False, missing=["programId"])
            return httpx.Response(200, json=d)
        if u == f"{SITE}/kya/challenge" and req.method == "POST":
            return httpx.Response(200, json={"nonce": "3f1a9c8e-2b7d-4f60-a1c5-e9b8d7f6a4c2"})
        if u.endswith("/v2/auth/agent/session"):
            body = json.loads(req.content)
            seen.setdefault("sessions", []).append({"body": body, "partner": req.headers.get("x-partner-id")})
            if body["scope"] == air.MERCHANT_SESSION_SCOPE and not verify_only_ok:
                return httpx.Response(403, json={"code": "AGENT_SCOPE_DENIED", "message": "no"})
            return httpx.Response(200, json={"accessToken": "agent.jwt", "user": {"id": USER}})
        if u.endswith("/v2/credentials/verify-by-agent"):
            seen["verify"] = json.loads(req.content)
            seen["auth"] = req.headers.get("authorization")
            return httpx.Response(200, json=verify)
        if u == f"{SITE}/catalog":
            pres = req.headers.get("X-AIR-KYA")
            seen["header"] = pres
            viewer = "human" if pres is None else ("eligible" if pres else "ineligible")
            return httpx.Response(200, json={"viewer": viewer, "products": [{"sku": viewer}]},
                                  headers={"X-AIR-Viewer": viewer, "X-AIR-Reason": "r", "X-AIR-Disclosed": "tier"})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


# ------------------------------------------------------------------ delegation


class Console:
    """AIR Console device-code endpoints. `approve_after` token polls stay pending, then approve."""

    def __init__(self, approve_after=1, swap_key=False, error=None, expires_in=600):
        self.calls, self.pub = [], None
        self.approve_after, self.swap_key, self.error, self.expires_in = approve_after, swap_key, error, expires_in

    def __call__(self, req):
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        self.calls.append(req.url.path)
        if req.url.path == "/api/oauth/device/code":
            assert form["client_id"] == "air-agent-broker"
            assert form["scope"] == "openid credentials.read credentials.verify"
            assert form["agent_public_key"].startswith("-----BEGIN PUBLIC KEY-----")
            self.pub = form["agent_public_key"]
            return httpx.Response(200, json={"device_code": "dc", "user_code": "ABCD", "verification_uri": "https://c/x",
                                             "expires_in": self.expires_in, "interval": 0})
        assert form["device_code"] == "dc"
        if self.error:
            return httpx.Response(400, json={"error": self.error})
        if self.calls.count("/api/oauth/token") <= self.approve_after:
            return httpx.Response(400, json={"error": "authorization_pending"})
        pub = "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----" if self.swap_key else self.pub
        return httpx.Response(200, json={"agentPublicKey": pub, "userId": USER, "partnerId": BUNDLE_PARTNER})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 1)


def test_two_step_login(store):
    console, clock = Console(approve_after=2), Clock()
    out = air.login_start(air.air_env(), "t", http=console.client(), directory=store, now=clock)
    assert out["status"] == "awaiting_approval" and out["user_code"] == "ABCD" and out["verification_url"] == "https://c/x"
    assert "key" not in out and "device_code" not in out  # the model never sees the key or device code
    assert oct((store / air.PENDING_FILE).stat().st_mode & 0o777) == "0o600"
    assert air.load_delegation(store) is None

    # wait=0: one poll, still pending
    assert air.login_poll(air.air_env(), http=console.client(), directory=store, wait=0, sleep=clock.sleep,
                          now=clock)["status"] == "pending"
    done = air.login_poll(air.air_env(), http=console.client(), directory=store, wait=60, sleep=clock.sleep, now=clock)
    assert done == {"status": "delegated", "userId": USER, "partnerId": BUNDLE_PARTNER}
    assert oct((store / air.KEY_FILE).stat().st_mode & 0o777) == "0o600"
    assert air.load_delegation(store).public_key_pem == console.pub
    assert not (store / air.PENDING_FILE).exists()


def test_login_rejects_swapped_key(store):
    console, clock = Console(approve_after=0, swap_key=True), Clock()
    air.login_start(air.air_env(), "t", http=console.client(), directory=store, now=clock)
    with pytest.raises(air.AirError, match="different agent public key"):
        air.login_poll(air.air_env(), http=console.client(), directory=store, sleep=clock.sleep, now=clock)
    assert not (store / air.KEY_FILE).exists() and not (store / air.PENDING_FILE).exists()


def test_login_denied_and_expired(store):
    clock = Clock()
    console = Console(error="access_denied")
    air.login_start(air.air_env(), "t", http=console.client(), directory=store, now=clock)
    with pytest.raises(air.AirError) as exc:
        air.login_poll(air.air_env(), http=console.client(), directory=store, sleep=clock.sleep, now=clock)
    assert exc.value.code == "access_denied" and not (store / air.PENDING_FILE).exists()

    console = Console(approve_after=99, expires_in=5)
    air.login_start(air.air_env(), "t", http=console.client(), directory=store, now=clock)
    with pytest.raises(air.AirError, match="expired"):
        air.login_poll(air.air_env(), http=console.client(), directory=store, wait=60, sleep=clock.sleep, now=clock)
    assert not (store / air.PENDING_FILE).exists()


def test_login_finish_without_start(store):
    with pytest.raises(air.AirError) as exc:
        air.login_poll(air.air_env(), http=Console().client(), directory=store)
    assert exc.value.code == "NO_PENDING_LOGIN"


def test_new_login_keeps_old_delegation_until_approved(store):
    old = delegate(store)
    console, clock = Console(approve_after=99), Clock()
    air.login_start(air.air_env(), "t", http=console.client(), directory=store, now=clock)
    assert air.login_poll(air.air_env(), http=console.client(), directory=store, wait=0, sleep=clock.sleep,
                          now=clock)["status"] == "pending"
    assert air.load_delegation(store).public_key_pem == old.public_key_pem


# ------------------------------------------------------------------ session + verify


def test_signed_message_pem_and_monotonic(store):
    d = delegate(store)
    a, b = air.signed_message(d, now=1700000000), air.signed_message(d, now=1700000000)
    assert a["message"] == f"{d.public_key_pem}:{USER}:{int(a['message'].rsplit(':', 1)[1])}"
    assert a["publicKey"].startswith("-----BEGIN PUBLIC KEY-----")
    assert int(b["message"].rsplit(":", 1)[1]) > int(a["message"].rsplit(":", 1)[1])
    d.key.public_key().verify(base64.b64decode(a["signature"]), a["message"].encode(), ec.ECDSA(hashes.SHA256()))


def test_live_visit_presents_and_hides_token(store):
    d = delegate(store)
    http, seen = site_and_air()
    r = visit(SITE, http=http, delegation=d)
    assert r["viewer"] == "eligible" and r["presented"] and r["disclosed"] == ["tier"]
    assert seen["header"] == SDJWT  # data URL forwarded as-is
    assert seen["verify"] == {"programId": "01M6WS5Y09GJ5ZSZ6Q3BEQ", "fieldsToDisclose": ["tier"],
                              "nonce": "3f1a9c8e-2b7d-4f60-a1c5-e9b8d7f6a4c2"}
    assert seen["sessions"][0]["partner"] == BUNDLE_PARTNER
    assert seen["sessions"][0]["body"]["scope"] == "openid credentials.verify"
    assert SDJWT not in json.dumps(r) and "agent.jwt" not in json.dumps(r)


def test_partner_fallback_and_scope_fallback(store):
    d = delegate(store, partner=None)
    http, seen = site_and_air(verify_only_ok=False)
    visit(SITE, http=http, delegation=d)
    assert [s["body"]["scope"] for s in seen["sessions"]] == [air.MERCHANT_SESSION_SCOPE, air.FULL_SESSION_SCOPE]
    assert seen["sessions"][0]["partner"] == air.SANDBOX["partner_id"]


def test_vp_token_shape(store):
    http, seen = site_and_air(verify={"verificationResult": {"status": "Compliant"},
                                      "vp_token": {"01M6WS5Y09GJ5ZSZ6Q3BEQ": ["compact~x~kb"]}})
    visit(SITE, http=http, delegation=delegate(store))
    assert seen["header"] == "compact~x~kb"


def test_not_found_sends_empty_header(store):
    http, seen = site_and_air(verify={"verificationResult": {"status": "NotFound"}})
    r = visit(SITE, http=http, delegation=delegate(store))
    assert seen["header"] == "" and r["viewer"] == "ineligible"
    assert r["issue_url"] == "https://issue.example/gold"


def test_guards(store):
    http, _ = site_and_air()
    with pytest.raises(VisitError, match="live AIR issuer"):
        visit(SITE, http=http, mock="good")
    http, _ = site_and_air(environment="mock")
    with pytest.raises(VisitError, match="mock issuer"):
        visit(SITE, http=http, delegation=delegate(store))
    http, seen = site_and_air(configured=False)
    with pytest.raises(VisitError, match="not configured"):
        visit(SITE, http=http, delegation=delegate(store))
    assert "header" not in seen
    with pytest.raises(VisitError):
        visit("http://not-local.example", http=http)


def test_not_delegated_gets_unverified_catalog(store):
    http, seen = site_and_air()
    r = visit(SITE, http=http)
    assert seen["header"] == "" and "sessions" not in seen and "verify" not in seen
    assert r["viewer"] == "ineligible" and r["verification"] == "not_delegated" and "air-kya login start" in r["note"]


def test_mock_mode_uses_mock_air(store):
    http, seen = site_and_air(environment="mock")
    visit(SITE, http=http, mock="good", mock_air_url="http://127.0.0.1:8799")
    assert seen["auth"] == "Bearer mock-agent:good" and "sessions" not in seen


# ------------------------------------------------------------------ approval checkpoint


def refuse(info):
    raise ApprovalRequired({"approval_required": True, **info})


def test_confirm_runs_before_nonce_or_air(store):
    http, seen = site_and_air()
    with pytest.raises(ApprovalRequired) as exc:
        visit(SITE, http=http, delegation=delegate(store), confirm=refuse)
    assert exc.value.details["requested_fields"] == ["tier"] and exc.value.details["site"] == SITE
    assert seen == {}  # no session, no verify, no catalog request


def test_confirm_skipped_when_nothing_to_disclose(store):
    asked = []
    http, _ = site_and_air()
    visit(SITE, http=http, confirm=asked.append)  # not delegated
    http, _ = site_and_air(environment="mock")
    visit(SITE, http=http, mock="good", confirm=asked.append)
    assert asked == []


# ------------------------------------------------------------------ CLI


@pytest.fixture
def fake_net(monkeypatch):
    """Route the CLI's AIR client and site client to the mocked site + AIR."""
    http, seen = site_and_air()
    fresh = lambda *a, **k: httpx.Client(transport=http._transport)  # the CLI closes each client it opens
    monkeypatch.setattr(cli, "_air_client", fresh)
    monkeypatch.setattr(cli, "site_client", fresh)
    return seen


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_cli_visit_requires_approval_when_delegated(store, fake_net, capsys):
    delegate(store)
    code, out = run_cli(capsys, "visit", SITE)
    assert code == 0 and out["approval_required"] is True and out["requested_fields"] == ["tier"]
    assert "--approved" in out["message"] and fake_net == {}
    code, out = run_cli(capsys, "visit", SITE, "--approved")
    assert code == 0 and out["viewer"] == "eligible" and out["disclosed"] == ["tier"]
    assert SDJWT not in json.dumps(out) and "agent.jwt" not in json.dumps(out)


def test_cli_approval_setting_off(store, fake_net, capsys, monkeypatch):
    delegate(store)
    monkeypatch.setenv("AIR_KYA_REQUIRE_APPROVAL", "0")
    code, out = run_cli(capsys, "visit", SITE)
    assert code == 0 and out["viewer"] == "eligible"


def test_cli_not_delegated_needs_no_approval(store, fake_net, capsys):
    code, out = run_cli(capsys, "visit", SITE)
    assert code == 0 and out["verification"] == "not_delegated" and "approval_required" not in out


def test_cli_whoami_and_logout(store, capsys):
    code, out = run_cli(capsys, "whoami")
    assert code == 0 and out["delegated"] is False and out["login_pending"] is False
    delegate(store)
    code, out = run_cli(capsys, "whoami")
    assert out["delegated"] is True and out["userId"] == USER and out["partnerId"] == BUNDLE_PARTNER
    code, out = run_cli(capsys, "logout")
    assert code == 0 and not (store / air.KEY_FILE).exists() and not (store / air.BUNDLE_FILE).exists()


def test_cli_login_two_steps(store, capsys, monkeypatch):
    console = Console(approve_after=0)
    monkeypatch.setattr(cli, "_air_client", lambda *a, **k: console.client())
    code, out = run_cli(capsys, "login", "start", "--name", "Test bot")
    assert code == 0 and out["user_code"] == "ABCD" and "login finish" in out["next"]
    code, out = run_cli(capsys, "whoami")
    assert out["login_pending"] is True
    code, out = run_cli(capsys, "login", "finish", "--wait", "0")
    assert code == 0 and out["status"] == "delegated"


def test_cli_errors_are_json(store, capsys):
    code, out = run_cli(capsys, "visit", "http://not-local.example")
    assert code == 1 and out["code"] == "SITE_NOT_PUBLIC"
    code, out = run_cli(capsys, "login", "finish")
    assert code == 1 and out["code"] == "NO_PENDING_LOGIN"


def test_settings_override_endpoints(monkeypatch):
    env = air.air_env({"console_url": "https://agents.example", "partner_id": " ", "api_url": ""})
    assert env.console_url == "https://agents.example"
    assert env.partner_id == air.SANDBOX["partner_id"] and env.air_api_url == air.SANDBOX["air_api_url"]
    monkeypatch.setenv("AIR_KYA_CONSOLE_URL", "https://console.example")
    assert cli._env().console_url == "https://console.example"


# ------------------------------------------------------------------ site address guard




def fake_resolver(table):
    def resolve(host, port):
        if host not in table:
            raise OSError("no such host")
        return table[host]
    return resolve


@pytest.mark.parametrize("url", [
    "https://10.0.0.5", "https://172.16.0.1", "https://192.168.1.1", "https://169.254.169.254",
    "https://127.0.0.1:8787", "https://[::1]", "https://[fc00::1]", "https://[fe80::1]", "https://0.0.0.0",
    "https://[::ffff:127.0.0.1]", "https://100.64.0.1", "http://localhost:8787", "http://127.0.0.1:6379",
])
def test_site_base_refuses_local_literals(url):
    with pytest.raises(VisitError) as exc:
        kya.site_base(url)
    assert exc.value.extra.get("code") == "SITE_NOT_PUBLIC"


def test_site_base_allows_localhost_only_when_asked():
    assert kya.site_base("http://127.0.0.1:8787", allow_local=True) == "http://127.0.0.1:8787"
    assert kya.site_base("https://[::1]:8443", allow_local=True) == "https://[::1]:8443"
    with pytest.raises(VisitError):  # local still means loopback, not the LAN or metadata
        kya.site_base("https://169.254.169.254", allow_local=True)
    with pytest.raises(VisitError):
        kya.site_base("http://192.168.1.1", allow_local=True)
    assert kya.site_base("https://93.184.215.14") == "https://93.184.215.14"


def test_checked_addresses_requires_every_address_public():
    resolve = fake_resolver({"shop.example": ["93.184.215.14"], "mixed.example": ["93.184.215.14", "10.0.0.7"],
                             "meta.example": ["169.254.169.254"], "v6.example": ["2606:4700::1111"],
                             "local.example": ["127.0.0.1"]})
    assert kya.checked_addresses("shop.example", 443, resolve=resolve) == ["93.184.215.14"]
    assert kya.checked_addresses("v6.example", 443, resolve=resolve) == ["2606:4700::1111"]
    for host in ("mixed.example", "meta.example", "local.example"):
        with pytest.raises(VisitError, match="non-public"):
            kya.checked_addresses(host, 443, resolve=resolve)
    assert kya.checked_addresses("local.example", 443, allow_local=True, resolve=resolve) == ["127.0.0.1"]
    with pytest.raises(VisitError, match="Cannot resolve"):
        kya.checked_addresses("nope.example", 443, resolve=resolve)


class RecordingBackend(httpcore.NetworkBackend):
    def __init__(self):
        self.connected = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append((host, port))
        raise httpcore.ConnectError("recorded")


def test_backend_connects_to_checked_address_only():
    answers = iter([["93.184.215.14"], ["127.0.0.1"]])  # second lookup "rebinds" to loopback
    inner = RecordingBackend()
    backend = kya.PublicOnlyBackend(resolve=lambda h, p: next(answers), inner=inner)
    with pytest.raises(httpcore.ConnectError):
        backend.connect_tcp("shop.example", 443)
    assert inner.connected == [("93.184.215.14", 443)]  # the IP we checked, never the hostname
    with pytest.raises(VisitError, match="non-public"):
        backend.connect_tcp("shop.example", 443)
    assert len(inner.connected) == 1
    with pytest.raises(httpcore.ConnectError):
        backend.connect_unix_socket("/var/run/docker.sock")


def test_site_client_refuses_rebound_host_before_any_request():
    with kya.site_client(resolve=fake_resolver({"shop.example": ["10.1.2.3"]})) as client:
        with pytest.raises(VisitError, match="non-public"):
            client.get("https://shop.example/.well-known/air-kya")


def test_visit_uses_site_client_for_site_only(store):
    http, seen = site_and_air()
    with kya.site_client(resolve=fake_resolver({"shop.example": ["192.168.0.10"]})) as site_http:
        with pytest.raises(VisitError, match="non-public"):
            visit(SITE, http=http, site_http=site_http, delegation=delegate(store))
    assert seen == {}  # refused before discovery, so AIR was never asked for a presentation


def test_cli_visit_refuses_private_site(store, capsys):
    for url in ("https://169.254.169.254", "http://127.0.0.1:6379"):
        code, out = run_cli(capsys, "visit", url)
        assert code == 1 and out["code"] == "SITE_NOT_PUBLIC"
