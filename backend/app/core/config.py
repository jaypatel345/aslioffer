import os
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource



# pydantic-settings JSON-decodes complex field types (List[str]) straight from
# the environment, BEFORE any field_validator runs. So the comma-separated form
# the validator below advertises never reached it: setting
# BACKEND_CORS_ORIGINS=https://app.example.com raised SettingsError and the
# process refused to start — the exact variable you must set to deploy.
_LIST_FIELDS = {"BACKEND_CORS_ORIGINS"}


def _coerce_csv(field_name, value):
    if field_name in _LIST_FIELDS and isinstance(value, str):
        raw = value.strip()
        if raw and not raw.startswith("["):
            return [item.strip() for item in raw.split(",") if item.strip()]
    return None


class _CsvTolerantEnvSource(EnvSettingsSource):
    def prepare_field_value(self, field_name, field, value, value_is_complex):
        coerced = _coerce_csv(field_name, value)
        if coerced is not None:
            return coerced
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class _CsvTolerantDotEnvSource(DotEnvSettingsSource):
    def prepare_field_value(self, field_name, field, value, value_is_complex):
        coerced = _coerce_csv(field_name, value)
        if coerced is not None:
            return coerced
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class Settings(BaseSettings):
    PROJECT_NAME: str = "AsliOffer Backend"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite:///./aslioffer.db"

    # Redis Cache
    REDIS_URL: str = "redis://localhost:6379/0"

    # SerpApi Configuration
    SERPAPI_API_KEY: str = ""
    SEARCH_TIMEOUT_SECONDS: float = 8.0
    SEARCH_MAX_RETRIES: int = 2
    SEARCH_RETRY_BACKOFF_SECONDS: float = 0.5
    SEARCH_DEMO_MODE: bool = False

    # Gemini AI Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Accept both JSON and comma-separated list values from env and .env."""
        return (
            init_settings,
            _CsvTolerantEnvSource(settings_cls),
            _CsvTolerantDotEnvSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
