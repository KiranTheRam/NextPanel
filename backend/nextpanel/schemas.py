from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import MediaType, RequestStatus


# ------------------------------------------------------------------- auth

class AuthStatusOut(BaseModel):
    setup_required: bool
    registration_enabled: bool


class CredentialsIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_admin: bool
    created_at: datetime
    request_count: int = 0


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    is_admin: bool = False


class UserUpdateIn(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=128)
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
