# Alexa Mobile Caregiver + Shared FSM Beats: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status:** PLAN ONLY. Do **not** implement, open PRs, or Final Submit until Devt/Anoop say go.
> **Repo:** `pamu512/care-ladder-amazon` @ main `606da4e8d188` (Rank 1–4 + CI merged; pytest 106).
> **Source FSM contract:** `/workspace/care-ladder-console-handoff/home/home-guide.md` (Family Chat-First) beats only, **not** WA/TG adapters.
> **Owner:** Careladder-AWS (`df7af528-…`). Hermes = Mac Cursor worker when coding starts.

**Goal:** Port the shared family-chat FSM beats onto the Alexa+ session so caregiver ack happens in the **Alexa mobile skill** (talk/ack stops the ladder), while Fire TV stays a supporting in-home visual (frames, timeline, MCP demo), with optional thin Proactive Events as awareness-only.

**Architecture:** Keep the existing MCP Streamable HTTP + `session_snapshot` deepen stack. Add a channel-agnostic **CareConversation FSM** (states/timers/copy) that Alexa+ session tools and `alexa_sim` drive. Remap `notify_caretaker` away from Fire-TV-as-pager toward Alexa-mobile conversational notify. Fire TV becomes read-mostly living-room surface. Optional Proactive Events = schema-locked chime only.

**Tech Stack:** Python FastAPI, MCP SDK Streamable HTTP, existing `alexa_sim` MCP client, Fire TV static `/firetv/`, pytest, YAML care plans. No Bee/Ring/Bedrock. No Stripe/Portal. No opencv `main` merge.

## Global Constraints

- Alexa+ **primary**; Fire TV **supporting**; Skip Ring; **no Final Submit** without Anoop.
- Port **FSM + copy**, not WhatsApp/Telegram `BotThread` adapters.
- Caregiver surface on Amazon = **Alexa mobile** (open skill, conversational ack, stop ladder).
- Proactive Events = thin awareness chime only (schema-locked, opt-in); not rich buttons; document honesty.
- Fire TV = living-room frames / ladder timeline / MCP demo only, **not** the caregiver pager.
- Notify copy/stills: blurred frame + countdown + **three clear actions**.
- Docs/VO: console = **setup + archive** honesty (not the live pager).
- SKIP: full WA/TG BotThread in this repo; Stripe/Portal/facility gov; Ring/Bee/auto-911; merge into opencv `main`.
- No em dashes in served copy or VO. Wellness ladder, not a medical device. Emergency off + hard lock.
- Reserved NANP fiction phones only (`+12125550176`).
- Do not force-push `main`.

---

## 0 · Product decision (Amazon cut)

Family chat-first (SaaS) says: family lives in chat; console is setup+archive.  
**Amazon lock (Anoop via Devt):** on this track the caregiver lives in **Alexa mobile**, not WA/TG and not Fire TV as pager.

| Beat (shared FSM) | SaaS surface (out of Amazon scope) | Amazon surface (this plan) |
| --- | --- | --- |
| `speaker_window` | Mom asked on speaker; reply resolves before family paged | Existing `alexa_checkin` ×2 on resident Echo / sim (`SpeakerSimulator` + MCP `check_in_prompt`) |
| `family_paged` | WA/TG inform card | Alexa mobile skill session: notify card copy + three actions + conversational ack |
| `pressure` | Warn at t−3:00 | Same timer on Alexa mobile session; Fire TV may **mirror** timeline only |
| `calling_N` | Voice call stub ladder | Existing `request_call` / dial stubs (simulated); secondary contact in plan |
| ANY ack | Chat button / numbered / ack-link | Alexa mobile utterance or explicit ack tool; **first wins**; stops escalation |
| Outcome → closed | Free-text “how did it go?” | Conversational outcome in Alexa mobile; `resolve` + documentation audit line |
| Audit hops + timestamps | Bot audit events | Every FSM transition → `AuditEvent` with `at` |

---

## 1 · Current repo evidence (main `606da4e`)

### 1.1 Tree (relevant)

```
configs/amazon_demo_home.yaml          # Amazon rung order
src/care_ladder/mcp_server/server.py   # 7 MCP tools + session_snapshot
src/care_ladder/mcp_server/alexa_sim.py# MCP client demo agent
src/care_ladder/ladder/orchestrator.py # alexa_checkin / wait_window / notify / request_call / emergency
src/care_ladder/channels/speaker.py    # SpeakerSimulator (resident check-in)
src/care_ladder/channels/response_intent.py  # clear_ok / needs_human / unclear
src/care_ladder/channels/dial.py       # StubDialer
src/care_ladder/audit/store.py         # AuditStore + MCP driving pill TTL
src/care_ladder/api/app.py             # FastAPI + /mcp mount + /firetv/
src/care_ladder/api/static/firetv/index.html  # Ambient Hearth + Acknowledge + MCP pill/tools
docs/demo-video-script-amazon.md       # VO still treats Fire TV as caregiver surface
docs/friction-log.md                   # Rank 4 filled
tests/test_{mcp,alexa_sim,firetv,amazon_*,response_intent,orchestrator}.py
```

**Absent in this repo (present only in SaaS family plan):** `channels/bot.py`, `channels/notify.py`, `channels/ack.py`, `channels/router.py`, WA/TG adapters. Amazon channels package exports speaker + dial only.

### 1.2 Alexa+ / MCP (already deepened Rank 1–3)

Seven tools: `start_or_resume_incident`, `check_in_prompt`, `advance_rung`, `resolve_incident`, `get_incident_status`, `notify_caretaker`, `request_call`.  
Every return carries `session_snapshot` (`household_id`, `incident_id`, `rung`, `status`, `tools`).  
`alexa_sim` prints SESSION banners; Path A soft OK resolves; needs_human → notify; silence → notify + request_call.  
Mutations persist into shared `AuditStore` so Fire TV `/incidents` sees the same incident (`bind_audit_store`, MCP pill).

### 1.3 Notify today (gap vs Anoop lock)

`notify_caretaker` (MCP + orchestrator + YAML) uses channels **`["push_mock", "fire_tv"]`**, simulated.  
Fire TV UI is titled **“Fire TV Caregiver Dashboard”**, shows notify phase, **Acknowledge** button as primary human close, and is framed in VO shot 3 as “The caregiver surface is now a Fire TV dashboard.”  
That conflicts with the new lock: caregiver = Alexa mobile; Fire TV = supporting visual.

### 1.4 FSM today (partial)

Orchestrator already has resident speaker window (`alexa_checkin` → clear_ok resolve / needs_human jump to notify / unclear continues), `wait_window` 45s, notify, request_call, emergency fail-closed.  
**Missing vs shared F3:** named conversation states, pressure timer, multi-step call ladder as FSM, caregiver conversational ack that stops escalation from Alexa mobile, outcome documentation turn, per-hop `at` timestamps on `AuditEvent` (model has `acked_at` on Incident only; events lack `at`).

### 1.5 Intent / check-in

`response_intent.py` locked: `clear_ok` / `needs_human` / `unclear`. Soft “don’t worry” = clear_ok; mixed hurt = needs_human; groans = unclear.  
Resident path is solid; **caregiver ack classifier** for Alexa mobile does not exist yet.

### 1.6 Fire TV / MCP demo (keep, reframe)

Ambient Hearth, silhouette, rung rail, transcript + intent labels, MCP agent active pill, Agent path · MCP footer, default-hidden Show agent tools (7 names), Acknowledge still present as **demo/archive control** (not primary pager). Rank 2 script `scripts/amazon_demo_path.sh` couples sim → TV.

### 1.7 Tests

~106 passed on tip. Amazon-critical: `test_mcp_server.py`, `test_alexa_sim.py`, `test_firetv_app.py`, `test_amazon_paths.py`, `test_amazon_rungs.py`, `test_response_intent.py`, `test_orchestrator.py`. No `test_bot_fsm.py`.

### 1.8 Proactive Events

**No code or docs** in `care-ladder-amazon` for Alexa Proactive Events / skill messaging. Greenfield optional thin layer.

### 1.9 External FSM source (port beats only)

`home-guide.md` §2.1 states:

```
idle → speaker_window → family_paged → pressure → calling_N → closed
ANY ack → stop escalation; ask outcome; close with documentation
```

Three inform actions (design): “I'm on it, call her myself” / “Call Mom now” / “Can't take it, go to {next}”.

---

## 2 · Phase order (Amazon) + file map

| Phase | Delivers | Depends |
| --- | --- | --- |
| **A0 · Plan lock** | This doc reviewed; go from Devt/Anoop | (none) |
| **A1 · FSM core + timestamps** | Channel-agnostic conversation FSM + `AuditEvent.at` | A0 |
| **A2 · Alexa mobile caregiver surface** | MCP/sim tools for family_paged / ack / outcome; remap notify channels | A1 |
| **A3 · Fire TV reframe** | Copy/UI: supporting visual, not pager; keep timeline/MCP; soft stills hooks | A2 |
| **A4 · Optional Proactive Events** | Thin chime stub + honesty docs (feature-flagged) | A2 |
| **A5 · Demo/VO/docs** | Script, PITCH, README, friction honesty; console=setup+archive | A3–A4 |
| **A6 · Tests green + ready PRs** | Suite ≥ current + new FSM/ack tests; no Final Submit | A1–A5 |

### File map (where things land)

```
# NEW
src/care_ladder/channels/care_conversation.py   # FSM: states, timers, transitions, copy builders
src/care_ladder/channels/caregiver_intent.py    # classify caregiver Alexa utterances → ack actions
configs/amazon_demo_home.yaml                   # remap notify channels; pressure/call timers
docs/superpowers/plans/2026-09-29-alexa-mobile-family-fsm.md  # this plan (commit when coding)
docs/proactive-events-honesty.md                # optional A4
tests/test_care_conversation_fsm.py
tests/test_caregiver_intent.py
tests/test_alexa_mobile_ack.py

# MODIFY
src/care_ladder/models.py                       # AuditEvent.at: datetime
src/care_ladder/ladder/orchestrator.py          # stamp at=; optionally drive FSM on notify/call
src/care_ladder/mcp_server/server.py            # notify_caretaker → alexa_mobile; new tools OR extend existing
src/care_ladder/mcp_server/alexa_sim.py         # caregiver session path (family_paged → ack → outcome)
src/care_ladder/api/app.py                      # endpoints if needed for mobile sim / stills payload
src/care_ladder/api/static/firetv/index.html    # reframe copy; Acknowledge demoted; three-action mirror optional
docs/demo-video-script-amazon.md                # Alexa mobile as caregiver; Fire TV supporting
docs/amazon-split/PITCH.md / README.md          # surface roles
docs/friction-log.md                            # PE / mobile honesty if touched
```

**Will NOT create:** `bot.py` WA/TG adapters, `demo_family.yaml` chat channels, Stripe/Portal, Ring modules.

---

## 3 · Tasks (bite-sized; implement only after go)

### Task 1: Audit timestamps

**Files:** Modify `models.py`, `orchestrator.py` `_append`, MCP `_append_mcp_event`; Test: extend `test_orchestrator.py` / new assert.

- [ ] Add `at: datetime | None = None` on `AuditEvent` (default factory `datetime.now(timezone.utc)` when appending).
- [ ] Ensure every `_append` / MCP append sets `at`.
- [ ] Tests: incident trail events each have non-null `at`; order preserved.
- [ ] Commit: `audit: stamp at on every AuditEvent`

### Task 2: CareConversation FSM (no adapters)

**Files:** Create `care_conversation.py`; Test: `test_care_conversation_fsm.py`.

**Interfaces:**
- Produces: `CareState = idle|speaker_window|family_paged|pressure|calling_1|calling_2|closed`
- `CareConversation.start_speaker(...)`, `.expire_to_family_paged(...)`, `.pressure(...)`, `.start_call(n)`, `.ack(action, by, raw)`, `.record_outcome(text)`, `.audit_events()` 
- Copy builder: `inform_card(blurred_frame_ref, cue_text, countdown_sec, actions[3])`

FSM rules (mirrors F3, Alexa-shaped):
1. Cue → `speaker_window` (resident Alexa check-in). Resident `clear_ok` → `closed` (family never paged).
2. Speaker expires / needs_human / unclear-after-attempts → `family_paged` (Alexa mobile inform).
3. At t−3:00 before deadline → `pressure` warn on mobile session.
4. Deadline → `calling_1` then `calling_2` (stubs); exhausted if no answer.
5. **ANY** caregiver ack (`im_on_it` | `call_mom_now` | `pass_to_next`) from conversational classifier or explicit tool → stop escalation; owner=acker; ask outcome.
6. Outcome free text → `closed`; documentation=reply; close card audit line.
7. One active conversation per household; new cue while open joins same thread.
8. Distress bypasses quiet hours (already orchestrator); keep.

- [ ] Failing tests for each transition + first-wins ack.
- [ ] Minimal implementation (pure Python, no network).
- [ ] Green + commit: `fsm: CareConversation shared beats for Alexa session`

### Task 3: Caregiver intent classifier

**Files:** Create `caregiver_intent.py`; Test: `test_caregiver_intent.py`.

Map utterances → `im_on_it` | `call_mom_now` | `pass_to_next` | `outcome` | `unclear` (fail-closed).  
Three clear action phrasings must match inform card labels.

- [ ] TDD keyword/patterns (mirror resident intent style).
- [ ] Commit: `intent: caregiver Alexa mobile ack classifier`

### Task 4: Remap notify + MCP caregiver tools

**Files:** `amazon_demo_home.yaml`, `server.py`, `orchestrator.py`, `alexa_sim.py`; Test: `test_mcp_server.py`, `test_alexa_mobile_ack.py`, `test_amazon_rungs.py`.

- [ ] YAML `notify_caretaker.channels`: `["alexa_mobile"]` (+ optional `proactive_chime` later). Remove `fire_tv` as notify channel (Fire TV still **reads** store).
- [ ] Extend `notify_caretaker` payload: `surface: alexa_mobile`, `inform_card` (blurred frame id, countdown, three actions), `fsm_state: family_paged`.
- [ ] Add MCP tools (preferred explicit) **or** extend existing:
  - `caregiver_ack(household_id, incident_id, utterance|action)` → stops ladder, audits
  - `caregiver_outcome(household_id, incident_id, text)` → closes with documentation
- [ ] Wire `alexa_sim` Path C: after notify, simulate caregiver “I'm on it” → no further call; then outcome → resolved.
- [ ] Keep resident Path A soft OK / needs_human behavior.
- [ ] Commit: `amazon: Alexa mobile caregiver notify + ack tools`

### Task 5: Fire TV reframe (supporting only)

**Files:** `firetv/index.html`, `test_firetv_app.py`, optional stills fixtures.

- [ ] Title/subcopy: living-room care timeline / Ambient Hearth (not “Caregiver Dashboard” as pager).
- [ ] Notify phase: mirror “family informed on Alexa mobile” + countdown; **do not** require TV Acknowledge to stop ladder (ack already done on mobile). Keep Acknowledge as optional demo/archive control labeled honestly.
- [ ] Soft stills support: blurred frame thumb + three action labels visible for video (even if non-interactive on D-pad).
- [ ] MCP pill / agent tools toggle unchanged (judge proof).
- [ ] Tests update string greps; Path A labels survive.
- [ ] Commit: `firetv: supporting timeline; Alexa mobile is pager`

### Task 6: Optional thin Proactive Events (A4)

**Files:** New small module or stub under `channels/proactive_events.py`; `docs/proactive-events-honesty.md`; feature flag `CARE_LADDER_PROACTIVE=0` default off.

Honesty limits (must appear in README/friction):
- Alexa Proactive Events / skill messaging is **schema-locked**; no free-form rich notify.
- Opt-in only; may be unavailable in sim; demo must not claim push buttons arrived via PE.
- Role = **awareness chime** (“check Alexa app”) that fans into the mobile skill session, not a substitute for conversational ack.
- If Amazon APIs unavailable in hackathon window: stub + document “local sim only”.

- [ ] Stub interface `send_awareness_chime(household_id, incident_id) -> {simulated: true}`.
- [ ] Optional hook from `family_paged` transition when flag on.
- [ ] Docs + friction entry.
- [ ] Commit: `proactive: thin awareness chime stub (opt-in)`

### Task 7: Demo choreography + VO/docs (A5)

**Files:** `docs/demo-video-script-amazon.md`, `scripts/amazon_demo_path.sh`, `PITCH.md`, `README.md`, console static copy if shown.

Choreography changes:
1. Shots 1–2: before/after OK.
2. Shot 3: Fire TV = **in-home visual** (timeline/silhouette), not caregiver pager.
3. Shots 4–5: resident clear_ok / needs_human (unchanged intent story).
4. **New beat:** Alexa mobile (or `alexa_sim` caregiver mode) receives inform card (blurred frame, countdown, three actions); caregiver says “I'm on it”; ladder stops; outcome closes; Fire TV timeline mirrors hops with timestamps.
5. Shot 8: MCP proof still mid-late; TV updates as **audit mirror**.
6. Console (if shown): setup + archive honesty only.

- [ ] Rewrite VO word-for-word for surface roles.
- [ ] Extend `amazon_demo_path.sh` with caregiver ack step.
- [ ] Pitch/README tables: Alexa mobile primary caregiver; Fire TV supporting; PE optional thin.
- [ ] Commit: `docs: Alexa mobile caregiver choreography`

### Task 8: Acceptance gate + PR hygiene (A6)

- [ ] Full pytest green (expect ~110–120 after new tests).
- [ ] Ready (non-draft) stacked or sequential PRs: FSM → mobile notify/ack → Fire TV reframe → docs (+ optional PE).
- [ ] Ping Devt with PR URLs + HEAD SHAs + pytest count.
- [ ] **No Final Submit.** No opencv `main` merge.

---

## 4 · Acceptance criteria

1. **FSM:** Cue → speaker_window; resident clear_ok closes without family_paged. Silence/needs_human → family_paged on Alexa mobile with blurred frame + countdown + three actions in payload/copy.
2. **Ack:** Conversational caregiver ack (or explicit action) stops pressure/call ladder; audit shows channel=`alexa_mobile`, `at` timestamps, owner.
3. **Outcome:** Free-text outcome closes incident; documentation on trail.
4. **Fire TV:** Still shows silhouette timeline + MCP demo; copy does not claim TV is the pager; Acknowledge not required to stop escalation.
5. **MCP:** Seven existing tools remain; new caregiver tools listed in tools/list; session_snapshot continuity preserved.
6. **PE (if built):** Default off; when on, chime-only + honesty doc; no fake rich buttons.
7. **Tests:** New FSM/ack tests green; existing Amazon suite still green.
8. **Docs/VO:** Surfaces match Anoop lock; console=setup+archive; no Final Submit language as done.

---

## 5 · Demo choreography (target story)

1. OpenCV cue (stillness) → resident Alexa check-in (sim).
2. Soft OK path: ladder stands down; Fire TV shows resolve on timeline.
3. Needs-human / silence path: Alexa **mobile** inform (card: blurred still, countdown, three actions) → caregiver “I'm on it” → pressure/call never fire → outcome “Called Mom, she's fine” → closed.
4. Fire TV living room: frames + rung rail + audit hops with times (mirror).
5. MCP shot: `alexa_sim` (resident + caregiver modes) drives same AuditStore; MCP pill on TV.
6. Disclaimer: not medical; emergency off.

---

## 6 · Honest Proactive Events limits

- Not a free-form notification API; catalogs/schemas constrain content.
- Cannot replace conversational ack or three rich actions inside PE itself.
- Opt-in / availability varies; sim path must work with PE off.
- Demo VO must say “awareness chime” if shown; actions happen in the skill session.
- If implementation blocked by Amazon account/API access: ship stub + friction log, do not block A1–A3.

---

## 7 · Risks

| Risk | Mitigation |
| --- | --- |
| VO/demo still sell Fire TV as pager | A5 rewrite before reshoot; block Final Submit until VO matches |
| FSM duplicated in orchestrator vs MCP session | Single `CareConversation` owned by channels; orchestrator + MCP call into it |
| `AuditEvent.at` breaks serialization clients | Optional field with default; Fire TV JS tolerates missing then prefers `at` |
| Scope creep into WA/TG | Explicit skip list; reject PRs adding router/bot adapters here |
| PE oversell | Flag default off + honesty doc required in A4 |
| Ack on TV vs mobile double-close | First-wins registry; TV Acknowledge becomes no-op if already acked on mobile |

---

## 8 · What we will NOT do

- WhatsApp / Telegram `BotThread`, inline keyboards, template management in this repo.
- Stripe, customer portal, facility governance consoles.
- Ring / Bee / Bedrock / AgentCore / auto-911.
- Merge `amazon/*` or this work into `opencv-care-ladder` `main` before OpenCV judging.
- Final Submit / Devpost field edits beyond draft unless Anoop asks.
- Rich Proactive Events buttons or claiming PE delivered the three actions.
- Replacing MCP deepen stack or removing Fire TV supporting surface.
- Real PSTN dials or non-555 numbers.

---

## 9 · Go / no-go

**Waiting on Devt + Anoop:** approve this plan (or mark deltas) before any coding PR.

Suggested reply: `go A1–A3` | `go A1–A5` | `go A1–A5 + optional A4` | `revise: …`
