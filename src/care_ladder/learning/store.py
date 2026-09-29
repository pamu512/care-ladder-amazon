"""JSON-file persistence for RoutineProfile (process-local, demo-honest).

Spec 2026-09-27 section 4: ``data/routine_profiles/{subject_key}.json``.
Galuxium will move to Postgres keyed by tenant; same API here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from care_ladder.learning.profile import RoutineProfile

_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe(subject_key: str) -> str:
    return _SAFE_KEY.sub("_", subject_key)[:120] or "unknown"


class RoutineProfileJSONStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, subject_key: str) -> Path:
        return self.root / f"{_safe(subject_key)}.json"

    def get(self, subject_key: str) -> RoutineProfile | None:
        p = self._path(subject_key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return RoutineProfile.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            return None

    def save(self, profile: RoutineProfile) -> RoutineProfile:
        p = self._path(profile.subject_key)
        data = profile.model_dump(mode="json")
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return profile

    def get_or_create(self, subject_key: str, *, settled_after_days: int = 10) -> RoutineProfile:
        return self.get(subject_key) or RoutineProfile(
            subject_key=subject_key, settled_after_days=settled_after_days
        )
