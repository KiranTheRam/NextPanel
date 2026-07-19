from pathlib import Path
from urllib.parse import urlparse

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
    # Public deployments terminate TLS before the application.  Keep this on
    # by default so a proxy/configuration mistake cannot issue a reusable HTTP
    # session cookie.  Set false only for local HTTP development.
    session_cookie_secure: bool = True
    # Cloudflare Access SSO. Both values are required before SSO is enabled.
    # The team domain is the token issuer (for example,
    # https://my-team.cloudflareaccess.com); the audience is copied from the
    # Access application's Additional settings page.
    cloudflare_access_team_domain: str = ""
    cloudflare_access_audience: str = ""
    # This switch is deliberately effective only when SSO is fully configured
    # so a typo in one of the values above cannot disable every login method.
    local_login_enabled: bool = True
    # Optional comma-separated identities that should be promoted to admin on
    # SSO login. The first user on an empty installation is always an admin.
    cloudflare_access_admin_emails: str = ""
    # VAPID contact claim sent with web-push deliveries (a mailto: URI push
    # services can use to reach the operator about problems)
    vapid_sub: str = "mailto:admin@nextpanel.local"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nextpanel.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def cloudflare_team_domain(self) -> str:
        return self.cloudflare_access_team_domain.strip().rstrip("/")

    @property
    def sso_enabled(self) -> bool:
        domain = self.cloudflare_team_domain
        if not domain or not self.cloudflare_access_audience.strip():
            return False
        parsed = urlparse(domain)
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.endswith(".cloudflareaccess.com")
            and not parsed.path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        )

    @property
    def local_login_available(self) -> bool:
        return self.local_login_enabled or not self.sso_enabled

    @property
    def cloudflare_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.cloudflare_access_admin_emails.split(",")
            if email.strip()
        }


config = AppConfig()
