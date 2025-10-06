# app/utils/datetime.py
from __future__ import annotations

from datetime import datetime, timezone



def parse_iso_naive(s: str | None):
    """
    Accepts 'YYYY-MM-DD' or full ISO datetime (possibly with TZ).
    Returns a *naive* datetime for easy sorting, or None on failure.
    """
    if not s:
        return None
    try:
        # All-day event date
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime.fromisoformat(s)  # naive at midnight
        # Full ISO date-time (maybe with timezone)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        # strip tzinfo to make it naive for local sorting
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None
