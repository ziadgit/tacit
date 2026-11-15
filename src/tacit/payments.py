"""Stripe Checkout for unlocking an expert's followers-only skills (SPEC §10). Test mode only.

`payments` is duck-typed: `async create_checkout(*, expert_id, follower_id, amount_cents,
success_url, cancel_url, product_name) -> (session_id, url)` and
`parse_event(payload: bytes, signature: str) -> dict`.
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth import current_user, get_settings, get_store
from .config import Settings, require
from .domain import User, first_name
from .store import Store

log = logging.getLogger("tacit.payments")
TEST_PREFIXES = ("sk_test_", "rk_test_")
router = APIRouter()


def is_test_key(key: str) -> bool:
    return key.startswith(TEST_PREFIXES)


class BadSignature(Exception):
    """The Stripe-Signature header didn't verify."""


class StripePayments:
    """The official `stripe` package (17.x: `stripe.StripeClient`), refusing live keys."""

    def __init__(self, settings: Settings):
        key = require(settings.stripe_secret_key, "STRIPE_SECRET_KEY")
        if not is_test_key(key):
            raise RuntimeError("live Stripe keys are not allowed")
        import stripe

        self._stripe = stripe
        self._client = stripe.StripeClient(key, max_network_retries=0)
        self._webhook_secret = (settings.stripe_webhook_secret.get_secret_value()
                                if settings.stripe_webhook_secret else None)

    async def create_checkout(self, *, expert_id: str, follower_id: str, amount_cents: int,
                              success_url: str, cancel_url: str,
                              product_name: str = "Follow on tacit") -> tuple[str, str]:
        session = await self._client.v1.checkout.sessions.create_async(params={
            "mode": "payment",
            "line_items": [{"quantity": 1, "price_data": {
                "currency": "usd", "unit_amount": amount_cents,
                "product_data": {"name": product_name}}}],
            "client_reference_id": follower_id,
            "metadata": {"follower_id": follower_id, "expert_id": expert_id},
            "success_url": success_url,
            "cancel_url": cancel_url,
        })
        return session.id, session.url

    def parse_event(self, payload: bytes, signature: str) -> dict[str, Any]:
        if not self._webhook_secret:
            raise BadSignature("no webhook secret")
        try:
            self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except Exception:  # noqa: BLE001 - any failure to verify is a bad signature
            raise BadSignature("bad signature") from None
        return json.loads(payload)


def make_payments(settings: Settings) -> StripePayments | None:
    if settings.stripe_secret_key is None:
        return None
    try:
        return StripePayments(settings)
    except RuntimeError:
        log.warning("payments off: STRIPE_SECRET_KEY is not a test key")
        return None


def base_url(request: Request, settings: Settings) -> str:
    return (settings.public_base_url or str(request.base_url)).rstrip("/")


@router.post("/api/follow/{person_id}/checkout")
async def checkout(person_id: str, request: Request,
                   user: Annotated[User, Depends(current_user)],
                   store: Annotated[Store, Depends(get_store)],
                   settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    payments = request.app.state.payments
    if payments is None:
        raise HTTPException(503, "payments aren't set up")
    if person_id == user.id:
        raise HTTPException(400, "you can't follow yourself")
    expert = store.get_user(person_id)
    if expert is None:
        raise HTTPException(404, "no such person")
    f = store.follow(user.id, expert.id)
    if f.paid:
        raise HTTPException(409, "you already unlocked these skills")
    base = base_url(request, settings)
    try:
        _, url = await payments.create_checkout(
            expert_id=expert.id, follower_id=user.id, amount_cents=settings.follow_price_cents,
            success_url=f"{base}/app/#/people/{expert.id}?paid=1",
            cancel_url=f"{base}/app/#/people/{expert.id}",
            product_name=f"Follow {first_name(expert.name)}'s skills on tacit")
    except Exception as e:  # noqa: BLE001 - never echo Stripe's message
        log.warning("stripe checkout failed: %s", type(e).__name__)
        raise HTTPException(502, "couldn't start the payment") from None
    log.info("stripe checkout created")
    return {"url": url}


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, store: Annotated[Store, Depends(get_store)]):
    payments = request.app.state.payments
    if payments is None:
        return JSONResponse({"detail": "payments aren't set up"}, status_code=503)
    payload = await request.body()
    try:
        event = payments.parse_event(payload, request.headers.get("stripe-signature", ""))
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "bad signature"}, status_code=400)
    if not isinstance(event, dict):
        return JSONResponse({"detail": "bad event"}, status_code=400)
    event_id = event.get("id")
    if not isinstance(event_id, str) or not store.mark_stripe_event(event_id):
        return {}
    kind = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed" and obj.get("payment_status") == "paid":
        meta = obj.get("metadata") or {}
        follower, expert = meta.get("follower_id"), meta.get("expert_id")
        if (isinstance(follower, str) and isinstance(expert, str)
                and store.get_user(follower) and store.get_user(expert)):
            store.set_follow_paid(follower, expert, str(obj.get("id") or ""))
            log.info("stripe: follow paid")
    log.info("stripe event: %s", kind)
    return {}
