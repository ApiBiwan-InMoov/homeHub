# app/deps.py
from __future__ import annotations

import inspect
import os
import threading
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

# ---------------------- Google Calendar ----------------------
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import settings

# app/deps.py


# ... (rest of imports and code unchanged)

_ipx_singleton = None


def get_ipx():
    """FastAPI dependency to get a shared IPX client instance."""
    global _ipx_singleton
    if _ipx_singleton is None:
        ipx_class = _load_ipx_class()

        # Common kwargs we *might* have; filter to what the class actually accepts
        raw_kwargs = {
            "host": settings.ipx_host,
            "port": settings.ipx_port,
            "user": getattr(settings, "ipx_user", "") or "",
            "password": getattr(settings, "ipx_pass", "") or "",
        }

        # Build kwargs safely based on the constructor signature
        try:
            sig = inspect.signature(IPXClass)
            params = sig.parameters.keys()
        except (TypeError, ValueError):
            params = ()

        kwargs = {k: v for k, v in raw_kwargs.items() if k in params}

        # If the client uses base_url instead of host/port, map it
        if "base_url" in params and ("host" in raw_kwargs or "port" in raw_kwargs):
            host = settings.ipx_host
            port = settings.ipx_port
            kwargs.pop("host", None)
            kwargs.pop("port", None)
            kwargs["base_url"] = f"http://{host}:{port}"

        _ipx_singleton = ipx_class(**kwargs)
    return _ipx_singleton


# Include both readonly and edit scopes; UI may still restrict writes per-calendar.
GCAL_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleCalendar:
    """
    Small convenience wrapper around Google Calendar API.

    client_secret_path: path to OAuth client secret JSON (from Google Cloud Console)
    token_path:         path where the OAuth token will be stored/refreshed
    """

    def __init__(self, client_secret_path: str, token_path: str, scopes: list[str] | None = None):
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self.scopes = scopes or GCAL_SCOPES
        self._creds: Credentials | None = None
        self._svc = None
        self._lock = threading.Lock()
        self._cal_cache: Optional[list[dict[str, Any]]] = None

    # ---- Auth / service ----
    def _remove_bad_token(self) -> None:
        try:
            if os.path.exists(self.token_path):
                os.remove(self.token_path)
        except Exception:
            pass

    def _load_creds(self) -> Credentials:
        creds = None
        # Load token from disk if present
        try:
            if os.path.exists(self.token_path):
                creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)
        except Exception:
            # corrupted token file – start fresh
            self._remove_bad_token()
            creds = None

        # Refresh or run flow if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    # refresh failed (revoked?), redo full flow
                    self._remove_bad_token()
                    creds = None

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_path, self.scopes)
                creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())

        return creds

    def service(self):
        """Return a cached googleapiclient Calendar service."""
        with self._lock:
            if self._svc is not None:
                return self._svc
            self._creds = self._load_creds()
            # cache_discovery=False avoids file cache warnings
            self._svc = build("calendar", "v3", credentials=self._creds, cache_discovery=False)
            return self._svc

    def _handle_scope_error(self, e: HttpError) -> None:
        """
        If we get a 403 insufficientPermissions, delete token so the next call
        triggers OAuth flow with the current (broader) SCOPES.
        """
        if (
            getattr(e, "status_code", None) == 403
            or getattr(e, "resp", None)
            and getattr(e.resp, "status", None) == 403
        ):
            try:
                data = e.error_details if hasattr(e, "error_details") else None
            except Exception:
                data = None
            # Regardless of payload, nuke token to re-consent next time.
            self._remove_bad_token()
            # Also drop cached service so next call rebuilds.
            with self._lock:
                self._svc = None
                self._creds = None

    # ---- API helpers ----
    def list_calendars(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Return calendars visible to the account (with a small in-process cache)."""
        if self._cal_cache is not None and not force_refresh:
            return self._cal_cache

        svc = self.service()
        items: list[dict[str, Any]] = []
        page_token = None
        try:
            while True:
                resp = svc.calendarList().list(pageToken=page_token).execute()
                items.extend(resp.get("items", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as e:
            self._handle_scope_error(e)
            # re-raise so caller can decide what to do (UI can show a reconnect prompt)
            raise

        # Normalize
        normalized = []
        for it in items:
            normalized.append(
                {
                    "id": it.get("id"),
                    "summary": it.get("summary"),
                    "accessRole": it.get("accessRole"),  # "owner", "writer", "reader", ...
                    "primary": bool(it.get("primary")),
                    "timeZone": it.get("timeZone"),
                }
            )
        self._cal_cache = normalized
        return normalized

    # app/deps.py  — inside class GoogleCalendar

    def upcoming_events(
        self,
        max_results: int = 10,
        calendars: Optional[list[str]] = None,
        *,
        # backward-compat kwargs:
        limit: int | None = None,
        calendar_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return next events across one or more calendars.
        Accepts both (max_results, calendars=[...]) and legacy (limit, calendar_id=...).
        """
        # normalize args for backward compatibility
        if limit is not None:
            max_results = limit
        if calendar_id:
            calendars = [calendar_id]
        cal_ids = calendars or ["primary"]

        svc = self.service()
        tznow = datetime.now(timezone.utc).isoformat()

        events: list[dict[str, Any]] = []
        for cal_id in cal_ids:
            resp = (
                svc.events()
                .list(
                    calendarId=cal_id,
                    timeMin=tznow,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=max_results,
                )
                .execute()
            )
            for ev in resp.get("items", []):
                ev["_calendarId"] = cal_id
            events.extend(resp.get("items", []))

        # Sort by start
        def _start_key(e: dict) -> str:
            start = e.get("start", {})
            return start.get("dateTime") or start.get("date") or ""

        events.sort(key=_start_key)
        return events[:max_results]

    def create_event(self, calendar_id: str, body: dict) -> dict:
        svc = self.service()
        try:
            return svc.events().insert(calendarId=calendar_id, body=body).execute()
        except HttpError as e:
            self._handle_scope_error(e)
            raise

    def update_event(self, calendar_id: str, event_id: str, body: dict) -> dict:
        svc = self.service()
        try:
            return svc.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()
        except HttpError as e:
            self._handle_scope_error(e)
            raise

    def delete_event(self, calendar_id: str, event_id: str) -> dict:
        svc = self.service()
        try:
            svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return {"ok": True}
        except HttpError as e:
            self._handle_scope_error(e)
            raise


# Singleton holder
_gcal_singleton: GoogleCalendar | None = None


def get_calendar() -> GoogleCalendar:
    """FastAPI dependency to get the GoogleCalendar singleton."""

    global _gcal_singleton
    if _gcal_singleton is None:
        _gcal_singleton = GoogleCalendar(
            client_secret_path=settings.google_oauth_client_secrets,
            token_path=settings.google_token_file,
            scopes=GCAL_SCOPES,
        )
    return _gcal_singleton


# ---------------------- IPX dependency ----------------------

# app/deps.py


def _load_ipx_class():
    """
    Load the IPX client class.
    1) If settings specify module/class, try that first.
    2) Otherwise, try a list of likely modules/classes.
    """

    # --- 1) Respect explicit settings (safe getattr avoids AttributeError) ---
    mod_name = getattr(settings, "ipx_client_module", None)
    cls_name = getattr(settings, "ipx_client_class", None)
    if mod_name and cls_name:
        try:
            mod = import_module(mod_name)
        except Exception as e:
            raise ImportError(f"Failed to import module '{mod_name}': {e}") from e
        try:
            return getattr(mod, cls_name)
        except AttributeError:
            raise ImportError(f"Module '{mod_name}' loaded but class '{cls_name}' not found.")

    # --- 2) Autodiscover common locations ---
    candidates: list[tuple[str, tuple[str, ...]]] = [
        # add the real path to your client.py first
        ("app.ipx800.client", ("IPX800Client", "IPXClient", "Client")),
        # your previous fallbacks
        ("app.ipx.client", ("IPXClient", "Client")),  # shim
        ("app.services.ipx", ("IPXClient", "IPX")),  # legacy
        ("app.ipx800", ("IPXClient", "IPX", "IPX800", "IPX800Client")),  # package root
        ("app.ipx", ("IPXClient", "IPX", "IPX800", "IPX800Client", "Client")),
    ]

    last_err: Exception | None = None
    for module_name, class_names in candidates:
        try:
            mod = import_module(module_name)
            for name in class_names:
                if hasattr(mod, name):
                    return getattr(mod, name)
        except Exception as e:
            last_err = e
            continue

    raise ImportError(
        "Could not locate an IPX client class.\n"
        "Tried candidates:\n"
        "  - app.ipx800.client: IPX800Client/IPXClient/Client\n"
        "  - app.ipx.client:    IPXClient/Client\n"
        "  - app.services.ipx:  IPXClient/IPX\n"
        "  - app.ipx800:        IPXClient/IPX/IPX800/IPX800Client\n"
        "  - app.ipx:           IPXClient/IPX/IPX800/IPX800Client/Client\n\n"
        "Tip: set these in your .env to force a specific class:\n"
        "  IPX_CLIENT_MODULE=app.ipx800.client\n"
        "  IPX_CLIENT_CLASS=IPX800Client\n"
    ) from last_err
