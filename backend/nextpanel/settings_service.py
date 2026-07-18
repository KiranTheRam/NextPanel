"""Runtime-editable settings stored in the Settings table."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Setting

DEFAULTS: dict[str, str] = {
    # mangarr connection (manga requests)
    "mangarr_url": "http://localhost:6996",
    "mangarr_api_key": "",
    "mangarr_root_folder_id": "",  # default root folder used on approval
    # pullarr connection (comic requests)
    "pullarr_url": "http://localhost:6997",
    "pullarr_api_key": "",
    "pullarr_root_folder_id": "",
    # Shared secret mangarr/pullarr must send in X-Webhook-Secret when
    # calling POST /api/v1/webhooks/{app}. Empty disables inbound webhooks.
    # Deliberately not masked: the admin needs to copy it into both apps.
    "webhook_secret": "",
    # Fallback polling of approved requests (webhooks give instant updates)
    "poll_interval_minutes": "10",
    # Allow open self-registration on the login page
    "registration_enabled": "true",
}

SECRET_KEYS = {"mangarr_api_key", "pullarr_api_key"}


def validate(values: dict[str, str]) -> None:
    if "poll_interval_minutes" in values:
        try:
            minutes = int(values["poll_interval_minutes"])
        except (TypeError, ValueError):
            raise ValueError("poll_interval_minutes must be a whole number") from None
        if minutes < 1:
            raise ValueError("poll_interval_minutes must be at least 1")
    for key in ("mangarr_url", "pullarr_url"):
        if key in values and values[key] and not values[key].startswith(("http://", "https://")):
            raise ValueError(f"{key} must start with http:// or https://")
    for key in ("mangarr_root_folder_id", "pullarr_root_folder_id"):
        if key in values and values[key].strip():
            try:
                int(values[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a root folder id (number)") from None


async def get_all(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Setting))).scalars().all()
    values = dict(DEFAULTS)
    values.update({r.key: r.value for r in rows if r.key in DEFAULTS})
    return values


async def get(session: AsyncSession, key: str) -> str:
    row = await session.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, "")


async def set_many(session: AsyncSession, values: dict[str, str]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
    await session.commit()
