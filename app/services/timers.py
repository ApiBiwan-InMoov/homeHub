# app/services/timers.py
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

_DATA = "data/timers.json"
os.makedirs("data", exist_ok=True)


@dataclass
class TimerJob:
    id: str
    started_at: float
    duration_s: int
    due_at: float
    target: dict[str, Any]  # e.g. {"kind":"ipx_relay","relay":2}
    do: dict[str, Any]  # e.g. {"type":"set_on"}
    undo: dict[str, Any]  # e.g. {"type":"set_off"}
    origin: dict[str, Any]  # e.g. {"kind":"icon","id":"garage_light"} or {"kind":"rule","id":123}


class TimerManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: dict[str, TimerJob] = {}
        self._load()

    # -------- persistence --------
    def _load(self):
        if not os.path.exists(_DATA):
            return
        try:
            with open(_DATA) as f:
                raw = json.load(f)
            for j in raw.get("jobs", []):
                job = TimerJob(**j)
                self._jobs[job.id] = job
        except Exception:
            self._jobs = {}

    def _save(self):
        tmp = {"jobs": [asdict(j) for j in self._jobs.values()]}
        with open(_DATA, "w") as f:
            json.dump(tmp, f)

    # -------- API --------
    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            now = time.time()
            out = []
            for j in self._jobs.values():
                rem = max(0, int(j.due_at - now))
                out.append(
                    {
                        "id": j.id,
                        "target": j.target,
                        "origin": j.origin,
                        "remaining_s": rem,
                        "total_s": j.duration_s,
                    }
                )
            return out

    def active_for_target(self, kind: str, ident: Any) -> Optional[dict[str, Any]]:
        """Return countdown for a given target (e.g. relay) if any."""
        with self._lock:
            now = time.time()
            for j in self._jobs.values():
                if j.target.get("kind") == kind and j.target.get("relay") == ident:
                    return {"id": j.id, "remaining_s": max(0, int(j.due_at - now)), "total_s": j.duration_s}
        return None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                self._jobs.pop(job_id)
                self._save()
                return True
        return False

    def schedule(
        self,
        *,
        duration_s: int,
        target: dict[str, Any],
        do: dict[str, Any],
        undo: dict[str, Any],
        origin: dict[str, Any],
    ) -> TimerJob:
        with self._lock:
            # replace existing timer for same target (one timer per relay)
            for k, j in list(self._jobs.items()):
                if j.target == target:
                    self._jobs.pop(k)
            job = TimerJob(
                id=str(uuid.uuid4()),
                started_at=time.time(),
                duration_s=int(duration_s),
                due_at=time.time() + int(duration_s),
                target=target,
                do=do,
                undo=undo,
                origin=origin,
            )
            self._jobs[job.id] = job
            self._save()
            return job

    # -------- ticking (call every 1s) --------
    def tick_and_execute_due(self, do_undo_callback):
        """Remove due jobs and call do_undo_callback(job.undo, job.target)."""
        with self._lock:
            now = time.time()
            due_ids = [j.id for j in self._jobs.values() if j.due_at <= now]
            for jid in due_ids:
                job = self._jobs.pop(jid, None)
                if job:
                    try:
                        do_undo_callback(job.undo, job.target)
                    except Exception:
                        pass
            if due_ids:
                self._save()


timer_mgr = TimerManager()
