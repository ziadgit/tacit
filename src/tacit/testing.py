"""Shared test helpers (imported by *_test.py only)."""

from fastapi.testclient import TestClient

from .app import create_app
from .config import Settings
from .store import Store

SECRET = "test-session-secret-0123456789abcdef"


def make_settings(**kw) -> Settings:
    kw.setdefault("session_secret", SECRET)
    return Settings(_env_file=None, **kw)


def client(tmp_path, settings: Settings | None = None, **clients) -> TestClient:
    settings = settings or make_settings()
    store = clients.pop("store", None) or Store(tmp_path / "t.db")
    return TestClient(create_app(settings, store=store, **clients), base_url="http://localhost")


def onboard(c: TestClient, phone="+14155550100", name="Maya Lin", **kw) -> dict:
    body = {"name": name, "phone": phone, "consent_lookup": True, "consent_call": True, **kw}
    r = c.post("/api/onboarding", json=body)
    assert r.status_code == 201, r.text
    return r.json()
