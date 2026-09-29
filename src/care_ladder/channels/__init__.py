"""Communication channels: speaker check-in and dial stubs."""

from care_ladder.channels.dial import DialResult, StubDialer, next_rung_after_no_answer
from care_ladder.channels.speaker import SpeakerChannel, SpeakerReply, SpeakerSimulator

__all__ = [
    "DialResult",
    "SpeakerChannel",
    "SpeakerReply",
    "SpeakerSimulator",
    "StubDialer",
    "next_rung_after_no_answer",
]
