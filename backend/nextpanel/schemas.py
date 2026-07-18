from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import MediaType, RequestStatus
from .security import safe_cover_url


# ------------------------------------------------------------------- auth

class AuthStatusOut(BaseModel):
    setup_required: bool
    registration_enabled: bool


class CredentialsIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_admin: bool
    created_at: datetime
    request_count: int = 0


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class UserUpdateIn(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_admin: bool | None = None


# ------------------------------------------------------------------ search

class SearchResultOut(BaseModel):
    media_type: MediaType
    provider: str
    provider_id: int
    title: str
    english_title: str = ""
    alt_titles: list[str] = Field(default_factory=list)
    description: str = ""
    status: str = ""
    publisher: str = ""
    year: int | None = None
    cover_url: str = ""
    total_count: int | None = None
    in_library: bool = False
    # status of an existing NextPanel request for this title, if any
    request_id: int | None = None
    request_status: RequestStatus | None = None


class SearchOut(BaseModel):
    results: list[SearchResultOut]
    # app name -> error message, for apps that failed or are unconfigured
    errors: dict[str, str] = Field(default_factory=dict)


# ------------------------------------------------------------------ detail

class ChapterOut(BaseModel):
    number: float | None = None
    label: str = ""  # display number, e.g. "12" or "Annual 1"
    title: str = ""
    volume: int | None = None
    downloaded: bool = False
    monitored: bool = False


class StaffOut(BaseModel):
    name: str
    role: str = ""


class TitleDetailOut(BaseModel):
    media_type: MediaType
    provider: str
    provider_id: int
    title: str
    english_title: str = ""
    native_title: str = ""
    description: str = ""
    status: str = ""
    format: str = ""
    year: int | None = None
    end_year: int | None = None
    cover_url: str = ""
    banner_url: str = ""
    genres: list[str] = Field(default_factory=list)
    score: int | None = None
    publisher: str = ""
    country: str = ""
    staff: list[StaffOut] = Field(default_factory=list)
    total_count: int | None = None  # chapters (manga) or issues (comics)
    volumes: int | None = None
    downloaded_count: int = 0
    # chapter lists only exist once the series is in mangarr/pullarr
    chapters: list[ChapterOut] = Field(default_factory=list)
    chapters_available: bool = False
    in_library: bool = False
    library_series_id: int | None = None
    request_id: int | None = None
    request_status: RequestStatus | None = None


# ---------------------------------------------------------------- requests

class RequestCreateIn(BaseModel):
    media_type: MediaType
    provider: str
    provider_id: int
    title: str
    english_title: str = ""
    alt_titles: list[str] = Field(default_factory=list)
    year: int | None = None
    cover_url: str = ""
    description: str = ""

    @field_validator("cover_url")
    @classmethod
    def restrict_cover_url(cls, value: str) -> str:
        return safe_cover_url(value)


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    media_type: MediaType
    provider: str
    provider_id: int
    title: str
    english_title: str
    year: int | None
    cover_url: str
    description: str
    status: RequestStatus
    note: str
    remote_series_id: int | None
    downloaded_count: int
    total_count: int
    created_at: datetime
    updated_at: datetime
    username: str = ""
    decided_by_username: str = ""


class ApproveIn(BaseModel):
    root_folder_id: int | None = None  # override the configured default


class DenyIn(BaseModel):
    reason: str = ""


# ---------------------------------------------------------------- settings

class ConnectionTestOut(BaseModel):
    ok: bool
    version: str = ""
    message: str = ""


class WebhookIn(BaseModel):
    event: str = ""
    app: str = ""
    series_id: int


class PushSubscriptionIn(BaseModel):
    """Browser PushSubscription.toJSON() shape (extra fields ignored)."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: dict[str, str] = Field(default_factory=dict)
