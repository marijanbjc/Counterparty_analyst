from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "config" / "internal_config.yaml"


class YamlSource(PydanticBaseSettingsSource):
    def get_field_value(self, field, field_name) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if not CONFIG_FILE.exists():
            return {}
        return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_host: str
    app_port: int
    app_debug: bool

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    snapshot_path: str

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: int
    llm_max_retries: int

    auth_login: str
    auth_password: str
    auth_token_ttl_hours: int

    context_token_budget: int
    context_anchor_max_contractors: int

    risk_active_execproc_revenue_share: float
    risk_active_execproc_absolute: int
    risk_active_execproc_count_without_revenue: int
    risk_negative_factors_threshold: int
    risk_many_execproc_threshold: int

    zsk_mask_yellow_red: bool

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlSource(settings_cls),
            file_secret_settings,
        )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def snapshot_file(self) -> Path:
        path = Path(self.snapshot_path)
        return path if path.is_absolute() else ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
