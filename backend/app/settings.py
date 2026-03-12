from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GovernAI Workflow Builder"
    redis_url: str = "redis://localhost:6379/0"
    use_redis: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    confidence_threshold: float = 0.80
    max_questions: int = 8
    max_repair_attempts: int = 2

    litellm_default_model: str = "openai/gpt-4o-mini"
    litellm_default_temperature: float = 0.2
    litellm_default_max_tokens: int = 800

    model_config = SettingsConfigDict(
        env_prefix="GOV_UI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
