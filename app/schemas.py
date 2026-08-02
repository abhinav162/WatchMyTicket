"""Pydantic schemas shared across scrapers, services and the REST API."""

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Show(BaseModel):
    """A single bookable show found on a ticketing platform."""

    movie: str
    city: str
    theatre: str
    format: str = "2D"
    language: str = ""
    date: date_type
    time: str
    booking_url: str = ""


class WatchCreate(BaseModel):
    movie: str
    city: str
    date: date_type
    formats: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    theatres: list[str] = Field(default_factory=list)


class WatchUpdate(BaseModel):
    movie: str | None = None
    city: str | None = None
    date: date_type | None = None
    formats: list[str] | None = None
    languages: list[str] | None = None
    theatres: list[str] | None = None
    status: str | None = None


class WatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    movie: str
    city: str
    date: date_type
    formats: list[str]
    languages: list[str]
    theatres: list[str]
    status: str
    last_checked: datetime | None
    created_at: datetime
