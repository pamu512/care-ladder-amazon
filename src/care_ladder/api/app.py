"""FastAPI incident timeline + demo trigger (demo fixtures only; no live camera)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import asyncio

from fastapi import FastAPI, HTTPException, Response, UploadFile
from uuid import uuid4
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from care_ladder.audit.store import AuditStore
from care_ladder.channels.dial import StubDialer
from care_ladder.cloud.sinks import CloudSinks
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.learning.profile import (
    LearningConfig,
    RoutineProfile,
    freeze as _freeze_learning,
    mark_settled as _mark_settled,
    reset as _reset_learning,
)
from care_ladder.learning.store import RoutineProfileJSONStore
from care_ladder.models import AuditEvent, CueEvent
from care_ladder.plan_loader import load_care_plan
from care_ladder.vision.cues import CueDetector
from care_ladder.vision.ingest import ingest_video, save_upload

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEMO_PLAN_PATH = _REPO_ROOT / "configs" / "demo_home.yaml"
_AMAZON_PLAN_PATH = _REPO_ROOT / "configs" / "amazon_demo_home.yaml"
_LEARNING_STORE = RoutineProfileJSONStore(_REPO_ROOT / "data" / "routine_profiles")

SUPPORTED_FIXTURES = frozenset(
    {
        "alexa_path_a",
        "alexa_path_a_ok",
        "alexa_path_a_soft_ok",
        "alexa_path_a_needs_human",
        "alexa_path_a_unclear",
        "alexa_path_b",
        "quiet_hours_suppressed",
        "no_visibility",
        "no_movement_ok",
        "no_movement_silence",
        "opencv_stillness",
        "opencv_dnn_person",
        "opencv_pose_person",
    }
)
_POSE_MODEL_PATH = _REPO_ROOT / "models" / "pose_estimation_mediapipe_2023mar.onnx"
_MODEL_PATH = _REPO_ROOT / "models" / "person_detection_mediapipe_2023mar.onnx"
# Midday UTC so quiet_hours soft-suppress does not hide the judge demo ladder.
DEMO_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


class DemoRunRequest(BaseModel):
    fixture: str = Field(
        ...,
        description='Demo fixture id, e.g. "no_movement_silence" or "opencv_stillness"',
    )


class DemoRunResponse(BaseModel):
    incident_id: str


def _incident_summary(incident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "household_id": incident.household_id,
        "status": incident.status,
        "cue": incident.cue.model_dump(),
        "event_count": len(incident.events),
    }


async def _run_quiet_hours_suppressed(store: AuditStore):
    """Fixture: non-distress cue inside quiet hours -> suppressed (audited)."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "quiet_hours_suppressed"})
    speaker = SpeakerSimulator(scripted=["I'm fine"])
    dialer = StubDialer(behavior={})
    # DEMO_NOW is 12:00; quiet hours window 22:00-07:00 -> pass a 23:30 clock
    from datetime import datetime, timezone as tz

    night = datetime(2026, 9, 11, 23, 30, tzinfo=tz.utc)
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        pre_event_frames=[], store=store, now=night,
    )
    return incident


async def _run_no_visibility(store: AuditStore):
    """Fixture: person left the monitored zone -> no_visibility cue."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    cue = CueEvent(kind="no_visibility", confidence=0.85, detail={"fixture": "no_visibility"})
    speaker = SpeakerSimulator(scripted=["I'm fine"])
    dialer = StubDialer(behavior={})
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    return incident


def _demo_profile():
    """RoutineProfile for the OpenCV demo household (JSON store, gitignored)."""
    return _LEARNING_STORE.get_or_create("demo-home-1")


def _save_profile(profile):
    _LEARNING_STORE.save(profile)


async def _run_no_movement_ok(store: AuditStore):
    """Fixture: no_movement cue + verbal OK → resolve without dial (spec §10 Path A)."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "no_movement_ok"})
    speaker = SpeakerSimulator(scripted=["I'm fine"])
    dialer = StubDialer(behavior={})  # never reached on this path
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        routine_profile=_demo_profile(),
        store=store,
        now=DEMO_NOW,
    )
    return incident


def _amazon_profile():
    """RoutineProfile for the Amazon demo household (spec 2026-09-27)."""
    return _LEARNING_STORE.get_or_create("amazon-demo-1")


async def _run_alexa_path_a(store: AuditStore):
    """Amazon Path A: stillness cue -> Alexa+ check-in x2 silence -> wait 45s ->
    notify caretaker -> request_call (simulated) -> emergency fail-closed."""
    plan = load_care_plan(_AMAZON_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "alexa_path_a"})
    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={})
    profile = _amazon_profile()
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        routine_profile=profile,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    _LEARNING_STORE.save(profile)  # persist learning update (spec section 5)
    return incident


async def _run_alexa_path_a_ok(store: AuditStore):
    """Amazon Path A variant: resident answers OK on the second attempt."""
    plan = load_care_plan(_AMAZON_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "alexa_path_a_ok"})
    speaker = SpeakerSimulator(scripted=["", "I'm ok, just resting"])
    dialer = StubDialer(behavior={})
    profile = _amazon_profile()
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        routine_profile=profile,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    _LEARNING_STORE.save(profile)  # persist learning update (spec section 5)
    return incident


async def _run_alexa_path_a_soft_ok(store: AuditStore):
    """Path A: soft OK without the word okay — don't worry / leave me alone."""
    plan = load_care_plan(_AMAZON_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "alexa_path_a_soft_ok"})
    speaker = SpeakerSimulator(scripted=["don't worry"])
    dialer = StubDialer(behavior={})
    profile = _amazon_profile()
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        routine_profile=profile,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    _LEARNING_STORE.save(profile)
    return incident


async def _run_alexa_path_a_needs_human(store: AuditStore):
    """Path A: mixed/concerning reply — do not clear; raise notify."""
    plan = load_care_plan(_AMAZON_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "alexa_path_a_needs_human"})
    speaker = SpeakerSimulator(scripted=["I'm okay but I think I'm hurt"])
    dialer = StubDialer(behavior={})
    profile = _amazon_profile()
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        routine_profile=profile,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    _LEARNING_STORE.save(profile)
    return incident


async def _run_alexa_path_a_unclear(store: AuditStore):
    """Path A: groan / empty ASR — same as no clear answer; never invent OK."""
    plan = load_care_plan(_AMAZON_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "alexa_path_a_unclear"})
    speaker = SpeakerSimulator(scripted=["nngh", "ugh"])
    dialer = StubDialer(behavior={})
    profile = _amazon_profile()
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        routine_profile=profile,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    _LEARNING_STORE.save(profile)
    return incident


async def _run_alexa_path_b(store: AuditStore):
    """Amazon Path B: occlusion (no_visibility) -> Rung 1 holding (camera
    health, never distress) -> ask to move blanket -> no answer -> notify
    caretaker on the inform basis -> request_call (simulated) -> fail-closed."""
    plan = load_care_plan(_AMAZON_PLAN_PATH)
    cue = CueEvent(kind="no_visibility", confidence=0.85, detail={"fixture": "alexa_path_b"})
    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={})
    profile = _amazon_profile()
    incident = await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        routine_profile=profile,
        pre_event_frames=[], store=store, now=DEMO_NOW,
    )
    _LEARNING_STORE.save(profile)  # persist learning update (spec section 5)
    return incident


async def _run_no_movement_silence(store: AuditStore):
    """Fixture: no_movement cue + speaker silence → escalate via stub dialer."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"fixture": "no_movement_silence"})
    # Silence path: empty script → escalate; secondary answers so incident resolves.
    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[],
        routine_profile=_demo_profile(),
        store=store,
        now=DEMO_NOW,
    )
    return incident


def _synthetic_stillness_frames(
    *,
    width: int = 160,
    height: int = 120,
) -> list[np.ndarray]:
    """Build a short synthetic still-person sequence for CueDetector (no live camera)."""
    frames: list[np.ndarray] = []
    for _ in range(4):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[40:80, 60:100] = 200
        frames.append(frame)
    return frames


async def _run_opencv_stillness(store: AuditStore):
    """Fixture: synthetic frames → CueDetector.observe → run_incident (OpenCV path)."""
    plan = load_care_plan(_DEMO_PLAN_PATH)
    # Short timeout so demo/tests emit no_movement without waiting plan's 900s.
    plan.triggers.no_movement.timeout_sec = 2
    # Fixture pins the demo clock (2s): spec section 6 - an explicit fixture
    # timeout overrides learning, so no profile here.
    detector = CueDetector.from_plan(plan, zone_id="living_room")
    # Zone in demo YAML is 640x480; use matching canvas so blob sits in-zone.
    frames = _synthetic_stillness_frames(width=640, height=480)
    # Place blob well inside living_room polygon
    for f in frames:
        f[:, :] = 0
        f[200:280, 300:380] = 200

    cue: CueEvent | None = None
    times = [0.0, 1.0, 2.5, 3.0]
    for frame, t in zip(frames, times, strict=True):
        cue = detector.observe(frame, t=t)
        if cue is not None:
            break
    if cue is None:
        raise RuntimeError("opencv_stillness fixture: CueDetector did not emit a cue")

    cue.detail = {
        **cue.detail,
        "source": "opencv_cue_detector",
        "fixture": "opencv_stillness",
    }

    speaker = SpeakerSimulator(scripted=[])
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    # Attach last frames (privacy-blurred inside run_incident).
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=frames[-2:],
        store=store,
        privacy_mode="blur",
        now=DEMO_NOW,
    )
    return incident


async def _run_opencv_dnn_person(store: AuditStore):
    """Fixture: real photo → DNN person detector → zone check → ladder.

    Uses tests/fixtures/basketball1.png (OpenCV sample image with a person).
    Requires models/person_detection_mediapipe_2023mar.onnx (scripts/download_models.sh).
    The DNN localizes the person (in-zone) every frame; identical frames → motion stays
    ~0 → `no_movement` cue → ladder.
    """
    import cv2

    photo = cv2.imread(str(_REPO_ROOT / "tests" / "fixtures" / "basketball1.png"))
    if photo is None:
        raise RuntimeError("opencv_dnn_person fixture: sample photo missing")
    if not _MODEL_PATH.exists():
        raise RuntimeError(
            "opencv_dnn_person fixture: run scripts/download_models.sh first"
        )

    from care_ladder.vision.mppersondet import MPPersonDet

    plan = load_care_plan(_DEMO_PLAN_PATH)
    plan.triggers.no_movement.timeout_sec = 2  # demo clock, not plan's 900s
    detector = CueDetector.from_plan(plan, zone_id="living_room")
    detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)

    cue: CueEvent | None = None
    times = [0.0, 1.0, 2.5, 3.0]
    for t in times:
        cue = detector.observe(photo, t=t)
        if cue is not None:
            break
    if cue is None:
        raise RuntimeError("opencv_dnn_person fixture: detector emitted no cue")

    cue.detail = {
        **cue.detail,
        "source": "opencv_dnn_person_detector",
        "detector": "mediapipe_persondet_2023mar (OpenCV 5 DNN)",
        "fixture": "opencv_dnn_person",
    }

    speaker = SpeakerSimulator(scripted=["I'm fine, thanks"])
    dialer = StubDialer(behavior={})
    incident = await run_incident(
        cue=cue,
        plan=plan,
        speaker=speaker,
        dialer=dialer,
        pre_event_frames=[photo],
        store=store,
        privacy_mode="silhouette",
        now=DEMO_NOW,
    )
    return incident


def _default_store() -> AuditStore:
    """dynamodb when CARE_LADDER_STORE=dynamodb (and boto3 present), else memory."""
    if os.environ.get("CARE_LADDER_STORE", "").lower() == "dynamodb":
        try:
            from care_ladder.audit.dynamo_store import DynamoAuditStore

            return DynamoAuditStore()
        except Exception as exc:  # pragma: no cover - env-dependent
            print(f"WARNING: CARE_LADDER_STORE=dynamodb failed ({exc}); using memory")
    return AuditStore()


async def _publish_cloud(incident) -> None:
    """Best-effort S3 clip upload + EventBridge cue emission (no-ops locally).

    Never fails the incident: cloud sink errors are logged and swallowed.
    """
    try:
        sinks = CloudSinks()
        if not sinks.enabled:
            return
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        uris = sinks.upload_clip_frames(incident.id, frames, incident.privacy)
        sinks.emit_cue(incident, uris)
    except Exception as exc:  # pragma: no cover - env-dependent
        print(f"WARNING: cloud publish failed for {incident.id}: {exc}")


async def _run_opencv_pose_person(store: AuditStore):
    """Fixture: real photo → person ONNX → pose ONNX → torso metrics, no distress.

    Standing person: pose runs, torso angle computed, no distress cue; the
    incident demonstrates the pose path end-to-end with `source: pose_heuristics`
    context in the cue detail (pattern telemetry, not a fall).
    """
    import cv2

    photo = cv2.imread(str(_REPO_ROOT / "tests" / "fixtures" / "basketball1.png"))
    if photo is None:
        raise RuntimeError("opencv_pose_person fixture: sample photo missing")
    if not _MODEL_PATH.exists() or not _POSE_MODEL_PATH.exists():
        raise RuntimeError("opencv_pose_person fixture: run scripts/download_models.sh first")

    from care_ladder.vision.mppersondet import MPPersonDet
    from care_ladder.vision.mppose import MPPose

    plan = load_care_plan(_DEMO_PLAN_PATH)
    plan.triggers.no_movement.timeout_sec = 2
    # Fixture pins the demo clock (2s): spec section 6 - an explicit fixture
    # timeout overrides learning, so no profile here.
    detector = CueDetector.from_plan(plan, zone_id="living_room")
    detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)
    detector.pose_model = MPPose(str(_POSE_MODEL_PATH), confThreshold=0.5)

    cue = None
    for t in [0.0, 0.5, 1.0, 2.5, 3.0]:
        cue = detector.observe(photo, t=t)
        if cue is not None:
            break
    if cue is None:
        raise RuntimeError("opencv_pose_person fixture: detector emitted no cue")

    cue.detail = {
        **cue.detail,
        "source": "opencv_pose_path",
        "pose": getattr(detector, "last_pose_metrics", None),
        "models": ["person_detection_mediapipe_2023mar", "pose_estimation_mediapipe_2023mar"],
        "fixture": "opencv_pose_person",
    }
    speaker = SpeakerSimulator(scripted=["I'm fine"])
    dialer = StubDialer(behavior={})
    return await run_incident(
        cue=cue, plan=plan, speaker=speaker, dialer=dialer,
        pre_event_frames=[photo], store=store, privacy_mode="silhouette", now=DEMO_NOW,
    )


# In-flight upload analysis jobs: job_id -> {status, filename, incident_id, error}
_UPLOAD_JOBS: dict[str, dict[str, Any]] = {}


def create_app(store: AuditStore | None = None) -> FastAPI:
    """Build FastAPI app with injectable store (tests inject a fresh memory store)."""
    audit = store if store is not None else _default_store()
    application = FastAPI(
        title="Care Ladder",
        description="Incident timeline + demo trigger (reserved phones; emergency fail-closed).",
        version="0.1.0",
    )
    application.state.store = audit

    static_dir = Path(__file__).resolve().parent / "static"
    application.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")
    firetv_dir = static_dir / "firetv"
    application.mount("/firetv", StaticFiles(directory=firetv_dir, html=True), name="firetv")

    # Self-hosted MCP server (Streamable HTTP, MCP 2025-11-25+) for the
    # Alexa+ agent path: same container, same port. The internal route is "/"
    # so the mount serves exactly /mcp; the session manager's lifespan runs
    # from this app's own lifespan (ASGI mounts do not propagate lifespan).
    import contextlib

    from care_ladder.mcp_server.server import bind_audit_store, mcp as care_ladder_mcp

    from mcp.server.transport_security import TransportSecuritySettings

    bind_audit_store(audit)

    _mcp_asgi = care_ladder_mcp.streamable_http_app(
        stateless_http=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    application.mount("/mcp", _mcp_asgi)

    _existing_lifespan = application.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _lifespan(app: FastAPI):
        # Enter the MCP session manager for the lifetime of the API app
        # (ASGI mounts do not propagate lifespan to the mounted app).
        mgr = getattr(care_ladder_mcp, "session_manager", None)
        if mgr is None:
            async with _existing_lifespan(app):
                yield
            return
        async with _existing_lifespan(app), mgr.run():
            yield

    application.router.lifespan_context = _lifespan

    @application.get("/learning/{household_id}")
    def get_learning(household_id: str) -> dict[str, Any]:
        """RoutineProfile for the UI badge: phase, days, explain, controls state."""
        profile = _LEARNING_STORE.get_or_create(household_id)
        plan = load_care_plan(_DEMO_PLAN_PATH)
        from care_ladder.learning.profile import effective_no_movement_timeout_sec

        eff = effective_no_movement_timeout_sec(plan, profile)
        return {
            "household_id": household_id,
            "learning_phase": profile.learning_phase,
            "frozen": profile.frozen,
            "confirmed_ok_days": profile.confirmed_ok_days,
            "settled_after_days": profile.settled_after_days,
            "effective_no_movement_timeout_sec": eff,
            "plan_timeout_sec": plan.triggers.no_movement.timeout_sec,
            "usual_still_end_hour": profile.usual_still_end_hour,
        }

    @application.post("/learning/{household_id}/freeze")
    def learning_freeze(household_id: str) -> dict[str, Any]:
        profile = _LEARNING_STORE.get_or_create(household_id)
        _freeze_learning(profile)
        _LEARNING_STORE.save(profile)
        return {"household_id": household_id, "frozen": True}

    @application.post("/learning/{household_id}/reset")
    def learning_reset(household_id: str) -> dict[str, Any]:
        profile = _reset_learning(_LEARNING_STORE.get_or_create(household_id))
        _LEARNING_STORE.save(profile)
        return {"household_id": household_id, "learning_phase": "rapid"}

    @application.post("/learning/{household_id}/settle")
    def learning_settle(household_id: str) -> dict[str, Any]:
        profile = _mark_settled(_LEARNING_STORE.get_or_create(household_id))
        _LEARNING_STORE.save(profile)
        return {"household_id": household_id, "learning_phase": "settled"}

    @application.get("/plan")
    def get_plan() -> dict[str, Any]:
        """Current demo care plan (phone numbers redacted) for the console's
        full-ladder rail: shows never-reached rungs (e.g. emergency fail-closed)."""
        plan = load_care_plan(_DEMO_PLAN_PATH)

        def _redact(phone: str | None) -> str | None:
            if not phone:
                return phone
            return f"****{phone[-2:]}" if len(phone) >= 2 else "****"

        data = plan.model_dump()
        for key in ("caregiver", "secondary", "monitored"):
            contact = data.get(key)
            if contact and contact.get("phone_e164"):
                contact["phone_e164"] = _redact(contact["phone_e164"])
        return data

    @application.get("/mcp-agent")
    def mcp_agent() -> dict[str, Any]:
        """Calm Fire TV pill: true only while an MCP session is driving."""
        status = getattr(application.state.store, "mcp_agent_status", None)
        if status is None:
            return {"active": False, "household_id": None, "incident_id": None}
        return status()

    @application.get("/incidents")
    def list_incidents() -> list[dict[str, Any]]:
        return [_incident_summary(i) for i in application.state.store.list_incidents()]

    @application.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict[str, Any]:
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        # Full timeline JSON: ordered audit events (cue → tools → resolve/jump).
        return incident.model_dump()

    @application.post("/incidents/{incident_id}/ack")
    def ack_incident(incident_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Caregiver acknowledgement: a human confirmed they saw this incident.

        Appends a ``caregiver_ack`` audit event and stamps ``acked_by``/
        ``acked_at``. Status is unchanged (resolved stays resolved) - the ack
        is the human-side close of the loop; the orchestrator consults it for
        re-dial cooldown on subsequent cues.
        """
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if incident.acked_by is not None:
            raise HTTPException(status_code=409, detail="incident already acknowledged")
        body = body or {}
        contact = str(body.get("contact", "caregiver"))
        note = str(body.get("note") or "")[:200]
        now = datetime.now(timezone.utc)
        incident.acked_by = contact
        incident.acked_at = now
        incident.events.append(
            AuditEvent(
                tool="notify",
                cue_kind=incident.cue.kind,
                detail={"action": "caregiver_ack", "contact": contact, "note": note},
            )
        )
        application.state.store.save(incident)
        return {"incident_id": incident.id, "acked_by": contact, "acked_at": now.isoformat()}

    @application.get("/incidents/{incident_id}/frames/{index}", response_class=Response)
    def get_incident_frame(incident_id: str, index: int):
        """Serve a privacy-transformed pre-event frame as PNG.

        Frames reaching this endpoint already went through blur/silhouette in
        run_incident; raw identifiable pixels never enter the store.
        """
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        if not (0 <= index < len(frames)):
            raise HTTPException(
                status_code=404,
                detail=f"frame index {index} out of range (0..{max(len(frames)-1, 0)})",
            )
        ok, buf = cv2.imencode(".png", frames[index])
        if not ok:
            raise HTTPException(status_code=500, detail="png encode failed")
        return Response(content=buf.tobytes(), media_type="image/png")

    @application.get("/incidents/{incident_id}/detection_frame", response_class=Response)
    def get_detection_frame(incident_id: str):
        """The frame the detector saw at cue time, annotated (bbox + telemetry)
        and privacy-transformed. Answers 'why did this cue fire' visually."""
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        frame = incident.__dict__.get("_private_detection_frame")
        if frame is None:
            raise HTTPException(status_code=404, detail="no detection frame for this incident")
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise HTTPException(status_code=500, detail="png encode failed")
        return Response(content=buf.tobytes(), media_type="image/png")

    @application.get("/incidents/{incident_id}/frames")
    def list_incident_frames(incident_id: str) -> dict[str, Any]:
        incident = application.state.store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        return {
            "privacy": incident.privacy,
            "count": len(frames),
            "frame_urls": [f"/incidents/{incident_id}/frames/{i}" for i in range(len(frames))],
        }

    @application.post("/demo/upload", response_model=DemoRunResponse)
    async def demo_upload(file: UploadFile) -> DemoRunResponse:
        """Real video ingest: upload a clip → OpenCV decode → CueDetector → ladder.

        Returns 202 immediately with a job id; the CPU-heavy decode+DNN scan
        runs in a worker thread (a 28 MB / 100+ s clip takes minutes on a
        0.5-vCPU Fargate task — far past gateway timeouts — and would block
        the event loop if awaited inline). Poll GET /demo/upload/{job_id} for
        the resulting incident.
        """
        data = await file.read()
        if len(data) > 64 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="clip too large (max 64 MB)")
        suffix = Path(file.filename or "clip.mp4").suffix.lower() or ".mp4"
        if suffix not in {".mp4", ".mov", ".avi", ".m4v", ".webm"}:
            raise HTTPException(status_code=400, detail=f"unsupported type {suffix!r}")

        spilled = save_upload(data, suffix=suffix)
        job_id = uuid4().hex
        _UPLOAD_JOBS[job_id] = {
            "status": "processing",
            "filename": file.filename,
            "incident_id": None,
            "error": None,
        }

        def _process() -> None:
            entry = _UPLOAD_JOBS[job_id]
            try:
                entry["incident_id"] = _run_upload_sync(spilled, application.state.store)
                entry["status"] = "done"
            except HTTPException as exc:
                entry["status"] = "error"
                entry["error"] = exc.detail
            except Exception as exc:  # pragma: no cover - env-dependent
                entry["status"] = "error"
                entry["error"] = f"analysis failed: {exc}"
            finally:
                Path(spilled).unlink(missing_ok=True)

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _process)
        return DemoRunResponse(incident_id=job_id)

    @application.get("/demo/upload/{job_id}")
    def upload_job_status(job_id: str) -> dict[str, Any]:
        job = _UPLOAD_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job id")
        return job

    def _run_upload_sync(spilled: Path, store: AuditStore) -> str:
        """CPU-heavy upload analysis (runs in executor thread): decode →
        detectors → ladder. Returns incident id; raises HTTPException on
        undecodable/no-cue input."""
        plan = load_care_plan(_DEMO_PLAN_PATH)
        plan.triggers.no_movement.timeout_sec = 2  # demo clock
        detector = CueDetector.from_plan(plan, zone_id="living_room", profile=_demo_profile())
        if _MODEL_PATH.exists():
            from care_ladder.vision.mppersondet import MPPersonDet
            from care_ladder.vision.mppose import MPPose

            detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)
            if _POSE_MODEL_PATH.exists():
                detector.pose_model = MPPose(str(_POSE_MODEL_PATH), confThreshold=0.5)

        # Clip resolution may differ from plan zone canvas; use full-frame zone.
        probe = cv2.VideoCapture(str(spilled))
        ok, first = probe.read()
        probe.release()
        if not ok:
            raise HTTPException(
                status_code=422,
                detail="clip could not be decoded — is it a valid video file?",
            )
        h, w = first.shape[:2]
        detector.zone = np.asarray(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )

        result = ingest_video(spilled, detector, sample_hz=5.0, prefer_distress=True, max_seconds=180.0)
        if result.cue is None and detector.person_detector is not None:
            # DNN found nobody in the whole clip (stylized/low-res footage):
            # fall back to the contour-blob path and re-run once.
            detector.person_detector = None
            detector.pose_model = None
            result = ingest_video(spilled, detector)

        if result.cue is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no cue emitted from clip ({result.frame_count} frames, "
                    f"{result.duration_sec}s) — try a clip with a still person, "
                    "someone leaving frame, or lying on the floor"
                ),
            )

        result.cue.detail = {
            **result.cue.detail,
            # keep the more specific pose label when the pose path fired
            "source": result.cue.detail.get("source", f"uploaded_clip:{result.detector_source}"),
            "clip_frames": result.frame_count,
            "clip_fps": result.fps,
            "clip_duration_sec": result.duration_sec,
        }
        speaker = SpeakerSimulator(scripted=[])
        dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
        incident = asyncio.run(
            run_incident(
                cue=result.cue,
                plan=plan,
                speaker=speaker,
                dialer=dialer,
                pre_event_frames=result.pre_event_frames[-4:],
                store=store,
                privacy_mode="blur",
                now=DEMO_NOW,
            )
        )
        asyncio.run(_publish_cloud(incident))
        return incident.id

    @application.post("/demo/camera/start")
    async def camera_start(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Live camera demo: open a device index or RTSP/HTTP URL, run the same
        CueDetector at ~5 Hz, auto-create an incident on the first cue.

        Guardrails: demo plan only, hard 10-minute cap, one session per process,
        privacy transform before persist. A visible "LIVE" banner is shown in
        the console while a session runs.
        """
        from care_ladder.vision import camera as cam

        body = body or {}
        source = body.get("source", 0)
        if isinstance(source, str) and not source.startswith(("rtsp://", "http://", "https://")):
            raise HTTPException(status_code=400, detail="source must be a device index or rtsp/http URL")

        plan = load_care_plan(_DEMO_PLAN_PATH)
        plan.triggers.no_movement.timeout_sec = min(plan.triggers.no_movement.timeout_sec, 30)
        detector = CueDetector.from_plan(plan, zone_id="living_room", profile=_demo_profile())
        if _MODEL_PATH.exists():
            from care_ladder.vision.mppersondet import MPPersonDet

            detector.person_detector = MPPersonDet(str(_MODEL_PATH), scoreThreshold=0.3)

        async def _on_cue(cue, t: float):
            speaker = SpeakerSimulator(scripted=[])
            dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
            incident = await run_incident(
                cue=cue,
                plan=plan,
                speaker=speaker,
                dialer=dialer,
                pre_event_frames=[],
                store=application.state.store,
                privacy_mode="silhouette",
                now=datetime.now(timezone.utc),
            )
            await _publish_cloud(incident)

        try:
            session = cam.start_session(
                source=source, detector=detector, on_incident=_on_cue, max_seconds=600.0
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"status": "started", "source": source, "label": session.label}

    @application.post("/demo/camera/stop")
    def camera_stop() -> dict[str, Any]:
        from care_ladder.vision import camera as cam

        stopped = cam.stop_session()
        return {"status": "stopped" if stopped else "not_running"}

    @application.get("/demo/camera/status")
    def camera_status() -> dict[str, Any]:
        from care_ladder.vision import camera as cam

        session = cam.active_session()
        if session is None:
            return {"running": False}
        return session.status()

    @application.post("/demo/run", response_model=DemoRunResponse)
    async def demo_run(body: DemoRunRequest) -> DemoRunResponse:
        if body.fixture not in SUPPORTED_FIXTURES:
            raise HTTPException(
                status_code=400,
                detail=f"unknown fixture {body.fixture!r}; supported: {sorted(SUPPORTED_FIXTURES)}",
            )
        if body.fixture == "alexa_path_a":
            incident = await _run_alexa_path_a(application.state.store)
        elif body.fixture == "alexa_path_a_ok":
            incident = await _run_alexa_path_a_ok(application.state.store)
        elif body.fixture == "alexa_path_a_soft_ok":
            incident = await _run_alexa_path_a_soft_ok(application.state.store)
        elif body.fixture == "alexa_path_a_needs_human":
            incident = await _run_alexa_path_a_needs_human(application.state.store)
        elif body.fixture == "alexa_path_a_unclear":
            incident = await _run_alexa_path_a_unclear(application.state.store)
        elif body.fixture == "alexa_path_b":
            incident = await _run_alexa_path_b(application.state.store)
        elif body.fixture == "quiet_hours_suppressed":
            incident = await _run_quiet_hours_suppressed(application.state.store)
        elif body.fixture == "no_visibility":
            incident = await _run_no_visibility(application.state.store)
        elif body.fixture == "no_movement_ok":
            incident = await _run_no_movement_ok(application.state.store)
        elif body.fixture == "no_movement_silence":
            incident = await _run_no_movement_silence(application.state.store)
        elif body.fixture == "opencv_stillness":
            incident = await _run_opencv_stillness(application.state.store)
        elif body.fixture == "opencv_dnn_person":
            incident = await _run_opencv_dnn_person(application.state.store)
        elif body.fixture == "opencv_pose_person":
            incident = await _run_opencv_pose_person(application.state.store)
        else:  # pragma: no cover - guarded by SUPPORTED_FIXTURES
            raise HTTPException(status_code=400, detail="unsupported fixture")
        await _publish_cloud(incident)
        return DemoRunResponse(incident_id=incident.id)

    return application


# Default ASGI app for `uvicorn care_ladder.api.app:app`
app = create_app()
