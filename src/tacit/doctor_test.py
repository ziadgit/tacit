import httpx
import respx

from tacit import doctor
from tacit.config import Settings


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


async def test_missing_keys_are_skipped_not_failed(monkeypatch):
    monkeypatch.setattr(doctor, "check_band_sim", lambda s: (True, "sim"))
    results = await doctor.run(settings())
    assert {r.name: r.ok for r in results if r.name != "Vexo kit"} == dict.fromkeys(
        doctor.CHECKS, None
    )


@respx.mock
async def test_deepgram_status_reported_without_key():
    respx.get("https://api.deepgram.com/v1/projects").mock(return_value=httpx.Response(401))
    async with httpx.AsyncClient() as http:
        ok, detail = await doctor.check_deepgram(settings(deepgram_api_key="sekrit"), http)
    assert (ok, detail) == (False, "status 401")
    assert "sekrit" not in detail


def test_band_sim_uses_configured_number():
    ok, detail = doctor.check_band_sim(settings(tacit_band=74))
    assert ok and "Vexo-HACK-74" in detail


def test_only_team_bands_are_accepted():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        settings(tacit_band=42)
