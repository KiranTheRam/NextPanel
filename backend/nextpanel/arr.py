"""HTTP clients for the two *arr backends NextPanel fronts.

Both mangarr and pullarr expose the same *arr-style API shape under
/api/v1 with X-Api-Key auth; only the metadata provider and the add-series
payload differ.
"""

from dataclasses import dataclass, field
from typing import Any

import httpx

from .models import MediaType

REQUEST_TIMEOUT = 30.0


class ArrError(Exception):
    """The target app rejected the call or could not be reached."""


class ArrConflict(ArrError):
    """The series is already in the target app's library."""


@dataclass
class SearchResult:
    media_type: MediaType
    provider: str
    provider_id: int
    title: str
    english_title: str = ""
    alt_titles: list[str] = field(default_factory=list)
    description: str = ""
    status: str = ""
    publisher: str = ""
    year: int | None = None
    cover_url: str = ""
    total_count: int | None = None  # chapters (manga) or issues (comics)
    in_library: bool = False


@dataclass
class SeriesStatus:
    series_id: int
    title: str
    total_count: int
    downloaded_count: int


class ArrClient:
    """One configured mangarr or pullarr instance."""

    app_name: str
    media_type: MediaType

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.configured:
            raise ArrError(f"{self.app_name} is not configured (URL + API key in Settings)")
        url = f"{self.base_url}/api/v1{path}"
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.request(
                    method, url, headers={"X-Api-Key": self.api_key}, **kwargs
                )
        except httpx.HTTPError as exc:
            raise ArrError(f"Cannot reach {self.app_name} at {self.base_url}: {exc}") from exc
        if resp.status_code == 409:
            raise ArrConflict(f"Series already in {self.app_name}'s library")
        if resp.status_code == 401:
            raise ArrError(f"{self.app_name} rejected the API key")
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = resp.text[:200]
            raise ArrError(f"{self.app_name} returned {resp.status_code}: {detail}")
        if resp.status_code == 204:
            return None
        return resp.json()

    async def ping(self) -> dict[str, Any]:
        return await self._request("GET", "/system/status")

    async def root_folders(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/rootfolders")

    async def search(self, query: str) -> list[SearchResult]:
        raise NotImplementedError

    async def list_series(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/series")

    async def series_detail(self, series_id: int) -> dict[str, Any]:
        """The library series with its chapters/issues."""
        return await self._request("GET", f"/series/{series_id}")

    async def add_series(self, provider_id: int, root_folder_id: int, *,
                         provider: str = "", english_title: str = "",
                         alt_titles: list[str] | None = None) -> int:
        """Add the series (monitored, search immediately); returns its id."""
        raise NotImplementedError

    async def find_series_id(self, provider_id: int, provider: str = "") -> int | None:
        """Locate an existing library series by metadata provider id."""
        raise NotImplementedError

    async def series_status(self, series_id: int) -> SeriesStatus:
        raise NotImplementedError


class MangarrClient(ArrClient):
    app_name = "mangarr"
    media_type = MediaType.MANGA
    provider = "mangaupdates"

    async def search(self, query: str) -> list[SearchResult]:
        data = await self._request("GET", "/search/metadata", params={"q": query})
        return [
            SearchResult(
                media_type=self.media_type,
                provider=r.get("provider", self.provider),
                provider_id=int(r["provider_id"]),
                title=r.get("title", ""),
                english_title=r.get("english_title") or "",
                alt_titles=r.get("alt_titles") or [],
                description=r.get("description") or "",
                status=r.get("status") or "",
                year=r.get("year"),
                cover_url=r.get("cover_url") or "",
                total_count=r.get("total_chapters"),
                in_library=bool(r.get("in_library")),
            )
            for r in data
        ]

    async def add_series(self, provider_id: int, root_folder_id: int, *,
                         provider: str = "", english_title: str = "",
                         alt_titles: list[str] | None = None) -> int:
        # mangarr accepts either metadata provider; discovery items are
        # AniList, search results are MangaUpdates
        id_key = "anilist_id" if provider == "anilist" else "mangaupdates_id"
        data = await self._request("POST", "/series", json={
            id_key: provider_id,
            "root_folder_id": root_folder_id,
            "monitored": True,
            "search_now": True,
            "english_title": english_title,
            "alt_titles": alt_titles or [],
        })
        return int(data["id"])

    async def find_series_id(self, provider_id: int, provider: str = "") -> int | None:
        id_key = "anilist_id" if provider == "anilist" else "mangaupdates_id"
        for s in await self.list_series():
            if s.get(id_key) == provider_id:
                return int(s["id"])
        return None

    async def series_status(self, series_id: int) -> SeriesStatus:
        data = await self._request("GET", f"/series/{series_id}")
        return SeriesStatus(
            series_id=series_id,
            title=data.get("title", ""),
            total_count=int(data.get("chapter_count") or 0),
            downloaded_count=int(data.get("downloaded_count") or 0),
        )


class PullarrClient(ArrClient):
    app_name = "pullarr"
    media_type = MediaType.COMIC
    provider = "comicvine"

    async def search(self, query: str) -> list[SearchResult]:
        data = await self._request("GET", "/search/metadata", params={"q": query})
        return [
            SearchResult(
                media_type=self.media_type,
                provider=r.get("provider", self.provider),
                provider_id=int(r["provider_id"]),
                title=r.get("title", ""),
                alt_titles=r.get("alt_titles") or [],
                description=r.get("description") or "",
                status=r.get("status") or "",
                publisher=r.get("publisher") or "",
                year=r.get("year"),
                cover_url=r.get("cover_url") or "",
                total_count=r.get("total_issues"),
                in_library=bool(r.get("in_library")),
            )
            for r in data
        ]

    async def add_series(self, provider_id: int, root_folder_id: int, *,
                         provider: str = "", english_title: str = "",
                         alt_titles: list[str] | None = None) -> int:
        data = await self._request("POST", "/series", json={
            "comicvine_id": provider_id,
            "root_folder_id": root_folder_id,
            "monitored": True,
            "search_now": True,
        })
        return int(data["id"])

    async def find_series_id(self, provider_id: int, provider: str = "") -> int | None:
        for s in await self.list_series():
            if s.get("comicvine_id") == provider_id:
                return int(s["id"])
        return None

    async def series_status(self, series_id: int) -> SeriesStatus:
        data = await self._request("GET", f"/series/{series_id}")
        return SeriesStatus(
            series_id=series_id,
            title=data.get("title", ""),
            total_count=int(data.get("issue_count") or 0),
            downloaded_count=int(data.get("downloaded_count") or 0),
        )

    async def discover_releases(self, days: int, first_issues: bool) -> list[dict[str, Any]]:
        """Recent store releases grouped by volume (pullarr proxies ComicVine)."""
        return await self._request("GET", "/discover/releases", params={
            "days": days, "first_issues": str(first_issues).lower(),
        })


def client_for(media_type: MediaType, values: dict[str, str]) -> ArrClient:
    if media_type == MediaType.MANGA:
        return MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    return PullarrClient(values["pullarr_url"], values["pullarr_api_key"])


def client_by_app(app: str, values: dict[str, str]) -> ArrClient | None:
    if app == "mangarr":
        return MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    if app == "pullarr":
        return PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
    return None
