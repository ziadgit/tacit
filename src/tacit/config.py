"""Settings from the environment / .env. Missing keys fail where they are used."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The team's own Vexo bands: the ONLY place band numbers live. Code may connect to these and
# nothing else. Other people's bands are never scanned for or connected to over Bluetooth;
# social features learn about them only through our backend, from data their owners share.
TEAM_BANDS: tuple[int, ...] = (16, 74)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # Which of TEAM_BANDS this laptop drives (each teammate sets their own in .env).
    tacit_band: int | None = None

    deepgram_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    typesafe_api_key: SecretStr | None = None
    vapi_api_key: SecretStr | None = None

    jev_model: str = "jev-1.13.0"
    deepgram_stt_model: str = "nova-3"
    deepgram_tts_model: str = "aura-2-thalia-en"
    jev_timeout_s: float = 5.0

    @field_validator("tacit_band")
    @classmethod
    def _band_range(cls, v: int | None) -> int | None:
        if v is not None and v not in TEAM_BANDS:
            raise ValueError(f"TACIT_BAND must be one of the team's bands {TEAM_BANDS}")
        return v


def require(value: SecretStr | None, name: str) -> str:
    if value is None:
        raise RuntimeError(f"{name} is not set (add it to .env)")
    return value.get_secret_value()


def require_band(settings: Settings) -> int:
    if settings.tacit_band is None:
        raise RuntimeError(f"TACIT_BAND is not set: put one of {TEAM_BANDS} in .env")
    return settings.tacit_band
