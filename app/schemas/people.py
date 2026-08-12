from pydantic import BaseModel, Field
from datetime import date


class PersonCreate(BaseModel):
    name: str
    nickname: str | None = None
    pronouns: str | None = None
    relationship_label: str | None = None
    birthday_month: int | None = None
    birthday_day: int | None = None
    birthday_year: int | None = None
    how_we_met: str | None = None
    met_date: str | None = None
    location: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    occupation: str | None = None
    hobbies: str | None = None
    bio: str | None = None
    checkin_cadence_days: int | None = None
    instagram_username: str | None = None
    instagram_enabled: bool = False
    archived: bool = False


class PersonUpdate(PersonCreate):
    pass


class PersonResponse(BaseModel):
    id: int
    name: str
    nickname: str | None = None
    pronouns: str | None = None
    relationship_label: str | None = None
    birthday_month: int | None = None
    birthday_day: int | None = None
    birthday_year: int | None = None
    how_we_met: str | None = None
    met_date: str | None = None
    location: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    occupation: str | None = None
    hobbies: str | None = None
    bio: str | None = None
    ai_summary: str | None = None
    checkin_cadence_days: int | None = None
    last_contact_date: str | None = None
    relationship_state: str | None = None
    instagram_username: str | None = None
    instagram_enabled: bool = False
    archived: bool = False
    tags: list[str] = []
    friend_rank: int | None = None


class TagResponse(BaseModel):
    name: str
