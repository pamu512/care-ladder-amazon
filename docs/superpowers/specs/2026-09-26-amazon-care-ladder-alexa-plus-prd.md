# PRD: Care Ladder for Amazon Build, Ship, Shape (Alexa+ primary)

**Status:** Draft for Anoop review (edit freely; not implementation-approved until you say so)  
**Date:** 2026-09-26  
**Author:** Devt (from locked product decisions + Fire TV UX handoff)  
**Hackathon:** [Build, Ship, Shape: Amazon Developer Hackathon](https://amazonappdev2026.devpost.com/)  
**Deadline:** 2026-10-24 03:00 HKT (2026-10-23 12:00 PDT)  
**Repo base:** `opencv-care-ladder` (existing OpenCV Care Ladder; significant in-window update)  
**Related specs:** `2026-09-11-agentic-senior-care-ladder-design.md`, `2026-09-17-galuxium-care-ladder-saas-design.md`  
**Fire TV UX:** `fire-tv-dashboard/` (interactive prototype + design canvas + screenshots from 2026-09-26 handoff)

---

## 1. Summary

Ship a **significant update** of Care Ladder that wins Stage 1 on the **Alexa+** track while keeping OpenCV as the vision trigger and adding a **Fire TV** caregiver dashboard as supporting Amazon tech.

**One-line:** Camera notices something is wrong → agent climbs a fail-closed care ladder → Alexa+ runs multi-step check-in → Fire TV shows the caretaker what happened → notify/call without claiming clinical diagnosis or auto-911.

---

## 2. Locked decisions (do not silently reverse)

| Decision | Lock |
| --- | --- |
| Approach | **A — Alexa+ primary** |
| Vision trigger | **Keep OpenCV camera cues** (stillness / no-visibility / distress-family) |
| Voice / agent path | **Alexa+** monitoring + check-in via self-hosted **MCP** (spec ≥ 2025-11-25, Streamable HTTP) and/or **Agent Skill**, plus simulated Alexa+ web path if needed for demo |
| Caregiver surface | **Fire TV** dashboard (Fire OS or Vega OS / simulator OK), design locked by `fire-tv-dashboard/` prototypes |
| Bee | **Out** for this hack (Apple Watch alone is not Bee live data) |
| Ring | Out for this filing |
| Classic ASK-only skill | **Not** the Stage 1 gate (may exist as legacy; Alexa+ MCP/Agent is what we file) |
| Prize filing | Primary track **Alexa+**; Fire TV in same project as supporting; optional **AWS Builder** mini if real AWS agent stack is used |
| Win limit | One project can win at most **1 main track + 1 mini** |
| Clinical / 911 | Fail-closed: not clinical; emergency dial off by default with hard human gate |
| Design pillars | **Empathetic** (warm home object, never a control room); **audit-grade clarity**; **never voyeuristic** (silhouettes only; frames stay on device) |
| Demo household | Monitored person **Meera**; primary caretaker **Anoop**; contacts Anoop → Priya; plan example: living-room stillness **4m** |

---

## 3. Problem

Solo families and small home-care setups cannot staff a camera. Seniors and recovering people need a ladder that **confirms before it escalates**: notice stillness or missing visibility, check in by voice with session memory, escalate to a primary caretaker, and leave an audit trail. Raw alert spam and single-turn “are you okay?” bots are not enough.

---

## 4. Goals / non-goals

### Goals (hackathon v1)

1. **Alexa+ Stage 1 pass:** runtime use of self-hosted MCP (≥ 2025-11-25) or Agent Skill, or a documented simulated Alexa+ agent experience with source in repo.
2. **Agentic, not thin Q&A:** multi-step check-in, wait windows, no-answer advance, escalate, resolve; multi-session / incident state.
3. **OpenCV still drives the plan:** cue output changes the next rung / tool (same spirit as OpenCV Agentic Vision Care Ladder).
4. **Fire TV caregiver UX:** match the locked Calm Care-Tech dashboard (see §8.4); D-pad navigable; live state machine in demo, not a static mock slideshow.
5. **Significant update story:** clear before/after vs pre-window Care Ladder in README + ≤3 min demo.
6. **Privacy defaults:** silhouette / on-device processing; no live video on the TV; reserved fictional phones in demos.
7. **Friction log** for bonus scoring (Amazon tools, MCP, Fire TV sim, AWS if used).
8. **Public GitHub** (OSS license) or private shared per Amazon invite list before expiry.

### Non-goals (v1)

- Bee / Ring tracks
- Medical diagnosis, fall “accuracy” claims, identity biometrics
- Auto emergency services without explicit enabled rung + human gate
- Full Galuxium multi-tenant SaaS (Slack/Teams facility mode) unless it fits leftover time
- Appstore publish requirement (not required by rules)
- Partner Alexa+ preview tooling (Category SDK / MCP Toolkit / CLI / Web Simulator are unavailable to participants)
- Live video feed or cloud persistence of raw frames on the caregiver UI

---

## 5. Users

| Role | Needs |
| --- | --- |
| Monitored person (demo: Meera) | Low-friction voice check-in; clear that this is wellness support, not a doctor |
| Primary caretaker (demo: Anoop) | See incidents on Fire TV; get notify/call; acknowledge / resolve |
| Household configurer (may be caretaker) | Care plan: zones, timeouts, contacts, rung order |
| Hackathon judges | Proof of required Alexa+ tech + OpenCV→action trace + coherent Fire TV UX |

**ICP for this filing:** home-care / family caregiver (not full assisted-living enterprise). Facility Slack/Teams path stays future.

---

## 6. Product narrative (demo spine)

1. **Before:** OpenCV Care Ladder demo (camera → ladder → speaker/phone stub) without Alexa+ MCP / Fire TV surfaces.
2. **All clear (default):** Fire TV shows standby; care plan active; last check-in remembered.
3. **Cue:** OpenCV emits `no_movement` or `no_visibility` (or distress-family heuristic).
4. **Rung 1:** Re-perceive / hold (occlusion reads as privacy, not distress, while the room cannot be read).
5. **Rung 2:** Alexa+ multi-turn check-in (two voice attempts); TV quotes the conversation.
6. **Rung 3:** 45-second wait window; silence advances.
7. **Rung 4:** Notify caretaker (push to phone + this TV); optional request call with reserved fictional number; Acknowledge stands the ladder down.
8. **Audit trail:** Full mono-timestamped history stays on screen and in the log.
9. **After:** Same incident visible end-to-end; friction log callout.

Demo video ≤ **3 minutes**, English, public YouTube/Vimeo.

---

## 7. Architecture (logical)

```
Camera / clip feed
    → OpenCV cue service (existing Care Ladder path)
    → Ladder orchestrator (care plan JSON/YAML)
         ├→ Alexa+ MCP server / Agent Skill  (check-in, session, escalate tools)
         ├→ Notify / dial adapters (demo-safe)
         └→ Event bus / audit log
              → Fire TV caregiver app (timeline + status; Calm Care-Tech UI)
              → Optional AWS (Bedrock / AgentCore) for planner if used for mini
```

**Hard Amazon gate:** MCP server implements Streamable HTTP per MCP spec dated **2025-11-25 or later**, callable at runtime from the agent path used in demo (or Agent Skill equivalent). Simulated Alexa+ web experience is an allowed alternate path but must include sim source and still look agentic.

---

## 8. Functional requirements

### 8.1 OpenCV cues (reuse + tighten)

- Support at least: `no_movement`, `no_visibility`, one distress-family heuristic.
- Configurable timeouts / zones via care plan.
- Emit structured cue events the orchestrator consumes.
- Occlusion / lens covered: treat as camera-health / privacy holding path, not automatic distress claim (see §8.4 Path B).

### 8.2 Ladder orchestrator

- Load versioned care plan.
- Rungs (prototype lock):
  1. **Re-perceive** (Rung 1)
  2. **Voice check-in** via Alexa+ (Rung 2)
  3. **Wait** closed after silence window (Rung 3; default **45s**)
  4. **Notify caretaker** (Rung 4; push + Fire TV)
  5. **Request call** (optional action on Rung 4; reserved fictional number in demo)
  6. **Emergency** (ships **off**; hard human gate; demo build hard-locked so no real call can be placed)
- Default demo plan copy: `living-room stillness 4m · contacts Anoop → Priya`.
- No-answer within wait → advance.
- Affirmative OK → resolve and log.
- Full audit trail per incident (mono timestamps).

### 8.3 Alexa+ surface (primary)

- Self-hosted MCP tools exposing care flows, for example:
  - `start_or_resume_incident`
  - `check_in_prompt` / record response
  - `advance_rung` / `resolve_incident`
  - `get_incident_status`
  - `notify_caretaker` / `request_call`
- Multi-session state keyed by household + incident id.
- Not a single-turn FAQ wrapper around one API.
- Product feedback notes on every Amazon tool/API/SDK used (submission requirement).
- Prototype prompt examples (voice surface quotes these on the TV):
  - Stillness: “Meera, are you okay?” then “Meera, it’s Anoop’s Care Ladder — can you hear me?”
  - Occlusion: “Meera, the camera is covered — could you move the blanket?”

### 8.4 Fire TV surface (supporting) — UX lock from handoff

**Source of truth (do not invent a different TV UI without editing this PRD):**

| Artifact | Path |
| --- | --- |
| Interactive twin (D-pad + state machine + demo console) | `fire-tv-dashboard/care-ladder-fire-tv-prototype.html` |
| Design canvas (context, pillars, system, screen map) | `fire-tv-dashboard/care-ladder-fire-tv-design-canvas.html` |
| Screenshots | `fire-tv-dashboard/screenshots/` |

**Layout (10-foot):**

- Top bar: Care Ladder brand · “Meera’s home · Fire TV” · status pill · clock
- Main grid: large hero card (rung chip, incident id, title, subcopy, wait segments, actions) + right rail (silhouette panel + Alexa+ check-in transcript)
- Bottom: horizontal **AUDIT TRAIL**
- Footer: “Wellness ladder — not a medical device” · “Emergency dial off by default” · plan summary · **Demo console**

**Status pill vocabulary:** Care plan active / Re-checking / Checking on Meera / Calling Anoop / Resolved (and Camera blocked on occlusion path).

**Design system (Calm Care-Tech):**

| Token | Role |
| --- | --- |
| Ground `#24221E` / deep `#1E1C18` | Warm dark living-room object |
| Surface `#2E2B25` | Cards |
| Ink `#EFEAE2` | Primary text |
| Sage `#A8B5A0` | Reassurance / all-clear |
| Amber `#D9A05B` | Attention / check-in in progress |
| Clay `#D98873` | Urgent notify |
| Slate `#9DB0C7` | Info / re-perceive |
| Instrument Sans | UI type |
| JetBrains Mono | Audit timestamps and incident ids |
| Focus ring | Amber double ring for D-pad focus |

Accents are rationed: **one attention color per screen**.

**Privacy UI rules:**

- No live video anywhere in the caregiver UI.
- Room renders as **silhouette · processed on device** (or **No reading · lens covered**).
- “Listen in” may appear as a disabled affordance; prototype stance: audio never leaves the room.
- Push note copy pattern: `Push sent to Anoop’s phone · this TV · HH:MM`.

**Required states (match prototype):**

| Phase | Rung chip | Hero (examples) |
| --- | --- | --- |
| All clear | Standby | All clear · Meera settled after lunch · living room |
| Recheck | Rung 1 · Re-perceive | Meera has not moved in 4 minutes |
| Check-in | Rung 2 · Voice check-in | Alexa is checking on Meera · two attempts · then 45s wait · then it calls for you |
| Wait closed | Rung 3 · Wait closed | (bridge to notify) |
| Notify | Rung 4 · Notify caretaker | Meera has not responded · calling Anoop · Acknowledge / Request call / Emergency off |
| Occlusion Path B | Rung 1 holding → ask to move blanket → Rung 4 inform | Coverage reads as privacy, not distress; later: camera still covered · **no distress is being claimed** |
| Resolved | Resolved · acknowledged | Acknowledged — you took it from here · trail preserved |

**Interaction:**

- Runnable on Fire OS or Vega OS **or** official simulator; demo video must show it.
- D-pad / remote focus (arrow keys + Enter in HTML twin).
- Demo console drives: simulate cue, Meera answers OK, let silence win, camera occluded, run full demo, reset; emergency gate hold-to-review with hard lock in demo.
- Must not look like a static mock slideshow in the submission video.

### 8.5 Privacy and safety

- Blur / silhouette before cloud persistence where applicable; TV never shows raw frames.
- Demo phones = reserved fictional numbers (prototype uses `(555) 010-2276`).
- Emergency rung disabled unless explicitly enabled; never imply live 911; demo build cannot place a call.
- Clear UI copy: wellness ladder, not medical device.

### 8.6 Submission pack

- Devpost project: description, primary Alexa+, optional AWS mini fields, tool feedback.
- GitHub public + OSS license (preferred) or private + Amazon/Devpost invites.
- Demo ≤3 min with before/after of in-window work.
- Friction log markdown in repo.

---

## 9. Success metrics (hackathon)

| Bar | Pass condition |
| --- | --- |
| Stage 1 Alexa+ | Required tech demonstrably used at runtime (or valid sim path) |
| Design | Coherent OpenCV → Alexa+ → Fire TV story in one demo; TV matches locked Calm Care-Tech UX |
| Impact | Credible home-care case without clinical overclaim |
| Idea | Agentic ladder + multi-surface Amazon, not thin skill wrap |
| Ship | Submitted before deadline with video + repo + feedback fields |

---

## 10. Milestones (suggested, ~4 weeks)

| Week | Outcome |
| --- | --- |
| W1 | PRD approved; MCP skeleton + care-plan tools; OpenCV cue wired to orchestrator; Fire TV app shell on sim matching §8.4 layout |
| W2 | Full check-in / no-answer / escalate + occlusion Path B; audit + timeline API; privacy silhouette on exported frames |
| W3 | Fire TV polish (D-pad, demo console parity); end-to-end Path A/B demos; friction log; AWS mini only if already real |
| W4 | ≤3 min video; Devpost draft; Tarka-circle style review; Submit by Oct 23 PDT |

Exact dates can slip; **Submit buffer** before 2026-10-24 03:00 HKT is mandatory.

---

## 11. Risks

| Risk | Mitigation |
| --- | --- |
| Alexa+ partner tools unavailable | Self-host MCP or ship high-quality sim; do not depend on preview stack |
| Thin-skill judging fail | Multi-step state, media/cards if available, incident memory |
| Fire TV looks fake | Real sim build in video; ship from interactive twin, not screenshots only |
| Scope explosion (Galuxium SaaS + dual tracks) | Home-care only; one primary track; Bee/Ring cut |
| Pre-existing project | Document significant update; before/after in demo |
| Private GitHub invite expiry (7 days) | Prefer public OSS early |
| Voyeurism / clinical overclaim | Silhouette-only UI; occlusion copy never claims distress; wellness disclaimers in footer |

---

## 12. Open questions for Anoop (edit answers in place)

1. **Project name** for Devpost/GitHub (Care Ladder vs new Amazon-facing name)?  
2. **MCP vs Agent Skill vs sim:** preferred primary implementation path?  
3. **AWS Builder mini:** pursue Bedrock/AgentCore / Kiro Crew, or skip to protect schedule?  
4. **Hardware:** any Fire TV stick/device available, or simulator-only?  
5. **Repo strategy:** continue `opencv-care-ladder` vs new `care-ladder-amazon` repo that vendors/subtree the OpenCV core?  
6. **Notify channel for caretaker in demo:** partially locked by UX as **push mock + this TV**; confirm SMS/email stubs in or out.
7. **Fire TV UX:** treat `fire-tv-dashboard/` as pixel-level lock for v1, or allow visual polish as long as layout/states/pillars hold?

---

## 13. Approval

- [ ] Anoop reviewed and edited this PRD  
- [ ] Architecture §7 accepted or revised  
- [ ] Fire TV UX §8.4 accepted or revised  
- [ ] Milestones §10 accepted or revised  
- [ ] Open questions §12 answered  
- [ ] Ready for implementation plan (`writing-plans`) — **no coding until this box is checked**

---

## 14. Changelog

| Date | Change |
| --- | --- |
| 2026-09-26 | Initial PRD from Approach A lock (Alexa+ primary, OpenCV trigger, Fire TV supporting, Bee out) |
| 2026-09-26 | Folded Anoop Fire TV handoff: design pillars, Calm Care-Tech tokens, five-rung + occlusion Path B, Meera/Anoop demo household, prototype + canvas + screenshots under `fire-tv-dashboard/` |
