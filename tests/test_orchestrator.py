import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan
from care_ladder.privacy import blur_faces

# Outside demo_home quiet_hours (22:00–07:00) so ladder tests exercise rungs.
DAYTIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def test_silence_escalates_to_dial_and_writes_trace():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" in tools
    assert incident.events[0].cue_kind == "no_movement"


def test_ok_reply_resolves_without_dial():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["I'm fine"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" not in tools
    assert incident.status == "resolved"


def test_call_caregiver_jumps_to_dial_primary():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_visibility", confidence=0.8, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["yes call"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert "dial_contact" in tools
    assert "jump" in tools  # skipped wait (and any non-dial) logged
    assert incident.status == "resolved"


def test_disabled_emergency_never_runs_and_jumps_logged_on_no_answer_skip():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="distress_heuristic", confidence=0.7, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(
                behavior={"caregiver": "no_answer", "secondary": "no_answer"}
            ),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "dial_contact" in tools
    assert "emergency" not in tools  # never executed as a tool event
    assert any(
        e.tool == "jump" and e.detail.get("skipped_tool") == "emergency"
        for e in incident.events
    )
    assert incident.status == "exhausted"
    # Never real 911
    assert all("911" not in str(e.detail) for e in incident.events)


def test_reperceive_appears_in_audit_trace():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["ok"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "reperceive" in tools


def test_pre_event_frames_privacy_blur_before_attach():
    """C1: non-empty pre_event_frames must be privacy-transformed before attach count."""
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    frame[20:40, 30:50] = (180, 150, 120)

    blur_calls: list[int] = []

    def tracking_blur(f):
        blur_calls.append(1)
        return blur_faces(f)

    with patch("care_ladder.ladder.orchestrator.blur_faces", side_effect=tracking_blur):
        incident = asyncio.run(
            run_incident(
                cue=cue,
                plan=plan,
                speaker=SpeakerSimulator(scripted=["I'm fine"]),
                dialer=StubDialer(behavior={"caregiver": "answered"}),
                pre_event_frames=[frame],
                now=DAYTIME,
            )
        )

    assert blur_calls, "blur_faces must run before attach"
    assert incident.pre_event_frame_count == 1
    assert incident.privacy == "blur"
    cue_ev = incident.events[0]
    assert cue_ev.tool == "cue"
    assert cue_ev.detail.get("privacy") == "blur"
    # Refuse non-zero attach without privacy flag
    assert incident.pre_event_frame_count == 0 or cue_ev.detail.get("privacy") in {
        "blur",
        "silhouette",
    }


def test_empty_pre_event_frames_no_privacy_claim():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["ok"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    assert incident.pre_event_frame_count == 0
    assert incident.privacy is None


def test_wait_rung_skipped_when_consumed_as_speaker_listen():
    """I5: wait used as speaker listen window must not double-count as a wait sleep."""
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=DAYTIME,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    # Wait after speaker should be jumped (already used as listen), not executed as wait
    assert "wait" not in tools
    assert any(
        e.tool == "jump"
        and e.detail.get("skipped_tool") == "wait"
        and e.detail.get("reason") == "listen_window_already_consumed"
        for e in incident.events
    )


def test_quiet_hours_soft_suppress_non_distress():
    """I4: during quiet hours, non-distress cues are soft-suppressed with audit event."""
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={})
    # demo_home quiet_hours 22:00–07:00; pick 23:30 as in-window clock
    now = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=now,
        )
    )
    tools = [e.tool for e in incident.events]
    assert any(
        e.tool in {"suppress", "jump"}
        and (
            e.detail.get("reason") == "quiet_hours"
            or e.detail.get("policy") == "soft_suppress_non_distress"
        )
        for e in incident.events
    )
    assert "dial_contact" not in tools
    assert incident.status in {"resolved", "suppressed", "exhausted"}


def test_quiet_hours_does_not_suppress_distress():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    cue = CueEvent(kind="distress_heuristic", confidence=0.7, detail={"non_clinical": True})
    now = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=["I'm fine"]),
            dialer=StubDialer(behavior={"caregiver": "answered"}),
            pre_event_frames=[],
            now=now,
        )
    )
    tools = [e.tool for e in incident.events]
    assert "speaker_prompt" in tools
    assert not any(
        e.tool == "suppress" or e.detail.get("reason") == "quiet_hours"
        for e in incident.events
    )
