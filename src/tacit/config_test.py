import pytest
from pydantic import ValidationError

from tacit.config import Settings


def test_allowlist_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("CALL_ALLOWLIST", "+14155550100, +15105550101")
    assert Settings().call_allowlist == ["+14155550100", "+15105550101"]


def test_allowlist_empty_by_default():
    assert Settings().call_allowlist == []


def test_allowlist_rejects_non_e164(monkeypatch):
    monkeypatch.setenv("CALL_ALLOWLIST", "4155550100")
    with pytest.raises(ValidationError):
        Settings()


def test_defaults():
    s = Settings()
    assert s.openai_model == "gpt-6-luna"
    assert s.follow_price_cents == 500
    assert s.db_path.name == "tacit.db"
    assert s.session_secret is None


def test_env_file_is_not_read_from_repo(tmp_path):
    # conftest chdirs into tmp_path, so a stray .env elsewhere is invisible
    (tmp_path / ".env").write_text("TACIT_BAND=74\n")
    assert Settings().tacit_band == 74
    (tmp_path / ".env").unlink()
    assert Settings().tacit_band is None


def test_trailing_slash_stripped():
    s = Settings(public_base_url="https://x.fly.dev/")
    assert s.public_base_url == "https://x.fly.dev"
    assert s.server_url == "https://x.fly.dev"


def test_band_must_be_team_band():
    with pytest.raises(ValidationError):
        Settings(tacit_band=42)
