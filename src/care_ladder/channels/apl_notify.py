"""Alexa Presentation Language notify card (in-process document, not a second skill)."""

from __future__ import annotations

from typing import Any

from care_ladder.channels.care_conversation import INFORM_ACTIONS

APL_VOICE_ACTIONS: tuple[str, ...] = (
    "false_alarm",
    "on_my_way",
    "need_second_look",
    "snooze_alert",
)

_VOICE_LABELS: dict[str, str] = {
    "false_alarm": "False alarm",
    "on_my_way": "On my way",
    "need_second_look": "Need a second look",
    "snooze_alert": "Snooze",
}

APL_DOCUMENT: dict[str, Any] = {
    "type": "APL",
    "version": "2024.3",
    "mainTemplate": {
        "parameters": ["payload"],
        "items": [
            {
                "type": "Container",
                "items": [
                    {"type": "Image", "source": "${payload.notify.thumbnail}"},
                    {"type": "Text", "text": "${payload.notify.householdLabel}"},
                    {"type": "Text", "text": "${payload.notify.timeSinceCue}"},
                    {"type": "Text", "text": "${payload.notify.cueText}"},
                ],
            }
        ],
    },
}


def format_time_since(sec: int) -> str:
    seconds = max(0, int(sec))
    if seconds < 60:
        return "just now"
    mins = seconds // 60
    return f"{mins} min ago"


def apl_notify_card(
    *,
    thumbnail: str,
    household_label: str,
    time_since_cue_sec: int,
    cue_text: str,
    countdown_sec: int,
    next_contact: str = "Secondary contact",
) -> dict[str, Any]:
    """Thumbnail, household, time since cue, actions mirroring voice intents."""
    actions: list[dict[str, str]] = [
        {"id": aid, "label": _VOICE_LABELS[aid]} for aid in APL_VOICE_ACTIONS
    ]
    for item in INFORM_ACTIONS:
        actions.append(
            {"id": item["id"], "label": item["label"].format(next=next_contact)}
        )
    time_label = format_time_since(time_since_cue_sec)
    datasource = {
        "thumbnail": thumbnail,
        "householdLabel": household_label,
        "timeSinceCue": time_label,
        "time_since_cue_sec": int(time_since_cue_sec),
        "cueText": cue_text,
        "countdownSec": int(countdown_sec),
        "actions": actions,
    }
    return {
        "thumbnail": thumbnail,
        "householdLabel": household_label,
        "timeSinceCue": time_label,
        "time_since_cue_sec": int(time_since_cue_sec),
        "cueText": cue_text,
        "countdownSec": int(countdown_sec),
        "actions": actions,
        "apl": APL_DOCUMENT,
        "datasources": {"notify": datasource},
    }
