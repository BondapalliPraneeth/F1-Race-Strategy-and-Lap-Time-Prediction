"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="F1_", extra="ignore")

    database_url: str = "postgresql+psycopg://f1:f1@localhost:5432/f1strategy"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    jolpica_base_url: str = "https://api.jolpi.ca/ergast/f1"
    http_min_interval_s: float = 0.35  # stay under Jolpica's burst limit
    http_timeout_s: float = 30.0
    http_max_retries: int = 6
    raw_cache_dir: Path = BACKEND_DIR / "data" / "raw_cache"

    artifacts_dir: Path = BACKEND_DIR / "artifacts"
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
