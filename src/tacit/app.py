"""The tacit server (SPEC §11): API, PWA, landing page, webhooks."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl, StringConstraints

from .auth import clear_session, current_user, get_settings, get_store, guard, set_session
from .config import Settings
from .domain import (
    MOMENT_KINDS,
    CallOut,
    ContextItemOut,
    MeOut,
    Phone,
    User,
)
from .store import Store

log = logging.getLogger("tacit")
ROOT = Path(__file__).resolve().parents[2]
CSP = ("default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'")

CurrentUser = Annotated[User, Depends(current_user)]
StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class PWAFiles(StaticFiles):
    """The PWA: sw.js is never cached by the browser; the manifest has its own type."""

    async def get_response(self, path: str, scope) -> Response:
        resp = await super().get_response(path, scope)
        if path.endswith("sw.js"):
            resp.headers["Cache-Control"] = "no-cache"
        if path.endswith(".webmanifest"):
            resp.headers["Content-Type"] = "application/manifest+json"
        return resp


def me_out(store: Store, user: User) -> MeOut:
    ctx = store.context_for(user.id)
    calls = store.calls_for(user.id)
    skills = store.skills_mine(user.id)
    return MeOut(
        id=user.id, name=user.name, phone=user.phone, headline=user.headline,
        links=[str(u) for u in user.links], consent_lookup=user.consent_lookup,
        consent_call=user.consent_call, portrait=user.portrait,
        portrait_source=user.portrait_source, kinds_off=user.kinds_off,
        share_creative=user.share_creative,
        context=[ContextItemOut(**c.model_dump()) for c in ctx],
        calls=[CallOut(**c.model_dump()) for c in calls],
        counts={
            "skills": len(skills),
            "published": sum(s.status == "published" for s in skills),
            "followers": store.follower_count(user.id),
            "following": len(store.following(user.id)),
        },
    )


class OnboardingIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    phone: Phone
    headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)] | None = None
    links: Annotated[list[HttpUrl], Field(max_length=5)] = []
    consent_lookup: bool
    consent_call: bool


class MePatch(BaseModel):
    headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)] | None = None
    links: Annotated[list[HttpUrl], Field(max_length=5)] | None = None
    consent_lookup: bool | None = None
    consent_call: bool | None = None
    kinds_off: list[str] | None = None
    share_creative: bool | None = None


core = APIRouter()


@core.get("/healthz")
def healthz(request: Request) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    out.update(getattr(request.app.state, "bridge_health", None) or {})
    return out


@core.get("/api/config")
def api_config(request: Request, settings: SettingsDep) -> dict[str, Any]:
    st = request.app.state
    return {
        "phone_display": settings.tacit_phone_display,
        "follow_price_cents": settings.follow_price_cents,
        "calls_enabled": bool(settings.call_allowlist and st.vapi is not None),
        "lookup_enabled": st.exa is not None,
        "payments_enabled": st.payments is not None,
        "portraits_enabled": getattr(st, "portraits", None) is not None,
        "kinds": list(MOMENT_KINDS),
    }


@core.post("/api/onboarding", status_code=201)
def onboarding(body: OnboardingIn, response: Response, store: StoreDep,
               settings: SettingsDep) -> MeOut:
    if store.user_by_phone(body.phone):
        raise HTTPException(409, "this number already has an account")
    user = store.add_user(User(**body.model_dump()))
    set_session(response, settings, user.id)
    log.info("onboarding: new user")
    return me_out(store, user)


@core.get("/api/me")
def get_me(user: CurrentUser, store: StoreDep) -> MeOut:
    return me_out(store, user)


@core.patch("/api/me")
def patch_me(body: MePatch, user: CurrentUser, store: StoreDep) -> MeOut:
    fields = body.model_dump(exclude_unset=True)
    for k in ("consent_lookup", "consent_call", "share_creative", "links"):
        if k in fields and fields[k] is None:
            raise HTTPException(422, f"{k} can't be null")
    if "kinds_off" in fields:
        fields["kinds_off"] = [k for k in fields["kinds_off"] or [] if k in MOMENT_KINDS]
    if "links" in fields:
        fields["links"] = [str(u) for u in body.links or []]
    updated = store.update_user(user.id, **fields)
    return me_out(store, updated)


@core.delete("/api/me", status_code=204)
def delete_me(user: CurrentUser, store: StoreDep) -> Response:
    store.delete_user(user.id)
    resp = Response(status_code=204)
    clear_session(resp)
    log.info("delete everything: done")
    return resp


@core.post("/api/signout", status_code=204)
def signout() -> Response:
    resp = Response(status_code=204)
    clear_session(resp)
    return resp


def _routers() -> list[APIRouter]:
    from . import bridge_api, context, interview, network, payments, portraits

    return [core, context.router, interview.router, network.router, payments.router,
            portraits.router, bridge_api.router]


def build_clients(app: FastAPI, settings: Settings) -> None:
    """Real clients from whatever keys are set, unless a test injected one."""
    st = app.state
    if "exa" not in st.injected and settings.exa_api_key is not None:
        from exa_py import AsyncExa

        st.exa = AsyncExa(settings.exa_api_key.get_secret_value())
    if "jev" not in st.injected:
        from .judge import make_jev

        st.jev = make_jev(settings)
    if "vapi" not in st.injected and settings.vapi_api_key is not None:
        from .interview import VapiApi

        st.vapi = VapiApi(settings)
    if "payments" not in st.injected:
        from .payments import make_payments

        st.payments = make_payments(settings)
    if "portraits" not in st.injected:
        from .portraits import make_portraits

        st.portraits = make_portraits(settings)


def create_app(settings: Settings | None = None, *, store: Store | None = None, exa=None,
               jev=None, vapi=None, payments=None, portraits=None) -> FastAPI:
    settings = settings or Settings()
    injected = {"exa": exa, "jev": jev, "vapi": vapi, "payments": payments,
                "portraits": portraits}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.store is None:
            app.state.store = Store(settings.db_path)
        build_clients(app, settings)
        yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.injected = {k for k, v in injected.items() if v is not None}
    for k, v in injected.items():
        setattr(app.state, k, v)

    @app.middleware("http")
    async def checks(request: Request, call_next):
        t0 = time.monotonic()
        blocked = guard(request.method, request.url.path, request.headers.get("origin"),
                        settings)
        if blocked:
            resp: Response = JSONResponse({"detail": blocked[1]}, status_code=blocked[0])
        else:
            resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        route = request.scope.get("route")
        log.info("%s %s %s %.0fms", request.method, getattr(route, "path", request.url.path),
                 resp.status_code, (time.monotonic() - t0) * 1000)
        return resp

    for r in _routers():
        app.include_router(r)
    app.mount("/app", PWAFiles(directory=ROOT / "pwa", html=True, check_dir=False), name="pwa")
    app.mount("/design-system", StaticFiles(directory=ROOT / "design-system", check_dir=False),
              name="design-system")
    app.mount("/", StaticFiles(directory=ROOT / "landing", html=True, check_dir=False),
              name="landing")
    return app
