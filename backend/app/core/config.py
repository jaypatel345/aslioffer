import os
from typing import List, Union
from pydantic import AnyHttpUrl, Field, field_validator
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
    # SerpApi's own processing time for a query it has not cached varies from a few
    # seconds to over a minute (measured 3.5-88 s). A timed-out request is not retried
    # (see serpapi_client), so the per-request timeout is the time a search may take.
    SEARCH_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0, le=120)
    SEARCH_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    SEARCH_RETRY_BACKOFF_SECONDS: float = Field(default=0.5, ge=0, le=5)
    SEARCH_TOTAL_TIMEOUT_SECONDS: float = Field(default=65.0, gt=0, le=180)
    SEARCH_DEMO_MODE: bool = False
    # Searches run as from India: offers are Indian, and US-localised results bury
    # employers' own sites under stock tickers and job boards. Empty string = omit.
    SEARCH_COUNTRY: str = "in"
    SEARCH_LANGUAGE: str = "en"
    SEARCH_GOOGLE_DOMAIN: str = "google.co.in"
    # Elapsed limit for all external searches in one investigation (RUN_TIMEOUT_SECONDS
    # still bounds the whole run). Progress is streamed, so the user sees each step.
    INVESTIGATION_SEARCH_DEADLINE_SECONDS: float = Field(default=90.0, gt=0, le=300)
    # Searches per investigation. Employer resolution can need up to three (website,
    # off-topic retry, entity card) before the agents' own checks run.
    INVESTIGATION_MAX_SEARCHES: int = Field(default=12, ge=1, le=30)
    # Searches in flight at once. One slow SerpApi query holds a slot, so a small pool
    # makes every other check wait behind it.
    INVESTIGATION_MAX_CONCURRENT_SEARCHES: int = Field(default=5, ge=1, le=10)

    # Run service (J3)
    # Hard ceiling on one investigation run, on top of the investigator's own
    # search deadline. A run that exceeds it is marked FAILED, not left RUNNING.
    RUN_TIMEOUT_SECONDS: float = Field(default=150.0, gt=0, le=600)

    # Upload and privacy controls (J6)
    MAX_UPLOAD_BYTES: int = Field(default=5 * 1024 * 1024, gt=0)
    MAX_TEXT_CHARS: int = Field(default=20_000, gt=0)
    # Cases (offer text, claims, reports) are purged this many days after upload.
    CASE_RETENTION_DAYS: int = Field(default=7, ge=1, le=365)

    # Gemini AI Configuration
    # Groq is tried before Gemini for document reading: its free tier allows
    # 30 requests/minute and 1000/day, where Gemini's exhausted every model in
    # the fallback chain on a single screenshot.
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "qwen/qwen3.8-27b"

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
