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


_RENDERABLE_IMAGE_TYPES = {"jpeg", "jpg", "png", "gif", "webp", "avif"}


def _parse_asset_datetime(asset: dict) -> Optional[dt.datetime]:
    """Prefer `localDateTime` (Immich's own timezone-adjusted local capture time) over
    `fileCreatedAt` (which may be in UTC) so day/month comparisons reflect when the photo was
    actually taken locally, not clipped by a UTC boundary."""
    raw = asset.get("localDateTime") or asset.get("fileCreatedAt")
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _asset_local_year(asset: dict) -> Optional[int]:
    parsed = _parse_asset_datetime(asset)
    return parsed.year if parsed else None


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

    def get_person_assets(self, person_id: str, max_pages: int = 5) -> list[dict]:
        """Fetch all assets tagged with a given person.

        Note: the simpler `GET /people/{id}/assets` endpoint (getPersonAssets) is not reliably
        available across Immich server versions/deployments (some return 404), so we use the
        documented, paginated `POST /search/metadata` endpoint with a `personIds` filter instead -
        this is also what Immich's own support recommends for anything beyond trivial libraries.
        """
        results: list[dict] = []
        page = 1
        while page <= max_pages:
            body = {"personIds": [person_id], "size": 200, "page": page}
            data = self._post("/search/metadata", json=body)
            assets = data.get("assets", {}) if isinstance(data, dict) else {}
            items = assets.get("items", [])
            results.extend(items)
            next_page = assets.get("nextPage")
            if not next_page or not items:
                break
            page += 1
        return results

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
        """Immich's built-in memories endpoint - always relative to *today*.

        Note: this only returns results if Immich's own "Generate Memories" background job has
        already run for today's date and didn't filter out the assets for its own reasons - it's
        a pre-compiled collection, not a live search. See `on_this_day_with_fallback()` for a
        more reliable path that also works when this returns nothing.
        """
        try:
            data = self._get("/memories", params={"type": "on_this_day"})
        except ImmichError:
            return []
        if isinstance(data, list):
            return data
        return []

    def on_this_day_with_fallback(self, years_back: int = 15) -> list[dict]:
        """Prefer Immich's native pre-compiled memories; if that's empty (e.g. the background
        job hasn't run, or it filtered out older/untagged assets), fall back to directly
        searching year-by-year and group the results into the same shape the native endpoint
        returns (`[{"data": {"year": N}, "assets": [...]}, ...]`) so callers don't need to care
        which path was used."""
        native = self.on_this_day()
        if native:
            return native

        today = dt.date.today()
        assets = self.assets_on_date_across_years(today.month, today.day, years_back=years_back)
        by_year: dict[int, list[dict]] = {}
        for asset in assets:
            year = _asset_local_year(asset)
            if year is None:
                continue
            by_year.setdefault(year, []).append(asset)

        return [
            {"data": {"year": year}, "assets": by_year[year]}
            for year in sorted(by_year.keys(), reverse=True)
        ]

    def assets_on_date_across_years(self, month: int, day: int, years_back: int = 15,
                                     person_id: Optional[str] = None) -> list[dict]:
        """Browse "what happened on this date" for any arbitrary day across past years.

        Immich stores asset timestamps in UTC, so a naive same-UTC-day query window can silently
        clip photos taken in the early morning or late evening in the photographer's local
        timezone (e.g. a 9am local photo taken in a UTC-8 timezone is stored as 5pm UTC the
        *previous* day). To avoid that, we pad the query window by 24h on each side and then
        filter precisely in Python using the asset's `localDateTime` field (Immich's own
        timezone-adjusted local capture time), falling back to `fileCreatedAt` if that's missing.
        """
        results = []
        this_year = dt.date.today().year
        for y in range(this_year - years_back, this_year + 1):
            try:
                target = dt.date(y, month, day)
            except ValueError:
                continue  # e.g. Feb 29 on non-leap years
            window_start = dt.datetime.combine(target, dt.time.min) - dt.timedelta(hours=24)
            window_end = dt.datetime.combine(target, dt.time.min) + dt.timedelta(hours=48)
            body = {
                "takenAfter": window_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "takenBefore": window_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "size": 200,
            }
            if person_id:
                body["personIds"] = [person_id]
            try:
                data = self._post("/search/metadata", json=body)
                items = data.get("assets", {}).get("items", [])
            except ImmichError:
                continue
            for asset in items:
                local_dt = _parse_asset_datetime(asset)
                if local_dt and local_dt.month == month and local_dt.day == day:
                    results.append(asset)
        return results

    def thumbnail_url(self, asset_id: str) -> str:
        return f"{self.base_url}/assets/{asset_id}/thumbnail"

    def original_url(self, asset_id: str) -> str:
        return f"{self.base_url}/assets/{asset_id}/original"

    def fetch_asset_preview_bytes(self, asset_id: str) -> tuple[bytes, str]:
        """High-quality, web-safe image for display. Prefers the full-resolution original file,
        but falls back to the small JPEG thumbnail when the original isn't a browser-renderable
        format (e.g. HEIC/RAW) so the card never shows a broken image."""
        content, content_type = self.fetch_asset_bytes(asset_id, size="original")
        if content_type.split("/")[-1].lower() not in _RENDERABLE_IMAGE_TYPES:
            content, content_type = self.fetch_asset_bytes(asset_id, size="thumbnail")
        return content, content_type

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

    def asset_face_center(self, asset_id: str) -> tuple[float, float] | None:
        """Approximate centre of an asset's first detected face, as (x_pct, y_pct) in 0-100.
        Used to keep object-fit image crops on the faces (so people are front and centre).
        Returns None when Immich has no face info or the API is unreachable."""
        try:
            data = self._get(f"/assets/{asset_id}")
        except ImmichError:
            return None
        people = data.get("people") or []
        for person in people:
            bb = person.get("boundingBox") or person.get("bounding_box")
            coords = None
            if isinstance(bb, dict):
                x1, y1, x2, y2 = bb.get("x1"), bb.get("y1"), bb.get("x2"), bb.get("y2")
                if all(v is not None for v in (x1, y1, x2, y2)):
                    coords = (float(x1), float(y1), float(x2), float(y2))
            elif isinstance(bb, str):
                parts = [float(x) for x in bb.split(",")]
                if len(parts) == 4:
                    coords = tuple(parts)
            if coords:
                cx = (coords[0] + coords[2]) / 2
                cy = (coords[1] + coords[3]) / 2
                return (round(cx * 100, 1), round(cy * 100, 1))
        return None

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
