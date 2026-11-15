"""Settings from the environment / .env. Missing keys fail where they are used."""

import re
from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The team's own Vexo bands: the ONLY place band numbers live. Code may connect to these and
# nothing else. Other people's bands are never scanned for or connected to over Bluetooth;
# social features learn about them only through our backend, from data their owners share.
TEAM_BANDS: tuple[int, ...] = (16, 74)

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # Which of TEAM_BANDS this laptop drives (each teammate sets their own in .env).
    tacit_band: int | None = None

    deepgram_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None   # if set, Claude does band extraction
    exa_api_key: SecretStr | None = None
    typesafe_api_key: SecretStr | None = None
    vapi_api_key: SecretStr | None = None
    minimax_api_key: SecretStr | None = None

    vapi_server_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    tacit_bridge_token: SecretStr | None = None
    tacit_server_url: str | None = None

    openai_model: str = "gpt-6-luna"
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"
    scenario_threshold: float = 0.6
    windows_per_hour: int = 40
    mute_rewind_s: int = 15
    bridge_buffer_mb: int = 500

    vapi_assistant_id: str | None = None
    vapi_phone_number_id: str | None = None
    tacit_phone_display: str | None = None
    public_base_url: str | None = None
    call_allowlist: Annotated[list[str], NoDecode] = []
    vapi_llm_provider: str = "openai"
    vapi_llm_model: str = "gpt-4.1"
    vapi_voice_id: str = "asteria"

    jev_model: str = "jev-1.13.0"
    deepgram_stt_model: str = "nova-3"
    deepgram_tts_model: str = "aura-2-thalia-en"
    interview_max_seconds: int = 600
    follow_price_cents: int = 500
    tacit_data_dir: Path = Path("data")
    exa_timeout_s: float = 8.0
    jev_timeout_s: float = 5.0
    calls_per_user_per_day: int = 3
    lookups_per_user_per_day: int = 3
    portraits_per_user_per_day: int = 3
    minimax_base_url: str = "https://api.minimax.io"

    @field_validator("tacit_band")
    @classmethod
    def _band_range(cls, v: int | None) -> int | None:
        if v is not None and v not in TEAM_BANDS:
            raise ValueError(f"TACIT_BAND must be one of the team's bands {TEAM_BANDS}")
        return v

    @field_validator("call_allowlist", mode="before")
    @classmethod
    def _parse_allowlist(cls, v: object) -> list[str]:
        if v is None:
            return []
        items = [p.strip() for p in v.split(",")] if isinstance(v, str) else list(v)
        items = [p for p in items if p]
        for p in items:
            if not E164.match(p):
                raise ValueError("CALL_ALLOWLIST entries must be E.164 numbers like +14155550100")
        return items

    @field_validator("public_base_url", "tacit_server_url")
    @classmethod
    def _no_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @property
    def server_url(self) -> str | None:
        """Where a bridge uploads: TACIT_SERVER_URL, else PUBLIC_BASE_URL."""
        return self.tacit_server_url or self.public_base_url

    @property
    def db_path(self) -> Path:
        return self.tacit_data_dir / "tacit.db"


def require(value: SecretStr | None, name: str) -> str:
    if value is None:
        raise RuntimeError(f"{name} is not set (add it to .env)")
    return value.get_secret_value()


def require_band(settings: Settings) -> int:
    if settings.tacit_band is None:
        raise RuntimeError(f"TACIT_BAND is not set: put one of {TEAM_BANDS} in .env")
    return settings.tacit_band
