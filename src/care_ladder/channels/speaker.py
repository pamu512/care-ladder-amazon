"""Nest/Alexa-style spoken check-in channel (simulator only for v1)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from care_ladder.channels.response_intent import (
    ResponseIntent,
    classify_response_intent,
    intent_to_reply_kind,
)

SpeakerReplyKind = Literal["ok", "call_caregiver", "silence"]


@dataclass(frozen=True)
class SpeakerReply:
    kind: SpeakerReplyKind
    raw: str
    intent: ResponseIntent = "unclear"


@runtime_checkable
class SpeakerChannel(Protocol):
    async def prompt(self, text: str, wait_sec: float) -> SpeakerReply:
        """Speak ``text`` and wait up to ``wait_sec`` for a spoken reply."""
        ...


def classify_utterance(raw: str) -> SpeakerReplyKind:
    """Map a free-form reply to ok / call_caregiver / silence.

    Fail-closed: concern or mixed OK+hurt wins over the word "okay".
    Soft reassurance without "okay" (don't worry / leave me alone) is still OK.
    Groans and empty ASR are silence — never invented OK.
    """
    intent = classify_response_intent(raw)
    kind = intent_to_reply_kind(intent, raw)
    return kind  # type: ignore[return-value]


class SpeakerSimulator:
    """Injectable scripted replies for Nest/Alexa-style check-in demos/tests.

    Empty queue or unmatched utterance after ``wait_sec`` → ``silence``.
    Real Nest/Alexa device integration is out of scope.
    """

    def __init__(self, scripted: Sequence[str] | None = None) -> None:
        self._queue: list[str] = list(scripted or [])

    async def prompt(self, text: str, wait_sec: float) -> SpeakerReply:
        _ = text  # spoken prompt; real devices would TTS this
        if self._queue:
            raw = self._queue.pop(0)
            intent = classify_response_intent(raw)
            kind = intent_to_reply_kind(intent, raw)  # type: ignore[assignment]
            return SpeakerReply(kind=kind, raw=raw, intent=intent)
        await asyncio.sleep(max(0.0, wait_sec))
        return SpeakerReply(kind="silence", raw="")
