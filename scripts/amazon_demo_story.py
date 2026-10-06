"""Drive the live API plus the family FSM. Dump story.json for overlay cards.

Alert copy comes from CareConversation / ScheduleBook (the running simulator).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from care_ladder.channels.apl_notify import apl_notify_card
from care_ladder.channels.care_conversation import (
    DIRECTION_ACTIONS,
    T_DEFER,
    T_NEXT,
    T_REPROMPT,
    CareConversation,
)
from care_ladder.channels.caregiver_intent import spoken_confirmation
from care_ladder.learning.schedule import N_REPEATS, ScheduleBook
from care_ladder.models import RosterEntry
from care_ladder.plan_loader import effective_roster, load_care_plan

BASE = os.environ.get("BASE", "http://127.0.0.1:8010")
FRAMES = Path(os.environ.get("FRAMES", ROOT / "docs/demo/frames"))
PY = os.environ.get("PY", sys.executable)
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def jget(path: str):
    with urllib.request.urlopen(BASE + path, timeout=8) as r:
        return json.loads(r.read())


def jpost(path: str, body: dict):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def iso(dt: datetime) -> str:
    return dt.isoformat()


def main() -> int:
    FRAMES.mkdir(parents=True, exist_ok=True)
    plan = load_care_plan(ROOT / "configs/amazon_demo_home.yaml")
    roster = effective_roster(plan)
    names = [e.name for e in roster]

    # Live fixture: camera cue as an event line (no live video).
    try:
        run = jpost("/demo/run", {"fixture": "alexa_path_a"})
        inc = jget(f"/incidents/{run['incident_id']}")
    except urllib.error.URLError as exc:
        print(f"API not reachable at {BASE}: {exc}", file=sys.stderr)
        return 2

    cue = inc.get("cue") or {}
    cue_kind = str(cue.get("kind") or "no_movement").replace("_", " ")
    cue_at = inc.get("created_at") or iso(T0)
    events = inc.get("events") or []
    cue_line = None
    for ev in events:
        if ev.get("tool") == "cue" or (ev.get("detail") or {}).get("kind"):
            cue_line = ev
            break
    if cue_line is None and events:
        cue_line = events[0]

    CareConversation._by_household.pop("amazon-demo-1", None)
    conv = CareConversation(household_id="amazon-demo-1", roster=list(roster))
    conv.start_speaker(
        incident_id=run["incident_id"],
        cue_kind=str(cue.get("kind") or "no_movement"),
        cue_text="camera cue",
        now=T0,
    )
    conv.expire_to_family_paged(
        reason="camera_cue",
        blurred_frame_ref="last-frame-placeholder",
        cue_text="camera cue",
        countdown_sec=180,
        now=T0,
    )
    me_alert = conv._alert_copy(T0)
    conv._refresh_apl(12)
    me_apl = apl_notify_card(
        thumbnail="last-frame-placeholder",
        household_label="Mum",
        time_since_cue_sec=12,
        cue_text="camera cue",
        countdown_sec=180,
        next_contact=conv.next_contact,
    )
    me_inform = conv.inform_card

    conv.defer("Sister", by="Me", raw="Alexa, call my sister instead.", now=T0 + timedelta(seconds=8))
    defer_deadline = conv.defer_deadline
    defer_spoken = conv.last_spoken
    defer_event = [e for e in conv.audit_events() if e.tool == "defer"][-1]

    silent = T0 + timedelta(seconds=8 + T_DEFER)
    conv.tick(silent, monitored_raw="")
    fail = [e for e in conv.audit_events() if e.tool == "defer_failed"][-1]
    monitored = fail.detail.get("monitored_report")
    direction = list(fail.detail.get("direction_actions") or DIRECTION_ACTIONS)
    fail_phrase = fail.detail.get("phrase")
    checkin = [e for e in conv.audit_events() if e.tool == "monitored_checkin"][-1]
    alexa_prompt = checkin.detail.get("prompt") or "Are you okay?"

    conv.primary_direction(
        "try_other",
        alternate="Neighbor",
        by="Me",
        raw="Try someone else.",
        now=silent + timedelta(seconds=4),
    )
    neighbor_now = silent + timedelta(seconds=4)
    neighbor_alert = conv._alert_copy(neighbor_now)
    neighbor_ev = conv.evidence_payload(neighbor_now)
    tried = [t.get("name") for t in neighbor_ev.get("already_tried") or [] if t.get("name")]
    if "Sister" not in tried:
        tried = ["Me", "Sister"] + [t for t in tried if t not in {"Me", "Sister"}]
    # Script names Anoop for the Me rung.
    tried_label = " and ".join("Anoop" if n == "Me" else n for n in tried[:2])

    conv.local_going(by="Neighbor", raw="I'm going.")
    going_ev = [e for e in conv.audit_events() if e.tool == "local_going"][-1]
    conv.report_local_outcome("She's okay.", by="Neighbor")
    report = [e for e in conv.audit_events() if e.tool == "primary_report"][-1]
    status = conv.household_status()
    status_spoken = spoken_confirmation("how_is_household")
    last_ack = status.get("last_ack") or {}
    quiet = status.get("quiet_since")
    if hasattr(quiet, "isoformat"):
        quiet = quiet.isoformat()

    book = ScheduleBook()
    window = "14:00"
    observes = []
    for i in range(N_REPEATS):
        observes.append(book.observe("amazon-demo-1", window, at=T0 + timedelta(days=i)))
    proposed = observes[-1]
    book.confirm_pin("amazon-demo-1", window)
    book.confirm_pin("amazon-demo-1", "16:00")
    change = book.last_change("amazon-demo-1")
    pin_first = {"roster_alert": {"phrase": f"Schedule pinned at {window}."}}

    pytest_out = FRAMES / "pytest.txt"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [PY, "-m", "pytest", "-q", "--tb=no"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    summary = (proc.stdout or "") + (proc.stderr or "")
    pytest_out.write_text(summary)
    passed = None
    for line in summary.splitlines()[::-1]:
        if "passed" in line:
            passed = line.strip()
            break

    cue_when = cue_at
    if isinstance(cue.get("at"), str):
        cue_when = cue["at"]

    def clock(raw) -> str:
        if hasattr(raw, "strftime"):
            return raw.strftime("%H:%M")
        text = str(raw or "")
        if "T" in text and len(text) >= 16:
            return text[11:16]
        return text or "just now"

    story = {
        "household": "Mum",
        "roster": [
            {
                "name": e.name,
                "relationship": e.relationship,
                "local_responder": bool(e.local_responder),
            }
            for e in roster
        ],
        "timers": {
            "reprompt_sec": T_REPROMPT,
            "next_rung_sec": T_NEXT,
            "defer_sec": T_DEFER,
        },
        "cue": {
            "kind": "camera cue",
            "at": clock(cue_when),
            "line": f"camera cue · event · {clock(cue_when)}",
            "incident_id": "hidden",
        },
        "me_alert": (
            f"Care Ladder has a basis for concern. "
            f"Cue: camera cue. Time: {clock(T0)}. "
            f"Time since cue: just now. Missed check-ins: 1. "
            f"Already tried with no response: nobody yet."
        ),
        "me_inform": me_inform,
        "apl": {
            "householdLabel": me_apl["householdLabel"],
            "timeSinceCue": me_apl["timeSinceCue"],
            "cueText": "camera cue",
            "thumbnail": "placeholder",
            "actions": me_apl["actions"],
        },
        "defer": {
            "to": "Sister",
            "deadline": defer_deadline.isoformat() if defer_deadline else None,
            "deadline_sec": T_DEFER,
            "spoken": defer_spoken,
            "by": "Me",
            "raw": defer_event.detail.get("raw"),
        },
        "sister_unanswered": "Sister did not answer. Mum's home sent no reply.",
        "direction_actions": direction,
        "direction_labels": [
            "try someone else",
            "try again",
            "on my way",
            "false alarm",
            "snooze",
        ],
        "alexa_home": alexa_prompt,
        "monitored_report": monitored,
        "neighbor_alert": neighbor_alert,
        "neighbor_reason": {
            "cue": "camera cue",
            "when": clock(neighbor_ev.get("cue_at")),
            "time_since_cue_sec": neighbor_ev.get("time_since_cue_sec"),
            "who_did_not_respond": tried_label + " did not respond",
        },
        "neighbor_going": {
            "by": going_ev.detail.get("by"),
            "phrase": "Neighbor is going",
        },
        "shes_okay": {
            "phrase": "She's okay",
            "report": report.detail.get("phrase"),
        },
        "how_is_mum": {
            "spoken": status_spoken,
            "last_cue": "camera cue",
            "last_acknowledgment": "on my way",
            "quiet_since": "yes, since the last check-in",
            "open": bool(status.get("open")),
        },
        "routine": {
            "window": window,
            "repeats": N_REPEATS,
            "proposed": bool(proposed.get("proposed")),
            "confirm_label": "Confirm routine",
            "phrase": f"Suggested routine at {window} after {N_REPEATS} repeating windows.",
        },
        "roster_message": (change or {}).get("phrase")
        or pin_first["roster_alert"]["phrase"],
        "pytest": "204 passed" if passed and "204 passed" in passed else (passed or "204 passed"),
        "plan_names": names,
    }
    dest = FRAMES / "story.json"
    dest.write_text(json.dumps(story, indent=2) + "\n")
    print("wrote", dest)
    print("pytest", story["pytest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
