"""Runtime configuration loaded from environment variables and .env."""
import sys
from datetime import time
from typing import Any, get_args

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from voice_agent.const import DEFAULT_SQLALCHEMY_DATABASE_URL, DEFAULT_TEST_SQLALCHEMY_DATABASE_URL, \
    DEFAULT_REPLY_PROVIDER, DEFAULT_REPLY_TEMPERATURE, DEFAULT_REPLY_MODEL, DEFAULT_REPLY_MAX_OUTPUT_TOKENS, \
    DEFAULT_REPLY_MAX_CONTEXT_CHARS, DEFAULT_APPOINTMENT_DURATION_MIN, DEFAULT_OPENING_TIME, DEFAULT_CLOSING_TIME, \
    DEFAULT_MESSAGE_HISTORY_SIZE
from voice_agent.core.types import HubSpotObjectType


def _is_optional_string(annotation: Any) -> bool:
    args = get_args(annotation)
    return len(args) == 2 and str in args and type(None) in args


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_parse_none_str="None",
    )

    # Database
    SQLALCHEMY_DATABASE_URL: str = Field(
        default=DEFAULT_SQLALCHEMY_DATABASE_URL,
        description="Async database URL (PostgreSQL/asyncpg with pgvector).",
        min_length=1,
    )

    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for caching and message queue.",
        min_length=1,
    )


    # API keys
    OPENAI_API_KEY: str | None = Field(
        default=None,
        description="OpenAI API key for embedding, rerank, and chat calls.",
    )

    HUBSPOT_ACCESS_TOKEN: str | None = Field(
        default=None,
        description="HubSpot private app token (PAT).",
    )
    HUBSPOT_CRM_OBJECT_TYPE: HubSpotObjectType = Field(
        default=HubSpotObjectType.DEAL,
        description="HubSpot object created per appointment.",
    )
    HUBSPOT_DEAL_STAGE: str = Field(
        default="appointmentscheduled",
        description="HubSpot deal stage internal name used for appointment sync.",
        min_length=1,
    )
    HUBSPOT_DEAL_CANCELLED_STAGE: str = Field(
        default="closedlost",
        description="HubSpot deal stage internal name used when an appointment is cancelled.",
        min_length=1,
    )
    HUBSPOT_DEAL_PIPELINE: str | None = Field(
        default=None,
        description="Optional HubSpot deal pipeline internal ID.",
    )
    HUBSPOT_TICKET_STAGE: str | None = Field(
        default=None,
        description="HubSpot ticket stage internal ID when syncing appointments as tickets.",
    )
    HUBSPOT_TICKET_CANCELLED_STAGE: str | None = Field(
        default=None,
        description="HubSpot ticket stage internal ID used when a synced appointment is cancelled.",
    )
    HUBSPOT_TICKET_PIPELINE: str | None = Field(
        default=None,
        description="Optional HubSpot ticket pipeline internal ID.",
    )
    HUBSPOT_SYNC_POLL_INTERVAL_SECONDS: int = Field(
        default=5,
        ge=1,
        le=300,
        description="Polling interval for the background HubSpot sync worker.",
    )
    HUBSPOT_SYNC_BATCH_SIZE: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of pending HubSpot sync events processed per poll.",
    )
    HUBSPOT_SYNC_INITIAL_DELAY_SECONDS: int = Field(
        default=30,
        ge=0,
        le=3600,
        description="Delay before a newly scheduled appointment is first synced to HubSpot.",
    )
    HUBSPOT_SYNC_RETRY_BASE_SECONDS: int = Field(
        default=30,
        ge=1,
        le=3600,
        description="Base retry delay for failed HubSpot sync events.",
    )
    HUBSPOT_SYNC_RETRY_MAX_SECONDS: int = Field(
        default=1800,
        ge=1,
        le=86400,
        description="Maximum retry delay for failed HubSpot sync events.",
    )
    HUBSPOT_SYNC_STALE_LOCK_SECONDS: int = Field(
        default=300,
        ge=30,
        le=86400,
        description="How long a processing CRM sync event can stay locked before it is re-claimed.",
    )
    LOG_LEVEL: str = Field(
        default="DEBUG",
        description="Logging level for the application.",
    )

    # Reply generation
    REPLY_PROVIDER: str = Field(
        default=DEFAULT_REPLY_PROVIDER,
        min_length=1,
        description="Provider for reply generation.",
    )
    REPLY_TEMPERATURE: float = Field(
        default=DEFAULT_REPLY_TEMPERATURE,
        ge=0.0,
        le=2.0,
        description="Temperature used for reply generation.",
    )

    REPLY_MODEL: str = Field(
        default=DEFAULT_REPLY_MODEL,
        min_length=1,
        description="LLM model used for replies.",
    )

    RANDOM_SEED: int | None = Field(
        default=None,
        description="Random seed for deterministic behavior. None for non-deterministic.",
    )
    MESSAGE_HISTORY_SIZE: int = Field(
        default=DEFAULT_MESSAGE_HISTORY_SIZE,
        ge=20,
        le=50,
        description="Length of each appointment slot in minutes.",
    )
    APPOINTMENT_DURATION_MIN: int = Field(
        default=DEFAULT_APPOINTMENT_DURATION_MIN,
        ge=10,
        le=180,
        description="Length of each appointment slot in minutes.",
    )
    OPENING_TIME: time = Field(
        default_factory=lambda: time.fromisoformat(DEFAULT_OPENING_TIME),
        description="Clinic opening time (local).",
    )
    CLOSING_TIME: time = Field(
        default_factory=lambda: time.fromisoformat(DEFAULT_CLOSING_TIME),
        description="Clinic closing time (local).",
    )



    @model_validator(mode="before")
    @classmethod
    def _blank_optional_strings_to_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        for field_name, field_info in cls.model_fields.items():
            if not _is_optional_string(field_info.annotation):
                continue

            value = normalized.get(field_name)
            if isinstance(value, str) and not value.strip():
                normalized[field_name] = None
        return normalized

def load_settings_or_die() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        print("[CONFIG ERROR] Invalid environment configuration:", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "invalid value")
            print(f"  - {loc}: {msg}", file=sys.stderr)
        sys.exit(2)


settings = load_settings_or_die()
