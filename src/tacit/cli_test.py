import json

import httpx
import respx
from typer.testing import CliRunner

from tacit import cli, doctor
from tacit.config import Settings

runner = CliRunner()
SECRETS = {"VAPI_API_KEY": "vapi-sekrit", "VAPI_SERVER_SECRET": "server-sekrit",
           "DEEPGRAM_API_KEY": "dg-sekrit", "PUBLIC_BASE_URL": "https://tacit.example"}


def env(monkeypatch, **kw):
    for k, v in {**SECRETS, **kw}.items():
        monkeypatch.setenv(k, v)


def test_vapi_sync_dry_run_masks_every_secret(monkeypatch):
    env(monkeypatch)
    r = runner.invoke(cli.app, ["vapi-sync", "--dry-run"])
    assert r.exit_code == 0, r.output
    for v in SECRETS.values():
        if "sekrit" in v:
            assert v not in r.output
    body = json.loads(r.output)
    assert body["server"]["url"] == "https://tacit.example/vapi/webhook"
    assert body["server"]["headers"] == {"x-tacit-secret": "***"}
    assert body["credentials"] == [{"provider": "deepgram", "apiKey": "***"}]


@respx.mock
def test_vapi_sync_creates_then_says_what_to_add(monkeypatch):
    env(monkeypatch)
    route = respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(201, json={"id": "asst_123"}))
    r = runner.invoke(cli.app, ["vapi-sync"])
    assert r.exit_code == 0, r.output
    assert "Add VAPI_ASSISTANT_ID=asst_123 to .env" in r.output
    assert route.calls.last.request.headers["authorization"] == "Bearer vapi-sekrit"
    assert "sekrit" not in r.output


@respx.mock
def test_vapi_sync_patches_when_id_set(monkeypatch):
    env(monkeypatch, VAPI_ASSISTANT_ID="asst_9")
    route = respx.patch("https://api.vapi.ai/assistant/asst_9").mock(
        return_value=httpx.Response(200, json={"id": "asst_9"}))
    r = runner.invoke(cli.app, ["vapi-sync"])
    assert r.exit_code == 0 and route.called and "updated" in r.output


@respx.mock
def test_vapi_sync_error_shows_status_only(monkeypatch):
    env(monkeypatch)
    respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(400, json={"message": "bad server-sekrit"}))
    r = runner.invoke(cli.app, ["vapi-sync"])
    assert r.exit_code == 1 and "vapi status 400" in r.output and "sekrit" not in r.output


def test_vapi_sync_needs_base_url(monkeypatch):
    monkeypatch.setenv("VAPI_API_KEY", "k")
    r = runner.invoke(cli.app, ["vapi-sync"])
    assert r.exit_code == 1 and "PUBLIC_BASE_URL" in r.output


def test_serve_passes_proxy_headers(monkeypatch):
    seen = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    r = runner.invoke(cli.app, ["serve", "--port", "8123"])
    assert r.exit_code == 0, r.output
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8123
    assert seen["proxy_headers"] is True and seen["forwarded_allow_ips"] == "*"
    r = runner.invoke(cli.app, ["serve", "--no-proxy-headers"])
    assert seen["proxy_headers"] is False


def test_doctor_settings_rows_never_show_values():
    s = Settings(_env_file=None, session_secret="sess-sekrit", public_base_url="https://x.example",
                 call_allowlist="+14155550100,+14155550101")
    rows = {r.name: r for r in doctor.settings_rows(s)}
    assert rows["SESSION_SECRET"].detail == "set: yes"
    assert rows["VAPI_SERVER_SECRET"].detail == "set: no" and rows["VAPI_SERVER_SECRET"].ok is None
    assert rows["PUBLIC_BASE_URL"].detail == "set: yes"
    assert rows["CALL_ALLOWLIST"].detail == "2 numbers"
    text = " ".join(r.detail for r in rows.values())
    assert "sekrit" not in text and "+1415" not in text and "x.example" not in text


def test_doctor_cli_prints_rows(monkeypatch):
    async def fake_run(s):
        return doctor.settings_rows(s)

    monkeypatch.setattr(doctor, "run", fake_run)
    monkeypatch.setenv("SESSION_SECRET", "sess-sekrit")
    r = runner.invoke(cli.app, ["doctor"])
    assert r.exit_code == 0, r.output
    assert "SESSION_SECRET" in r.output and "set: yes" in r.output
    assert "sess-sekrit" not in r.output
