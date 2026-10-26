"""Runtime configuration. Secrets come from the environment / an untracked .env only."""

from __future__ import annotations

import shlex
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    gemini_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    verifier_model: str | None = None

    mcp_search_command: str = "npx"
    mcp_search_args: str = "-y tavily-mcp@0.2.22"
    mcp_search_tool: str | None = None  # auto-detected from list_tools when unset

    max_active_runs: int = Field(2, ge=1, le=10)
    run_timeout_seconds: float = Field(300, gt=0)
    llm_timeout_seconds: float = Field(60, gt=0)
    tool_timeout_seconds: float = Field(30, gt=0)
    max_retries: int = Field(2, ge=0, le=5)
    max_queries_per_task: int = Field(2, ge=1, le=3)
    max_results_per_query: int = Field(5, ge=1, le=10)
    max_source_chars: int = Field(4000, ge=500)

    db_path: str = "data/researchlab.db"
    cors_origins: str = "http://localhost:3000"
    demo_base_url: str = "http://127.0.0.1:8000"

    @field_validator("gemini_api_key", "tavily_api_key", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mcp_search_arg_list(self) -> list[str]:
        return shlex.split(self.mcp_search_args)

    def live_unavailable_reasons(self) -> list[str]:
        """Why live mode cannot run right now (empty list = available)."""
        reasons = []
        if self.gemini_api_key is None:
            reasons.append("GEMINI_API_KEY is not set")
        if self.tavily_api_key is None:
            reasons.append("TAVILY_API_KEY is not set")
        return reasons


@lru_cache
def get_settings() -> Settings:
    return Settings()
