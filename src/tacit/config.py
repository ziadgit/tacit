"""Settings from the environment / .env. Missing keys fail where they are used."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # The team's Vexo band number (1..999). The ONE place it lives; never hard-code it.
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
        if v is not None and not 1 <= v <= 999:
            raise ValueError("TACIT_BAND must be 1..999 (the number on your band's bag)")
        return v


def require(value: SecretStr | None, name: str) -> str:
    if value is None:
        raise RuntimeError(f"{name} is not set (add it to .env)")
    return value.get_secret_value()


def require_band(settings: Settings) -> int:
    if settings.tacit_band is None:
        raise RuntimeError("TACIT_BAND is not set: put your band's number (from its bag) in .env")
    return settings.tacit_band
