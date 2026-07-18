from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Process-level configuration (env vars / .env). Runtime-editable
    settings (mangarr/pullarr connections, defaults) live in the Settings
    table."""

    model_config = SettingsConfigDict(env_prefix="NEXTPANEL_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    host: str = "0.0.0.0"
    port: int = 6995
    log_level: str = "INFO"
    # VAPID contact claim sent with web-push deliveries (a mailto: URI push
    # services can use to reach the operator about problems)
    vapid_sub: str = "mailto:admin@nextpanel.local"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nextpanel.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"


config = AppConfig()
