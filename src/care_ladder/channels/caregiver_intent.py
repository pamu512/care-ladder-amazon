"""Fail-closed caregiver classifier for Alexa mobile ack / outcome.

Buckets:
- im_on_it / call_mom_now / pass_to_next — inform-card actions (stop ladder)
- outcome — free-text close ("Called Mom, she's fine")
- unclear — groan / empty / garbage; never invent an ack
"""

from __future__ import annotations

import re
from typing import Literal

from care_ladder.channels.care_conversation import ACK_ACTIONS

CaregiverIntent = Literal[
    "im_on_it",
    "call_mom_now",
    "pass_to_next",
    "outcome",
    "unclear",
]

CAREGIVER_INTENT_LABELS: dict[CaregiverIntent, str] = {
    "im_on_it": "I'm on it",
    "call_mom_now": "Call Mom now",
    "pass_to_next": "Pass to next",
    "outcome": "Outcome",
    "unclear": "Unclear",
}

_WS = re.compile(r"\s+")

_PASS = re.compile(
    r"("
    r"can['’]?t\s+take\s+it|"
    r"cannot\s+take\s+it|"
    r"go\s+to\s+(?:the\s+)?(?:next|secondary)|"
    r"pass\s+(?:it|this)\s+(?:on|to)|"
    r"hand\s+(?:it|this)\s+off"
    r")",
    re.IGNORECASE,
)

_CALL_MOM = re.compile(
    r"("
    r"call\s+mom\s+now|"
    r"please\s+call\s+mom|"
    r"dial\s+(?:mom|her)\s+now"
    r")",
    re.IGNORECASE,
)

_IM_ON_IT = re.compile(
    r"("
    r"i['’]?m\s+on\s+it|"
    r"call\s+her\s+myself|"
    r"i['’]?ll\s+(?:call|check|go)|"
    r"i\s+will\s+(?:call|check|go)|"
    r"got\s+it|"
    r"on\s+my\s+way"
    r")",
    re.IGNORECASE,
)

_OUTCOME = re.compile(
    r"("
    r"\bcalled\b|"
    r"(?:she|he|they)['’]?s\s+(?:fine|ok(?:ay)?|good)|"
    r"checked\s+on|"
    r"went\s+over|"
    r"all\s+(?:clear|fine|good)"
    r")",
    re.IGNORECASE,
)


def _is_garbage(text: str) -> bool:
    letters = re.sub(r"[^a-z]", "", text)
    if len(text) <= 2:
        return True
    if letters and not re.search(r"[aeiou]", letters) and len(letters) <= 8:
        return True
    return False


def classify_caregiver_intent(raw: str) -> CaregiverIntent:
    """Map a caregiver utterance to an ack action, outcome, or unclear."""
    text = _WS.sub(" ", (raw or "").strip()).casefold()
    if not text:
        return "unclear"
    if _PASS.search(text):
        return "pass_to_next"
    if _CALL_MOM.search(text):
        return "call_mom_now"
    if _IM_ON_IT.search(text):
        return "im_on_it"
    if _OUTCOME.search(text):
        return "outcome"
    if _is_garbage(text):
        return "unclear"
    return "unclear"


def is_ack_action(intent: str) -> bool:
    return intent in ACK_ACTIONS
