"""Fail-closed check-in response intent for Alexa+ / speaker replies.

Three buckets (product lock):
- clear_ok — soft reassurance; may close the ladder like Path A OK
- needs_human — mixed or concerning; do not clear; raise notify
- unclear — groan / empty ASR / garbage; never invent OK

Deterministic keywords + simple patterns for the hackathon demo.
An optional LLM hook is accepted but stays off unless CARE_LADDER_INTENT_LLM=1.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Literal

ResponseIntent = Literal["clear_ok", "needs_human", "unclear"]

INTENT_LABELS: dict[ResponseIntent, str] = {
    "clear_ok": "Clear OK",
    "needs_human": "Needs human",
    "unclear": "Unclear",
}

_LLM_ENV = "CARE_LADDER_INTENT_LLM"

# Concern tokens win over reassurance. "I'm okay but I think I'm hurt" stays
# needs_human even though it contains okay.
_CONCERN = re.compile(
    r"\b("
    r"hurt|hurts|pain|painful|fell|fall|fallen|help|"
    r"injur(?:y|ed)|bleed(?:ing)?|dizz(?:y|iness)|sick|"
    r"can'?t\s+get\s+up|cannot\s+get\s+up|"
    r"emergency|unwell|broken|ache|aching"
    r")\b",
    re.IGNORECASE,
)

_SOFT_OK = re.compile(
    r"("
    r"\bdon'?t\s+worry\b|"
    r"\bleave\s+me\s+alone\b|"
    r"\bdon'?t\s+call\b|"
    r"\bdo\s+not\s+call\b|"
    r"\ball\s+good\b|"
    r"\bno\s+problem\b|"
    r"\bi(?:['’]m|\s+am)\s+(?:fine|good|well|alright|all\s+right|ok(?:ay)?)\b|"
    r"\bjust\s+(?:resting|napping|sitting|ok(?:ay)?)\b|"
    r"\byes\s+i(?:['’]m|\s+am)\b|"
    r"\bok(?:ay)?\b|"
    r"\bfine\b|"
    r"\balright\b|"
    r"\ball\s+right\b"
    r")",
    re.IGNORECASE,
)

_UNCLEAR_TOKEN = re.compile(
    r"^("
    r"u+h+|u+m+|m+h*|h+m+|ugh+|n+g+h+|aa+h*|oh+|nngh+|argh+|"
    r"\[(?:inaudible|unintelligible)\]|"
    r"\.+|…+|\?+"
    r")$",
    re.IGNORECASE,
)

_EXPLICIT_CALL = re.compile(r"\b(?:yes\s+)?call\b", re.IGNORECASE)
_NEGATE_CALL = re.compile(r"\b(?:don'?t|do\s+not)\s+call\b", re.IGNORECASE)

_WS = re.compile(r"\s+")


def _is_garbage(text: str) -> bool:
    letters = re.sub(r"[^a-z]", "", text)
    if len(text) <= 2:
        return True
    if letters and not re.search(r"[aeiou]", letters) and len(letters) <= 8:
        return True
    if letters and len(letters) / max(len(text), 1) < 0.4:
        return True
    return False


def _deterministic(raw: str) -> ResponseIntent:
    text = _WS.sub(" ", (raw or "").strip()).casefold()
    if not text:
        return "unclear"
    if _UNCLEAR_TOKEN.fullmatch(text):
        return "unclear"

    concern = bool(_CONCERN.search(text))
    wants_call = bool(_EXPLICIT_CALL.search(text)) and not _NEGATE_CALL.search(text)
    if concern or wants_call:
        return "needs_human"
    if _SOFT_OK.search(text):
        return "clear_ok"
    # Garbage / leftover ASR only after OK and concern tokens, so "ok" (len 2)
    # is never swallowed as unclear.
    if _is_garbage(text):
        return "unclear"
    return "unclear"


def classify_response_intent(
    raw: str,
    *,
    llm_classify: Callable[[str], str] | None = None,
) -> ResponseIntent:
    """Map a free-form resident reply to a fail-closed intent bucket."""
    intent = _deterministic(raw)
    if llm_classify is None:
        return intent
    flag = os.environ.get(_LLM_ENV, "").strip().lower()
    if flag not in {"1", "true", "on"}:
        return intent
    try:
        hooked = llm_classify(raw)
    except Exception:
        return intent
    if hooked in INTENT_LABELS:
        return hooked  # type: ignore[return-value]
    return intent


def intent_to_reply_kind(intent: ResponseIntent, raw: str = "") -> str:
    """Map intent onto the existing speaker reply_kind union.

    needs_human always escalates (call_caregiver kind) so OpenCV and Alexa+
    paths share one fail-closed gate. Jump *reason* is chosen by the orchestrator.
    """
    _ = raw
    if intent == "clear_ok":
        return "ok"
    if intent == "needs_human":
        return "call_caregiver"
    return "silence"


def intent_label(intent: ResponseIntent) -> str:
    return INTENT_LABELS[intent]


def jump_reason_for_intent(intent: ResponseIntent, raw: str) -> str:
    """Audit jump reason: explicit call request keeps call_caregiver."""
    if intent != "needs_human":
        return intent
    text = (raw or "").casefold()
    if _EXPLICIT_CALL.search(text) and not _NEGATE_CALL.search(text):
        return "call_caregiver"
    return "needs_human"
