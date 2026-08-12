from pydantic import BaseModel


class JournalCreate(BaseModel):
    title: str | None = None
    body: str
    entry_date: str  # ISO date
    event_type: str | None = "note"
    energy_cost: str | None = None
    location: str | None = None
    person_ids: list[int] = []


class JournalUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    entry_date: str | None = None
    event_type: str | None = None
    energy_cost: str | None = None
    location: str | None = None
    person_ids: list[int] | None = None


class JournalEntryResponse(BaseModel):
    id: int
    title: str | None = None
    body: str | None = None
    entry_date: str
    event_type: str | None = None
    energy_cost: str | None = None
    location: str | None = None
    source: str | None = None
    created_at: str | None = None
    people: list[str] = []


class JournalImageResponse(BaseModel):
    id: int
    immich_asset_id: str | None = None
    upload_path: str | None = None
    caption: str | None = None
