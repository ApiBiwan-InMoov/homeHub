# [RUNTIME_OVERRIDE v1] central place for small runtime flags shared across routers
from __future__ import annotations

from threading import Lock
from typing import Optional

__all__ = ["set_revert_override", "consume_revert_override"]

_lock = Lock()
_revert_override: Optional[int] = None  # seconds to override "revert_after_s" once

def set_revert_override(seconds: Optional[int]) -> None:
    """Set a one-shot override for revert_after_s (in seconds)."""
    global _revert_override
    with _lock:
        _revert_override = int(seconds) if seconds is not None else None

def consume_revert_override() -> Optional[int]:
    """Return and clear the one-shot override."""
    global _revert_override
    with _lock:
        v = _revert_override
        _revert_override = None
        return v
