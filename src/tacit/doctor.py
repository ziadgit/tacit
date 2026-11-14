"""`tacit doctor`: check every sponsor key and the band with one cheap call each.

Prints only status codes, never keys or response bodies.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .band import use_kit
from .config import Settings, require, require_band


@dataclass
class Result:
    name: str
    ok: bool | None  # None = skipped (no key)
    detail: str


def _http_check(r: httpx.Response) -> tuple[bool, str]:
    return (True, "works") if r.is_success else (False, f"status {r.status_code}")


async def check_deepgram(s: Settings, http: httpx.AsyncClient) -> tuple[bool, str]:
    key = require(s.deepgram_api_key, "DEEPGRAM_API_KEY")
    r = await http.get(
        "https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {key}"}
    )
    return _http_check(r)


async def check_openai(s: Settings, http: httpx.AsyncClient) -> tuple[bool, str]:
    key = require(s.openai_api_key, "OPENAI_API_KEY")
    r = await http.get(
        "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}
    )
    return _http_check(r)


async def check_exa(s: Settings, http: httpx.AsyncClient) -> tuple[bool, str]:
    key = require(s.exa_api_key, "EXA_API_KEY")
    r = await http.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": key},
        json={"query": "wearable audio wristband", "numResults": 1},
    )
    return _http_check(r)


async def check_vapi(s: Settings, http: httpx.AsyncClient) -> tuple[bool, str]:
    key = require(s.vapi_api_key, "VAPI_API_KEY")
    r = await http.get(
        "https://api.vapi.ai/assistant", params={"limit": 1},
        headers={"Authorization": f"Bearer {key}"},
    )
    return _http_check(r)


async def check_jev(s: Settings, http: httpx.AsyncClient) -> tuple[bool, str]:
    from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria, RetryPolicy

    jev = AsyncTypeSafeClient(
        api_key=require(s.typesafe_api_key, "TYPESAFE_API_KEY"),
        model=s.jev_model,
        retry=RetryPolicy(max_retries=0),
        timeout=s.jev_timeout_s,
    )
    q = {
        "said_hello": Noul(
            instructions="Does `transcript` contain a greeting?",
            criteria=NoulCriteria(true="It greets someone.", false="It does not greet anyone."),
        )
    }
    try:
        async with asyncio.timeout(s.jev_timeout_s + 1):
            resp = await jev.system_one(state={"transcript": "hi there, how are you"}, questions=q)
        return True, f"works (p(greeting)={float(resp.nouls['said_hello'].noul):.2f})"
    except Exception as e:  # noqa: BLE001 - report, don't crash; never echo the message (may hold the key)
        return False, type(e).__name__


def check_band_sim(s: Settings) -> tuple[bool, str]:
    band_no = require_band(s)
    use_kit()
    from vexo_open.sync import Band

    band = Band.connect(band_no, transport="sim")
    try:
        return True, f"pretend {band.name} connected, firmware {band.info.firmware}"
    finally:
        band.disconnect()


CHECKS: dict[str, tuple[str, Callable[..., Awaitable[tuple[bool, str]]]]] = {
    "Deepgram": ("deepgram_api_key", check_deepgram),
    "OpenAI": ("openai_api_key", check_openai),
    "Exa": ("exa_api_key", check_exa),
    "Jev (TypeSafe)": ("typesafe_api_key", check_jev),
    "Vapi": ("vapi_api_key", check_vapi),
}


async def run(s: Settings) -> list[Result]:
    results: list[Result] = []
    try:
        ok, detail = check_band_sim(s)
        results.append(Result("Vexo kit", ok, detail))
    except Exception as e:  # noqa: BLE001
        results.append(Result("Vexo kit", False, str(e)))

    async with httpx.AsyncClient(timeout=15) as http:

        async def one(name: str, field: str, fn) -> Result:
            if getattr(s, field) is None:
                return Result(name, None, f"skipped: {field.upper()} not set")
            try:
                ok, detail = await fn(s, http)
            except httpx.HTTPError as e:
                ok, detail = False, f"could not connect ({type(e).__name__})"
            return Result(name, ok, detail)

        results += await asyncio.gather(*(one(n, f, fn) for n, (f, fn) in CHECKS.items()))
    return results
