"""Thin client around the Immich REST API.

Only a handful of endpoints are used - see docs at https://immich.app/docs/api/
All calls are defensive: on any failure we raise ImmichError with a friendly
message rather than letting httpx exceptions bubble up to the user.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import httpx


class ImmichError(Exception):
    pass


class ImmichClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0):
        if not base_url:
            raise ImmichError("Immich URL is not configured. Add it in Settings.")
        if not api_key:
            raise ImmichError("Immich API key is not configured. Add it in Settings.")
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api"):
            self.base_url += "/api"
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, accept="application/json"):
        return {"x-api-key": self.api_key, "Accept": accept}

    def _get(self, path, params=None):
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(f"{self.base_url}{path}", headers=self._headers(), params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise ImmichError(f"Immich returned {e.response.status_code} for {path}")
        except httpx.RequestError as e:
            raise ImmichError(f"Could not reach Immich server: {e}")

    def _post(self, path, json=None):
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}{path}", headers=self._headers(), json=json or {})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise ImmichError(f"Immich returned {e.response.status_code} for {path}")
        except httpx.RequestError as e:
            raise ImmichError(f"Could not reach Immich server: {e}")

    def test_connection(self) -> dict:
        return self._get("/server/ping")

    def list_people(self, with_hidden: bool = False) -> list[dict]:
        data = self._get("/people", params={"withHidden": str(with_hidden).lower()})
        # Immich wraps in {"people": [...], "total": N, "hidden": N} on newer versions
        if isinstance(data, dict) and "people" in data:
            return data["people"]
        return data

    def get_person(self, person_id: str) -> dict:
        return self._get(f"/people/{person_id}")

    def get_person_assets(self, person_id: str) -> list[dict]:
        return self._get(f"/people/{person_id}/assets")

    def search_by_person(self, person_id: str, taken_after: Optional[str] = None,
                          taken_before: Optional[str] = None, size: int = 100) -> list[dict]:
        body = {"personIds": [person_id], "size": size}
        if taken_after:
            body["takenAfter"] = taken_after
        if taken_before:
            body["takenBefore"] = taken_before
        data = self._post("/search/metadata", json=body)
        return data.get("assets", {}).get("items", [])

    def search_by_date_range(self, taken_after: str, taken_before: str, size: int = 100) -> list[dict]:
        body = {"takenAfter": taken_after, "takenBefore": taken_before, "size": size}
        data = self._post("/search/metadata", json=body)
        return data.get("assets", {}).get("items", [])

    def on_this_day(self) -> list[dict]:
        """Immich's built-in memories endpoint - always relative to *today*."""
        try:
            data = self._get("/memories", params={"type": "on_this_day"})
        except ImmichError:
            return []
        if isinstance(data, list):
            return data
        return []

    def assets_on_date_across_years(self, month: int, day: int, years_back: int = 15,
                                     person_id: Optional[str] = None) -> list[dict]:
        """Browse "what happened on this date" for any arbitrary day (not just today),
        looping year by year since Immich's memories API only covers 'today'."""
        results = []
        this_year = dt.date.today().year
        for y in range(this_year - years_back, this_year + 1):
            try:
                start = dt.date(y, month, day)
            except ValueError:
                continue  # e.g. Feb 29 on non-leap years
            end = start + dt.timedelta(days=1)
            body = {
                "takenAfter": f"{start.isoformat()}T00:00:00.000Z",
                "takenBefore": f"{end.isoformat()}T00:00:00.000Z",
                "size": 200,
            }
            if person_id:
                body["personIds"] = [person_id]
            try:
                data = self._post("/search/metadata", json=body)
                items = data.get("assets", {}).get("items", [])
                results.extend(items)
            except ImmichError:
                continue
        return results

    def thumbnail_url(self, asset_id: str) -> str:
        return f"{self.base_url}/assets/{asset_id}/thumbnail"

    def original_url(self, asset_id: str) -> str:
        return f"{self.base_url}/assets/{asset_id}/original"

    def fetch_asset_bytes(self, asset_id: str, size: str = "thumbnail") -> tuple[bytes, str]:
        path = f"/assets/{asset_id}/thumbnail" if size == "thumbnail" else f"/assets/{asset_id}/original"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(f"{self.base_url}{path}", headers=self._headers(accept="*/*"))
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "image/jpeg")
        except httpx.HTTPStatusError as e:
            raise ImmichError(f"Immich returned {e.response.status_code} fetching asset")
        except httpx.RequestError as e:
            raise ImmichError(f"Could not reach Immich server: {e}")

    def person_thumbnail_bytes(self, person_id: str) -> tuple[bytes, str]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(f"{self.base_url}/people/{person_id}/thumbnail",
                                headers=self._headers(accept="*/*"))
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "image/jpeg")
        except httpx.HTTPStatusError as e:
            raise ImmichError(f"Immich returned {e.response.status_code} fetching person thumbnail")
        except httpx.RequestError as e:
            raise ImmichError(f"Could not reach Immich server: {e}")


def get_client_from_settings(db) -> "ImmichClient":
    from ..settings_store import get_setting
    url = get_setting(db, "immich_url")
    key = get_setting(db, "immich_api_key")
    return ImmichClient(url, key)
