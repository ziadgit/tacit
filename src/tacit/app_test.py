from tacit.store import Store
from tacit.testing import client, make_settings, onboard


def test_healthz_and_config_without_secret(tmp_path):
    c = client(tmp_path, make_settings(session_secret=None))
    assert c.get("/healthz").json() == {"status": "ok"}
    r = c.get("/api/config")
    assert r.status_code == 200
    assert r.json()["calls_enabled"] is False
    r = c.get("/api/me")
    assert r.status_code == 503 and r.json() == {"detail": "SESSION_SECRET is not set"}
    assert c.post("/api/onboarding", json={}).status_code == 503


def test_csp_on_every_response(tmp_path):
    c = client(tmp_path)
    for path in ("/healthz", "/api/config", "/api/me"):
        csp = c.get(path).headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_onboarding_sets_cookie_and_me(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/me").status_code == 401
    me = onboard(c, headline="Ten years in product", links=["https://maya.example.com"])
    assert me["name"] == "Maya Lin" and me["links"] == ["https://maya.example.com/"]
    assert me["counts"]["skills"] == 0
    cookie = c.cookies.get("tacit_session")
    assert cookie
    assert c.get("/api/me").json()["id"] == me["id"]


def test_cookie_flags(tmp_path):
    c = client(tmp_path, make_settings(public_base_url="https://tacit.example"))
    r = c.post("/api/onboarding", json={"name": "A", "phone": "+14155550100",
                                        "consent_lookup": False, "consent_call": False},
               headers={"origin": "https://tacit.example"})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc and "secure" in sc and "max-age=2592000" in sc


def test_duplicate_phone_409(tmp_path):
    c = client(tmp_path)
    onboard(c)
    c.cookies.clear()
    r = c.post("/api/onboarding", json={"name": "B", "phone": "+14155550100",
                                        "consent_lookup": False, "consent_call": False})
    assert r.status_code == 409
    assert r.json() == {"detail": "this number already has an account"}


def test_bad_phone_and_too_many_links(tmp_path):
    c = client(tmp_path)
    base = {"name": "A", "consent_lookup": False, "consent_call": False}
    assert c.post("/api/onboarding", json={**base, "phone": "4155550100"}).status_code == 422
    links = [f"https://x{i}.com" for i in range(6)]
    r = c.post("/api/onboarding", json={**base, "phone": "+14155550100", "links": links})
    assert r.status_code == 422


def test_origin_check(tmp_path):
    c = client(tmp_path)
    body = {"name": "A", "phone": "+14155550100", "consent_lookup": False, "consent_call": False}
    r = c.post("/api/onboarding", json=body, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/onboarding", json=body, headers={"origin": "http://localhost:8000"})
    assert r.status_code == 201


def test_patch_and_delete_me(tmp_path):
    store = Store(tmp_path / "t.db")
    c = client(tmp_path, store=store)
    me = onboard(c)
    r = c.patch("/api/me", json={"consent_call": False, "kinds_off": ["idea", "nope"],
                                 "links": ["https://a.com"]})
    assert r.status_code == 200
    j = r.json()
    assert j["consent_call"] is False and j["kinds_off"] == ["idea"]
    assert j["links"] == ["https://a.com/"]
    assert c.patch("/api/me", json={"consent_call": None}).status_code == 422
    r = c.delete("/api/me")
    assert r.status_code == 204
    assert store.get_user(me["id"]) is None
    assert c.get("/api/me").status_code == 401


def test_tampered_cookie_is_401(tmp_path):
    c = client(tmp_path)
    onboard(c)
    c.cookies.clear()
    assert c.get("/api/me", headers={"cookie": "tacit_session=garbage"}).status_code == 401


def test_static_mounts(tmp_path):
    c = client(tmp_path)
    assert c.get("/").status_code == 200
    assert c.get("/design-system/README.md").status_code == 200
    assert c.get("/api/nope").status_code == 404
