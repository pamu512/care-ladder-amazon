"""Fail-closed caregiver classifier for Alexa mobile ack / outcome / deepen.

Buckets:
- im_on_it / call_mom_now / pass_to_next: inform-card actions (stop ladder)
- false_alarm / on_my_way / need_second_look / snooze_alert / defer_escalation
- try_other / try_again: defer-fail direction
- how_is_household: status read
- outcome: free-text close ("Called Mom, she's fine")
- unclear: groan / empty / garbage; never invent an ack
"""

from __future__ import annotations

import re
from typing import Literal

from care_ladder.channels.care_conversation import ACK_ACTIONS

CaregiverIntent = Literal[
    "im_on_it",
    "call_mom_now",
    "pass_to_next",
    "false_alarm",
    "on_my_way",
    "need_second_look",
    "snooze_alert",
    "defer_escalation",
    "how_is_household",
    "try_other",
    "try_again",
    "outcome",
    "unclear",
]

CAREGIVER_INTENT_LABELS: dict[CaregiverIntent, str] = {
    "im_on_it": "I'm on it",
    "call_mom_now": "Call Mom now",
    "pass_to_next": "Pass to next",
    "false_alarm": "False alarm",
    "on_my_way": "On my way",
    "need_second_look": "Need a second look",
    "snooze_alert": "Snooze",
    "defer_escalation": "Call someone else",
    "how_is_household": "How is the household",
    "try_other": "Try someone else",
    "try_again": "Try them again",
    "outcome": "Outcome",
    "unclear": "Unclear",
}

VOICE_ACTIONS = (
    "false_alarm",
    "on_my_way",
    "need_second_look",
    "snooze_alert",
    "defer_escalation",
)

DIRECTION_ACTIONS = (
    "try_other",
    "try_again",
    "on_my_way",
    "false_alarm",
    "snooze_alert",
)

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
    r"got\s+it"
    r")",
    re.IGNORECASE,
)

_FALSE_ALARM = re.compile(
    r"("
    r"false\s+alarm|"
    r"it['’]?s\s+nothing|"
    r"stand\s+down|"
    r"all\s+a\s+mistake"
    r")",
    re.IGNORECASE,
)

_ON_MY_WAY = re.compile(
    r"("
    r"on\s+my\s+way|"
    r"i['’]?m\s+coming\s+over|"
    r"heading\s+(?:there|over|in)|"
    r"i['’]?m\s+going"
    r")",
    re.IGNORECASE,
)

_LOCAL_NEEDS_HELP = re.compile(
    r"needs\s+help|not\s+okay|not\s+ok\b",
    re.IGNORECASE,
)

_SECOND_LOOK = re.compile(
    r"("
    r"need\s+a\s+second\s+look|"
    r"second\s+look|"
    r"check\s+again|"
    r"look\s+again"
    r")",
    re.IGNORECASE,
)

_SNOOZE = re.compile(
    r"("
    r"\bsnooze\b|"
    r"remind\s+me\s+later|"
    r"\bnot\s+now\b"
    r")",
    re.IGNORECASE,
)

_TRY_AGAIN = re.compile(
    r"try\s+(?:them|him|her|it|x)\s+again|try\s+again",
    re.IGNORECASE,
)

_TRY_OTHER = re.compile(
    r"\btry\s+(?!them\b|him\b|her\b|it\b|again\b).+",
    re.IGNORECASE,
)

_DEFER_INSTEAD = re.compile(
    r"(?:call|try|page)\s+(.+?)\s+instead\b",
    re.IGNORECASE,
)

_PAGE_NAME = re.compile(r"^page\s+(.+)$", re.IGNORECASE)

_HOW_HH = re.compile(
    r"("
    r"how\s+is\s+(?:the\s+)?household|"
    r"any\s+open\s+alerts|"
    r"is\s+it\s+quiet|"
    r"how['’]?s\s+(?:the\s+)?(?:house|household|mom|resident)"
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

_SPOKEN: dict[str, str] = {
    "false_alarm": "Got it. Marking this as a false alarm.",
    "on_my_way": "Okay. I will hold further alerts while you are on the way.",
    "need_second_look": "Understood. I will take another look and check in again.",
    "snooze_alert": "Snoozed. I will check back shortly.",
    "defer_escalation": (
        "I will try {alternate} instead, and come back to you if they do not answer."
    ),
    "im_on_it": "Okay. I will hold further alerts. How did it go?",
    "try_again": "I will try them again.",
    "try_other": "I will try {alternate} instead.",
    "how_is_household": "Here is the household status.",
}


def _is_garbage(text: str) -> bool:
    letters = re.sub(r"[^a-z]", "", text)
    if len(text) <= 2:
        return True
    if letters and not re.search(r"[aeiou]", letters) and len(letters) <= 8:
        return True
    return False


def extract_alternate_contact(raw: str) -> str | None:
    """Pull the alternate contact slot from a defer / try-other utterance."""
    text = _WS.sub(" ", (raw or "").strip())
    if not text:
        return None
    m = _DEFER_INSTEAD.search(text)
    if m:
        name = m.group(1).strip()
        return name or None
    m = _PAGE_NAME.search(text)
    if m:
        name = m.group(1).strip()
        return name or None
    m = _TRY_OTHER.search(text)
    if m:
        name = re.sub(r"^try\s+", "", m.group(0), flags=re.IGNORECASE).strip()
        return name or None
    return None


def classify_local_outcome(raw: str) -> str:
    """Map a local-responder outcome line to okay / needs_help / unclear."""
    from care_ladder.channels.response_intent import classify_response_intent

    text = _WS.sub(" ", (raw or "").strip())
    if not text:
        return "unclear"
    if _LOCAL_NEEDS_HELP.search(text):
        return "needs_help"
    intent = classify_response_intent(text)
    if intent == "needs_human":
        return "needs_help"
    if intent == "clear_ok" or re.search(r"\b(ok(?:ay)?|fine|all\s+clear)\b", text, re.I):
        return "okay"
    return "unclear"


def spoken_confirmation(intent: str, *, alternate: str | None = None) -> str:
    """Spoken Alexa confirm. No em dashes."""
    template = _SPOKEN.get(intent, "Okay.")
    return template.format(alternate=alternate or "them")


def classify_caregiver_intent(raw: str) -> CaregiverIntent:
    """Map a caregiver utterance to a named intent or unclear."""
    text = _WS.sub(" ", (raw or "").strip()).casefold()
    if not text:
        return "unclear"
    if _DEFER_INSTEAD.search(text) or _PAGE_NAME.search(text):
        if extract_alternate_contact(raw):
            return "defer_escalation"
        return "unclear"
    if _FALSE_ALARM.search(text):
        return "false_alarm"
    if _SECOND_LOOK.search(text):
        return "need_second_look"
    if _SNOOZE.search(text):
        return "snooze_alert"
    if _ON_MY_WAY.search(text):
        return "on_my_way"
    if _TRY_AGAIN.search(text):
        return "try_again"
    if _PASS.search(text):
        return "pass_to_next"
    if _CALL_MOM.search(text):
        return "call_mom_now"
    if _IM_ON_IT.search(text):
        return "im_on_it"
    if _TRY_OTHER.search(text):
        return "try_other"
    if _OUTCOME.search(text):
        return "outcome"
    if _HOW_HH.search(text):
        return "how_is_household"
    if _is_garbage(text):
        return "unclear"
    return "unclear"


def is_ack_action(intent: str) -> bool:
    return intent in ACK_ACTIONS


def is_voice_action(intent: str) -> bool:
    return intent in VOICE_ACTIONS or intent in ACK_ACTIONS or intent in DIRECTION_ACTIONS
