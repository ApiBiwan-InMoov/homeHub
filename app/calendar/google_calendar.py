# app/calendar/google_calendar.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, List, Dict

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

class GoogleCalendar:
    def __init__(self, client_secret_path: str, token_path: str, calendar_id: str):
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self.calendar_id = calendar_id
        self._service = None

    def service(self):
        if self._service:
            return self._service

        creds: Optional[Credentials] = None
        try:
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        except Exception:
            creds = None

        if not creds or not creds.valid:
            # Simplest flow: open a local browser window for consent the first time.
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def next_event(self) -> Optional[Dict]:
        now = datetime.now(timezone.utc).isoformat()
        result = self.service().events().list(
            calendarId=self.calendar_id,
            timeMin=now,
            maxResults=1,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        items = result.get("items", [])
        return items[0] if items else None

    def upcoming_events(self, limit: int = 10) -> List[Dict]:
        now = datetime.now(timezone.utc).isoformat()
        result = self.service().events().list(
            calendarId=self.calendar_id,
            timeMin=now,
            maxResults=limit,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])

