# Implementation Plan: Care Ladder for Amazon Build, Ship, Shape (Alexa+ primary)

**Repo:** `opencv-care-ladder` - branch `amazon/alexa-plus-fire-tv` (off `main` @ `aebb167`)
**PRD:** `docs/superpowers/specs/2026-09-26-amazon-care-ladder-alexa-plus-prd.md` (section refs below)
**UX lock:** `docs/superpowers/specs/fire-tv-dashboard/` (prototype + canvas + screenshots)
**Deadline:** 2026-10-23 12:00 PDT / 2026-10-24 03:00 HKT - submit buffer mandatory
**Status:** Draft for Anoop approval. **No app code until this plan is approved.**

---

## 0. Pre-flight: repo facts this plan is built on (verified 2026-09-26)

1. **CI auto-deploy blast radius.** `.github/workflows/ci.yml` triggers ONLY on push to `branches: [main]`. The `amazon/*` branch never touches main until we choose to merge, so the live OpenCV stack at `d2u7pls4da2poz.cloudfront.net` is safe for the whole build. The OpenCV deadline (Oct 26) is 2 days AFTER the Amazon deadline, so this branch stays isolated until OpenCV judging completes. Merge timing: after Oct 26 (recommended) or branch-only. Anoop decides (Q2).
2. **The orchestrator already implements most of PRD 8.2.** `src/care_ladder/ladder/orchestrator.py` `run_incident()` loads a versioned care plan (`configs/demo_home.yaml` + `src/care_ladder/plan.py`), walks rungs (reperceive, speaker_prompt, wait_reply, dial_contact x2, emergency fail-closed), jumps on no-answer, and logs every step as AuditEvents, ending resolved / exhausted / suppressed. The Amazon work is wiring Alexa+ as the Rung-2 check-in engine and Fire TV as the Rung-4 notification surface, not building a new ladder.
3. **Existing surfaces to reuse.** FastAPI app (`src/care_ladder/api/app.py`) serves fixture-driven `/demo/run`, async clip upload + polling, live camera endpoints, `/incidents*` + detection frames, `/plan` (redacted), and ack. Console v2 is live at `/ui/`. The Fire TV app is a NEW static app under `src/care_ladder/api/static/firetv/` served at `/firetv/` from the same FastAPI app.
4. **Fire TV prototype committed on this branch** (`1c23510`): 36.7KB interactive twin with the full Calm Care-Tech system, D-pad spatial focus, demo console, emergency gate, deep links, plus design canvas and screenshots.
5. **MCP SDK resolves.** `uv pip install --dry-run mcp` against the repo venv resolves cleanly (adds sse-starlette, pyjwt, etc.). The official `mcp` Python SDK (FastMCP) serves Streamable HTTP, satisfying the hard gate (MCP spec 2025-11-25 or later, Streamable HTTP). Pin in pyproject, regenerate the lockfile with the venv-resolution method.
6. **Demo household.** PRD locks Meera (monitored), Anoop then Priya (contacts), living-room stillness 4m. Current `configs/demo_home.yaml` says Alex/Sam/Pat and 900s. A NEW `configs/amazon_demo_home.yaml` carries the Amazon household; the OpenCV demo config stays untouched (main remains the frozen submission source).
7. **Em dashes.** Every doc this plan writes is em-dash-free (standing directive). UI copy question: Q5.
8. **Scope fences.** No Galuxium SaaS on this branch. No Bee. No Ring. No classic-ASK work. AWS Builder mini only if a real Bedrock/AgentCore piece is already in-tree (Q3 recommends skip).

---

## 1. Slice 1: care plan + orchestrator rungs (PRD 8.2)

- [ ] 1.1 `configs/amazon_demo_home.yaml`: household `amazon-demo-1`; monitored Meera; caregiver Anoop; secondary Priya; living_room zone 640x480; triggers no_movement (timeout 240s), no_visibility, distress_heuristic; rungs `reperceive` -> `alexa_checkin` (2 attempts) -> `wait_window` (45s) -> `notify_caretaker` -> `request_call` (optional) -> `emergency` (enabled: false). Phones reserved NPA-555-01XX; prototype number `(555) 010-2276` for Anoop.
- [ ] 1.2 `src/care_ladder/plan.py`: extend the rung model for the new tool names + params (attempts, wait_sec, channels), defaulting safely for the old config so main-path behavior is unchanged.
- [ ] 1.3 Orchestrator: rung handlers `alexa_checkin`, `wait_window`, `notify_caretaker`, `request_call` in `src/care_ladder/ladder/orchestrator.py`, same AuditEvent contract:
  - `alexa_checkin`: two attempts with the PRD prompt copy; per-attempt outcome recorded (transcript lines quoted on TV).
  - `wait_window`: 45s silence clock; advance on expiry; answer resolves.
  - `notify_caretaker`: push mock + Fire TV event; Acknowledge stands down (reuse ack endpoint semantics).
  - `request_call`: optional action; logs audit event with reserved number and `simulated: true`; never dials.
  - `emergency`: unchanged fail-closed refusal when enabled is false.
- [ ] 1.4 Demo fixtures under the Amazon plan: `alexa_path_a` (stillness, silence, full ladder) and `alexa_path_b` (occlusion Path B) added to `/demo/run` (plan-aware fixture selection; existing OpenCV fixtures unchanged).
- [ ] 1.5 Tests `tests/test_amazon_rungs.py`: OK at attempt 1 resolves with no notify; OK at attempt 2 resolves; silence through 2 attempts + 45s advances to notify; ack stands down; emergency off never invokes a call tool and logs the refusal.

**AC:** Path A ladder under `amazon_demo_home.yaml` runs cue -> reperceive -> alexa_checkin x2 -> wait_window 45s -> notify_caretaker -> ack -> resolved with mono-timestamped audit events; tests green.

---

## 2. Slice 2: OpenCV cue -> orchestrator wiring + occlusion Path B (PRD 8.1, 8.4)

- [ ] 2.1 Cue sources (camera session, fixtures, clip upload) flow into the plan-driven path for the Amazon household: same CueDetector, plan selected by household config. No new detector code expected; wiring only.
- [ ] 2.2 Occlusion Path B: `no_visibility` cue -> Rung 1 holding (camera health, never distress) -> `alexa_checkin` asks to move the blanket -> no answer -> `notify_caretaker` informs (no distress claim anywhere) -> ack resolves. Audit copy uses "camera health" vocabulary; a guard test asserts no `distress_heuristic` event or distress-claim copy on this path.
- [ ] 2.3 Tests `tests/test_amazon_paths.py`: fixture-driven Path B end-to-end; distress-copy negative assertion; Path A from a vision cue (stillness fixture) end-to-end.

**AC:** `POST /demo/run {"fixture":"alexa_path_a" | "alexa_path_b"}` returns full ladders; Path B never claims distress; tests green.

---

## 3. Slice 3: self-hosted MCP server, Streamable HTTP (hard Amazon gate)

- [ ] 3.1 Dependency: add `mcp` (pinned) to pyproject; regenerate `requirements-lock.txt`; Dockerfile keeps the lock-then-editable pattern.
- [ ] 3.2 `src/care_ladder/mcp_server/server.py`: `FastMCP("Care Ladder")` with Streamable HTTP at `/mcp`, mounted as an ASGI sub-app inside the existing FastAPI app (one container, one port, no new infra, works on the existing Fargate task). Tools exactly matching PRD 8.3:
  - `start_or_resume_incident`, `check_in_prompt` (records response), `advance_rung`, `resolve_incident`, `get_incident_status`, `notify_caretaker`, `request_call`
  - State keyed by household + incident id (AuditStore / DynamoDB when configured); concurrent incidents supported.
- [ ] 3.3 `src/care_ladder/mcp_server/alexa_sim.py`: simulated Alexa+ agent as an in-repo MCP CLIENT that drives the ladder over Streamable HTTP (initialize -> tools/call sequence) with a visible terminal transcript; used in the demo to prove the tools are agent-callable at runtime, not curl-only. (Sim path allowed by PRD 7 with sim source in repo.)
- [ ] 3.4 Tests `tests/test_mcp_server.py`: initialize handshake over HTTP; tools/list returns exactly the 7 tool names (exact-set assertion kills typos); full Path A driven via tool calls only; advance from an invalid rung rejected; double-resolve rejected; notify writes an audit event; request_call never dials (dialer absent from audit tools).
- [ ] 3.5 Friction log entries for the mcp SDK: install, Streamable HTTP setup, ASGI mount, docs gaps.

**AC:** MCP handshake answers at `/mcp`; tools/list exact set; Path A runs via MCP tool calls only; sim client transcript shows an agent driving the ladder; tests green.

---

## 4. Slice 4: Fire TV caregiver app (PRD 8.4)

Declared adaptation: the prototype is the visual/UX lock; slice 4 ports it to be data-driven from the orchestrator API (polling) instead of its internal timers, which is what PRD 8.4 requires ("wire to the orchestrator, not a disconnected mock slideshow").

- [ ] 4.1 `src/care_ladder/api/static/firetv/index.html`: port of the twin (tokens, layout, D-pad spatial focus, emergency gate, demo console) polling `/incidents` + `/plan` + detection frame.
- [ ] 4.2 State mapping: all clear (no open incident), recheck (rung 1), checkin (rung 2 with live wait bar), wait closed (rung 3 bridge), notify (rung 4 with actions), occluded (Path B, cue kind `no_visibility`), resolved. Hero copy from the PRD 8.4 table.
- [ ] 4.3 Demo console drives the REAL API: Path A / Path B fixtures, ack, reset. "Run full demo" auto-sequences Path A. Emergency gate identical hold-to-review behavior, hard-locked copy.
- [ ] 4.4 Silhouette panel shows the incident detection frame (privacy-transformed) when present; "No reading, lens covered" on occlusion. No video element anywhere.
- [ ] 4.5 Launch: runs in the Silk browser on a Fire TV stick pointed at the backend URL (README documents device + recording-at-1280x720 setup); no Appstore packaging in v1.
- [ ] 4.6 Tests `tests/test_firetv_app.py`: served at `/firetv/`; Calm Care-Tech token anchors (`#24221E`, `#A8B5A0`, `#D9A05B`, JetBrains Mono, Instrument Sans fallback); D-pad keydown handlers; state/copy anchors; `(555) 010-2276` present; emergency-gate copy; audit trail section; demo-console buttons.

**AC:** `/firetv/` all-clear on open; demo console drives live ladders end-to-end with transcript, audit trail, silhouette; D-pad moves focus; gate never enables; tests green.

---

## 5. Slice 5: demo-safe notify/call stubs (PRD 8.5)

- [ ] 5.1 `notify_caretaker` audit event carries `channels: ["push_mock", "fire_tv"]`; push is a stub (SMS/email out per Q6).
- [ ] 5.2 `request_call` writes `simulated: true` + reserved number; no dialer adapter touched; emergency off refusal audited.
- [ ] 5.3 Tests: covered by slices 1 and 3 assertions plus a stub-contract test in `tests/test_amazon_paths.py`.

**AC:** every notify/call in the Amazon paths is visibly simulated in the audit trail; no dialer invocation.

---

## 6. Slice 6: ship pack (PRD 8.6)

- [ ] 6.1 README before/after section (pre-window Care Ladder vs Alexa+ + Fire TV update) + one-line architecture: Camera -> OpenCV cues -> ladder -> Alexa+ MCP -> Fire TV.
- [ ] 6.2 `docs/demo-video-script-amazon.md`: 3-min-or-less shot list, Path A + Path B, English, VO pacing-checked (~135 wpm), before segment reusing existing OpenCV demo footage where possible.
- [ ] 6.3 `docs/friction-log.md`: created in slice 3, one entry per Amazon surface touched, honest.
- [ ] 6.4 Devpost field draft (separate doc, NOT a Devpost submission): primary Alexa+, Fire TV supporting, AWS mini only if real, tool-feedback bullets.
- [ ] 6.5 No Final Submit anywhere; drafts only for Anoop review.

**AC:** before/after README; pacing-verified shot list; friction log current; Devpost draft doc ready for Anoop.

---

## 7. Slice 7: optional AWS Builder mini

Only if a real Bedrock/AgentCore piece is already in-tree and working by W3. Otherwise skip. No stub work.

---

## Open questions for Anoop

- **Q1 (design-blocking, slice 2):** occlusion DURING the wait window: keep waiting (current behavior) or hold-and-restart on recovery? Recommendation: hold-and-restart, privacy-first (never run a distress wait on a room the camera cannot read).
- **Q2:** merge to main after OpenCV judging (Oct 26, recommended) vs branch-only forever.
- **Q3:** AWS Builder mini: skip to protect schedule (recommended)?
- **Q4:** Fire TV hardware: any stick available, or browser/Silk-at-desk recording only?
- **Q5:** UI copy em dashes in the locked prototype strings ("Acknowledged" line uses one): keep prototype copy verbatim (recommend; UX lock) or sweep to plain hyphens?
- **Q6:** notify channels: push mock + Fire TV only (recommend); SMS/email stubs out?

PRD 12 overlaps: 12.1 name = Care Ladder (recommend keeping); 12.2 MCP primary with sim path (this plan); 12.3 = Q3; 12.4 = Q4; 12.5 repo strategy = locked by handoff (same repo, branch); 12.6 = Q6; 12.7 = keep as layout/state/pillar lock (this plan honors it).

## Execution order

Slice 1 -> 2 -> 3 (test-first in each), then 4 -> 5 -> 6; slice 7 only if it becomes real. Per-slice commits on `amazon/alexa-plus-fire-tv`; no main pushes until Q2 is decided.

## Verification baseline (every slice)

- `.venv/bin/python -m pytest -q` - baseline 83 passed, 2 skipped at branch point (`aebb167` + specs commit); every slice adds green tests, never red.
- Live OpenCV stack untouched until main merge (CI only deploys main).
- No credentials in tracked files; secrets scan before any push (repo is public).
- Em-dash-free docs; UI copy per Q5 decision.

## Plan self-review checklist

- [x] Every slice has acceptance criteria and named tests
- [x] Blast radius checked (CI/main/live stack isolated; OpenCV deadline vs Amazon deadline ordering)
- [x] PRD locks honored (Alexa+ primary, OpenCV trigger, Fire TV supporting, Bee/Ring out, fail-closed, Calm Care-Tech)
- [x] Open questions separated, only Q1 design-blocking
- [x] Anoop approves plan (2026-09-26: slices 1-3 approved to implement then check in; Q1 hold-and-restart on recovery; Q5 prototype UI copy verbatim, docs swept; Q4 browser-only recording)
