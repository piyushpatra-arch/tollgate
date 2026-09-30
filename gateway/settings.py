"""Runtime settings, read from environment variables prefixed with TOLLGATE_."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOLLGATE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tollgate.db"
    opa_url: str = "http://localhost:8181"
    ollama_api_base: str = "http://localhost:11434"
    config_dir: Path = Path("config")
    opa_timeout_s: float = 2.0
    model_timeout_s: float = 180.0
    pii_score_threshold: float = 0.4
