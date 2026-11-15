import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tacit import doctor
from tacit.app import create_app
from tacit.payments import BadSignature, StripePayments
from tacit.store import Store
from tacit.testing import make_settings, onboard


class FakePayments:
    def __init__(self):
        self.calls = []
        self.bad = False

    async def create_checkout(self, **kw):
        self.calls.append(kw)
        return "cs_test_1", "https://checkout.stripe.com/c/pay/cs_test_1"

    def parse_event(self, payload, signature):
        if signature != "good":
            raise BadSignature("bad")
        return json.loads(payload)


def setup(tmp_path, **kw):
    store = Store(tmp_path / "t.db")
    pay = FakePayments()
    s = make_settings(public_base_url="https://tacit.example", **kw)
    a = TestClient(create_app(s, store=store, payments=pay), base_url="https://tacit.example")
    b = TestClient(create_app(s, store=store, payments=pay), base_url="https://tacit.example")
    maya = onboard(a, phone="+14155550100", name="Maya Lin")["id"]
    ana = onboard(b, phone="+14155550101", name="Ana Ruiz")["id"]
    return store, pay, a, b, maya, ana


def completed(event_id, follower, expert, status="paid"):
    return json.dumps({"id": event_id, "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_test_1", "payment_status": status,
        "metadata": {"follower_id": follower, "expert_id": expert}}}})


def test_checkout_creates_follow_and_session(tmp_path):
    store, pay, a, b, maya, ana = setup(tmp_path)
    r = b.post(f"/api/follow/{maya}/checkout")
    assert r.status_code == 200
    assert r.json() == {"url": "https://checkout.stripe.com/c/pay/cs_test_1"}
    f = store.get_follow(ana, maya)
    assert f is not None and f.paid is False
    kw = pay.calls[0]
    assert kw["expert_id"] == maya and kw["follower_id"] == ana and kw["amount_cents"] == 500
    assert kw["success_url"] == f"https://tacit.example/app/#/people/{maya}?paid=1"
    assert kw["cancel_url"] == f"https://tacit.example/app/#/people/{maya}"
    assert kw["product_name"] == "Follow Maya's skills on tacit"
    assert b.post(f"/api/follow/{ana}/checkout").status_code == 400
    assert b.post("/api/follow/nope/checkout").status_code == 404


def test_webhook_marks_paid_once(tmp_path):
    store, pay, a, b, maya, ana = setup(tmp_path)
    b.post(f"/api/follow/{maya}/checkout")
    body = completed("evt_1", ana, maya)
    assert a.post("/stripe/webhook", content=body,
                  headers={"stripe-signature": "bad"}).status_code == 400
    assert store.get_follow(ana, maya).paid is False
    r = a.post("/stripe/webhook", content=body, headers={"stripe-signature": "good"})
    assert r.status_code == 200
    f = store.get_follow(ana, maya)
    assert f.paid is True and f.stripe_session_id == "cs_test_1"
    # replay: no change
    with store.lock:
        store.db.execute("UPDATE follows SET paid = 0")
    r = a.post("/stripe/webhook", content=body, headers={"stripe-signature": "good"})
    assert r.status_code == 200 and store.get_follow(ana, maya).paid is False
    # unpaid sessions and other events change nothing
    a.post("/stripe/webhook", content=completed("evt_2", ana, maya, status="unpaid"),
           headers={"stripe-signature": "good"})
    a.post("/stripe/webhook", content=json.dumps({"id": "evt_3", "type": "charge.refunded"}),
           headers={"stripe-signature": "good"})
    assert store.get_follow(ana, maya).paid is False
    assert b.post(f"/api/follow/{maya}/checkout").status_code == 200


def test_paid_follow_unlocks(tmp_path):
    store, pay, a, b, maya, ana = setup(tmp_path)
    from tacit.domain import Skill
    store.add_skill(Skill(owner_id=maya, title="Locked", verdict="v", reason="r",
                          status="published", visibility="followers"))
    assert b.get(f"/api/people/{maya}").json()["skills"][0]["locked"] is True
    a.post("/stripe/webhook", content=completed("evt_1", ana, maya),
           headers={"stripe-signature": "good"})
    assert b.get(f"/api/people/{maya}").json()["skills"][0]["verdict"] == "v"
    assert b.post(f"/api/follow/{maya}/checkout").status_code == 409


def test_no_payments_configured(tmp_path):
    s = make_settings()
    c = TestClient(create_app(s, store=Store(tmp_path / "t.db")), base_url="https://localhost")
    maya = onboard(c)["id"]
    assert c.get("/api/config").json()["payments_enabled"] is False
    assert c.post(f"/api/follow/{maya}/checkout").status_code == 503
    assert c.post("/stripe/webhook", content=b"{}").status_code == 503


def test_stripe_refuses_live_keys():
    with pytest.raises(RuntimeError, match="live Stripe keys are not allowed"):
        StripePayments(make_settings(stripe_secret_key="sk_live_abc"))
    StripePayments(make_settings(stripe_secret_key="sk_test_abc"))
    StripePayments(make_settings(stripe_secret_key="rk_test_abc"))


def test_live_key_disables_payments_in_the_app(tmp_path):
    s = make_settings(stripe_secret_key="sk_live_abc")
    with TestClient(create_app(s, store=Store(tmp_path / "t.db"))) as c:
        assert c.get("/api/config").json()["payments_enabled"] is False


def sign(payload: bytes, secret: str) -> str:
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


def test_parse_event_verifies_signature():
    p = StripePayments(make_settings(stripe_secret_key="sk_test_abc",
                                     stripe_webhook_secret="whsec_test"))
    payload = completed("evt_1", "a", "b").encode()
    assert p.parse_event(payload, sign(payload, "whsec_test"))["id"] == "evt_1"
    with pytest.raises(BadSignature):
        p.parse_event(payload, sign(payload, "whsec_other"))
    with pytest.raises(BadSignature):
        p.parse_event(payload, "")


async def test_create_checkout_params(monkeypatch):
    p = StripePayments(make_settings(stripe_secret_key="sk_test_abc"))
    seen = {}

    async def create_async(params=None, options=None):
        seen.update(params)
        return SimpleNamespace(id="cs_test_9", url="https://checkout.stripe.com/x")

    monkeypatch.setattr(p._client.v1.checkout.sessions, "create_async", create_async)
    out = await p.create_checkout(expert_id="e", follower_id="f", amount_cents=500,
                                  success_url="https://s", cancel_url="https://c",
                                  product_name="Follow Maya's skills on tacit")
    assert out == ("cs_test_9", "https://checkout.stripe.com/x")
    assert seen["mode"] == "payment" and seen["client_reference_id"] == "f"
    assert seen["metadata"] == {"follower_id": "f", "expert_id": "e"}
    item = seen["line_items"][0]
    assert item["price_data"] == {"currency": "usd", "unit_amount": 500,
                                  "product_data": {"name": "Follow Maya's skills on tacit"}}


async def test_doctor_stripe_row():
    async with httpx.AsyncClient() as http:
        ok, detail = await doctor.check_stripe(make_settings(stripe_secret_key="sk_live_x"), http)
        assert ok is False and "live key" in detail
        with respx.mock:
            route = respx.get("https://api.stripe.com/v1/balance").mock(
                return_value=httpx.Response(200, json={}))
            ok, detail = await doctor.check_stripe(make_settings(stripe_secret_key="sk_test_x"),
                                                   http)
            assert (ok, detail) == (True, "works (test mode)")
            assert route.calls.last.request.headers["authorization"].startswith("Basic ")
            assert "sk_test_x" not in detail
