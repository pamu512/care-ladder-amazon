"""Thin Proactive Events chime stub: default off, simulated only."""

from pathlib import Path

from care_ladder.channels.care_conversation import CareConversation
from care_ladder.channels.proactive_events import (
    PE_ENV,
    proactive_enabled,
    send_awareness_chime,
)


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(PE_ENV, raising=False)
    assert proactive_enabled() is False
    out = send_awareness_chime("amazon-demo-1", "inc-1")
    assert out["simulated"] is True
    assert out["skipped"] is True
    assert out["reason"] == "flag_off"
    assert out["kind"] == "awareness_chime"


def test_flag_on_returns_simulated_chime(monkeypatch):
    monkeypatch.setenv(PE_ENV, "1")
    assert proactive_enabled() is True
    out = send_awareness_chime("amazon-demo-1", "inc-1")
    assert out["simulated"] is True
    assert out["skipped"] is False
    assert out["kind"] == "awareness_chime"
    assert "schema-locked" in out["note"]


def test_family_paged_does_not_chime_when_flag_off(monkeypatch):
    monkeypatch.delenv(PE_ENV, raising=False)
    conv = CareConversation(household_id="h")
    conv.start_speaker(incident_id="i", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence", blurred_frame_ref="b", cue_text="c", countdown_sec=180
    )
    assert not any(e.tool == "proactive_chime" for e in conv.audit_events())


def test_family_paged_chimes_when_flag_on(monkeypatch):
    monkeypatch.setenv(PE_ENV, "1")
    conv = CareConversation(household_id="h")
    conv.start_speaker(incident_id="i", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence", blurred_frame_ref="b", cue_text="c", countdown_sec=180
    )
    chime = next(e for e in conv.audit_events() if e.tool == "proactive_chime")
    assert chime.detail["simulated"] is True
    assert chime.detail["skipped"] is False
    assert chime.at is not None


def test_honesty_doc_states_schema_lock_and_default_off():
    text = Path("docs/proactive-events-honesty.md").read_text()
    assert "schema-locked" in text.lower()
    assert "default **off**" in text or "default off" in text.lower()
    assert "rich buttons" in text.lower()
    assert "local sim only" in text.lower()
    assert "CARE_LADDER_PROACTIVE" in text
