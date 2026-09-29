"""Thin Alexa Proactive Events stub: awareness chime only.

Default off (CARE_LADDER_PROACTIVE=0). Schema-locked; no rich buttons.
Local sim only — see docs/proactive-events-honesty.md.
"""

from __future__ import annotations

import os
from typing import Any

PE_ENV = "CARE_LADDER_PROACTIVE"


def proactive_enabled() -> bool:
    return os.environ.get(PE_ENV, "0").strip().lower() in {"1", "true", "on"}


def send_awareness_chime(household_id: str, incident_id: str) -> dict[str, Any]:
    """Awareness chime that fans into the Alexa mobile skill session.

    Never claims rich buttons or three actions arrived via Proactive Events.
    """
    base = {
        "household_id": household_id,
        "incident_id": incident_id,
        "kind": "awareness_chime",
        "simulated": True,
        "note": "local sim only; schema-locked; not a rich notify",
    }
    if not proactive_enabled():
        return {**base, "skipped": True, "reason": "flag_off", "enabled": False}
    return {**base, "skipped": False, "reason": "opt_in", "enabled": True}
