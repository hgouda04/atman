# Appointment → Google Calendar Middleware

This service fetches appointments from a 3rd-party API and creates Google Calendar events.

## Features
- Pulls appointments from `THIRD_PARTY_BASE_URL/appointments`.
- Authenticates to the third-party API using HTTP Basic Auth (`THIRD_PARTY_USERNAME` / `THIRD_PARTY_PASSWORD`).
- Avoids duplicates by storing `source_appointment_id` in Google event private extended properties.
- Exposes HTTP endpoints:
  - `GET /health`
  - `POST /sync?updated_since=<ISO8601>`

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy environment template and fill values:
   ```bash
   cp .env.example .env
   ```
3. Export environment variables (or use your process manager):
   ```bash
   export THIRD_PARTY_BASE_URL="https://your-provider.example/api"
   export THIRD_PARTY_USERNAME="your-username"
   export THIRD_PARTY_PASSWORD="your-password"
   export GOOGLE_CALENDAR_ID="your-calendar-id@group.calendar.google.com"
   export GOOGLE_CREDENTIALS_FILE="./service-account.json"
   ```
4. Share your Google Calendar with the service account email from `service-account.json`.

## Run
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Appointment payload expectation
The third-party API should return a JSON array like:

```json
[
  {
    "id": "apt_123",
    "title": "Dental Checkup",
    "description": "Room 4B",
    "start_time": "2026-02-20T10:00:00+00:00",
    "end_time": "2026-02-20T10:30:00+00:00"
  }
]
```

## Trigger sync
```bash
curl -X POST "http://localhost:8000/sync"
```

With updated filter:
```bash
curl -X POST "http://localhost:8000/sync?updated_since=2026-02-20T00:00:00+00:00"
```

## What to do from here (recommended)
1. **Run one end-to-end sync in a test calendar first** to verify title/time mapping and timezone behavior.
2. **Put the sync on a schedule** (e.g., cron, Cloud Scheduler, GitHub Actions, or your orchestrator) so `/sync` runs every 1–5 minutes.
3. **Add observability**: capture request logs and sync counts (`fetched/synced/skipped`) in your logging or APM system.
4. **Add retry/backoff** around third-party and Google API failures before production rollout.
5. **Add update/cancel handling** if the source system changes or removes appointments after initial create.
6. **Protect the `/sync` endpoint** behind auth or a private network, since it can trigger writes to Google Calendar.
