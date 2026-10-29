from __future__ import annotations

import re
import zoneinfo
from functools import lru_cache
from pathlib import Path
from typing import Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high"]


def check_cron(expr: str) -> str:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"DIGEST_CRON needs 5 fields, got {expr!r}")
    # APScheduler 3 numbers day_of_week from Monday=0, so cron's `0` would mean Monday.
    if re.search(r"\d", fields[4]):
        raise ValueError("DIGEST_CRON: write the day of week as names (SUN, MON-FRI), not numbers")
    return expr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    anthropic_api_key: SecretStr | None = None
    llm_backend: Literal["anthropic", "fake"] = "anthropic"
    extract_model: str = "claude-sonnet-5-5"
    score_model: str | None = None
    digest_model: str = "claude-sonnet-5-5"
    outline_model: str = "claude-haiku-5-5"
    brief_model: str = "claude-haiku-5-5"
    llm_effort: Effort = "medium"

    telegram_bot_token: SecretStr | None = None
    telegram_allowed_chat_id: int | None = None

    cookies_browser: str = "chrome"
    cookies_browser_profile: str | None = None
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"

    keep_threshold: int = Field(default=60, ge=0, le=100)
    keep_media: bool = False
    fetch_delay_seconds: float = Field(default=20.0, ge=0)
    import_gap_seconds: float = Field(default=180.0, ge=1)
    import_daily_cap: int = Field(default=100, ge=1)
    import_max_bytes: int = Field(default=2 * 1024**3, ge=1)
    upload_max_bytes: int = Field(default=25 * 1024**2, ge=1)

    digest_cron: str = "0 18 * * SUN"
    timezone: str = "America/New_York"

    web_host: str = "127.0.0.1"
    web_port: int = 8000
    data_dir: Path = Path("./data")

    @field_validator("timezone")
    @classmethod
    def _tz_exists(cls, v: str) -> str:
        zoneinfo.ZoneInfo(v)
        return v

    @field_validator("digest_cron")
    @classmethod
    def _cron_parses(cls, v: str) -> str:
        v = check_cron(v)
        CronTrigger.from_crontab(v)
        return v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sift.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "imports"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def run_lock_path(self) -> Path:
        return self.data_dir / "worker.lock"

    @property
    def effective_score_model(self) -> str:
        return self.score_model or self.extract_model

    @property
    def llm_configured(self) -> bool:
        return self.llm_backend == "fake" or self.anthropic_api_key is not None

    def secrets(self) -> list[str]:
        out: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr) and value.get_secret_value():
                out.append(value.get_secret_value())
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
