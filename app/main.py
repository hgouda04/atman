from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from google.oauth2 import service_account
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Settings:
    third_party_base_url: str = os.getenv("THIRD_PARTY_BASE_URL", "")
    third_party_username: str = os.getenv("THIRD_PARTY_USERNAME", "")
    third_party_password: str = os.getenv("THIRD_PARTY_PASSWORD", "")
    google_calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "")
    google_credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "")


class ThirdPartyAppointmentClient:
    """Client for a 3rd-party API endpoint that exposes appointments via Basic Auth."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def get_appointments(self, updated_since: datetime | None = None) -> list[dict[str, Any]]:
        url = f"{self.base_url}/appointments"
        params: dict[str, str] = {}
        if updated_since:
            params["updated_since"] = updated_since.astimezone(timezone.utc).isoformat()

        response = requests.get(
            url,
            params=params,
            auth=(self.username, self.password),
            timeout=30,
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Expected appointment list from third-party API")
        return payload


class GoogleCalendarService:
    """Handles writing appointments as events in Google Calendar."""

    def __init__(self, credentials_file: str, calendar_id: str) -> None:
        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(
            credentials_file,
            scopes=scopes,
        )
        self.calendar_id = calendar_id
        self.service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def event_exists(self, appointment_id: str) -> bool:
        events = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                privateExtendedProperty=[f"source_appointment_id={appointment_id}"],
                maxResults=1,
            )
            .execute()
        )
        return bool(events.get("items"))

    def create_event(self, appointment: dict[str, Any]) -> dict[str, Any]:
        start = appointment["start_time"]
        end = appointment["end_time"]
        title = appointment.get("title", "Appointment")
        notes = appointment.get("description", "")
        appointment_id = str(appointment["id"])

        event_body = {
            "summary": title,
            "description": notes,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "extendedProperties": {
                "private": {
                    "source_appointment_id": appointment_id,
                }
            },
        }

        return (
            self.service.events()
            .insert(calendarId=self.calendar_id, body=event_body)
            .execute()
        )


class SyncService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.third_party_client = ThirdPartyAppointmentClient(
            base_url=settings.third_party_base_url,
            username=settings.third_party_username,
            password=settings.third_party_password,
        )
        self.google_calendar = GoogleCalendarService(
            credentials_file=settings.google_credentials_file,
            calendar_id=settings.google_calendar_id,
        )

    def sync_appointments(self, updated_since: datetime | None = None) -> dict[str, int]:
        appointments = self.third_party_client.get_appointments(updated_since=updated_since)
        synced = 0
        skipped = 0

        for appointment in appointments:
            appointment_id = str(appointment.get("id", ""))
            if not appointment_id:
                logger.warning("Skipping appointment with missing id: %s", appointment)
                skipped += 1
                continue

            if self.google_calendar.event_exists(appointment_id):
                skipped += 1
                continue

            self.google_calendar.create_event(appointment)
            synced += 1

        return {"fetched": len(appointments), "synced": synced, "skipped": skipped}


app = FastAPI(title="Appointment to Google Calendar Middleware")
settings = Settings()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sync")
def sync(updated_since: str | None = None) -> dict[str, int]:
    try:
        parsed_updated_since = (
            datetime.fromisoformat(updated_since) if updated_since else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid updated_since format") from exc

    try:
        service = SyncService(settings)
        result = service.sync_appointments(updated_since=parsed_updated_since)
    except requests.RequestException as exc:
        logger.exception("Third-party API error")
        raise HTTPException(status_code=502, detail="Failed to fetch appointments") from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="Google credentials file was not found",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected sync error")
        raise HTTPException(status_code=500, detail="Sync failed") from exc

    return result
