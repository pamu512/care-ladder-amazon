# One-page Devpost pitch rewrite: Care Ladder × Amazon creative language

**Use:** Elevator pitch + “How it works” bullets on https://devpost.com/software/care-ladder  
**Track map:** Primary **Alexa+** · Supporting **Fire TV** · MCP Streamable HTTP (spec 2025-11-25+) · AWS Builder mini **not** filed  
**Tone:** Calm care product first; Amazon criteria named precisely, not hyped  
**Status:** Draft for Anoop. No Final Submit

---

## Elevator pitch (≈95 words)

When a home camera goes quiet (stillness, a covered lens, a distress-family cue), Care Ladder does not spam alerts. A fail-closed **care ladder** confirms before it escalates. An **Alexa+** agent, driven through our **self-hosted MCP server** (Streamable HTTP), runs a multi-step voice check-in with **session memory** for the open incident. The family’s **Fire TV** shows a calm, silhouette-only dashboard: the real conversation, intent label, and full audit trail, never a live video feed. Soft reassurance can stand the ladder down; “okay but hurt” will not. Not a medical device; emergency dial stays off unless a human unlocks it.

---

## Track one-liners (paste near top)

- **Alexa+ (primary):** Self-hosted MCP care-flow tools + in-repo simulated Alexa+ MCP client. Multi-rung, multi-turn, incident session state (not single-turn Q&A).  
- **Fire TV (supporting):** Calm Care-Tech caregiver surface at `/firetv/`: D-pad focus, Ambient Hearth layout, data-driven from the live ladder API.  
- **Open source:** MIT; significant in-window update of the OpenCV Care Ladder spine (vision still triggers; Amazon surfaces are new).

---

## Rungs → Amazon creative language

| Rung (product) | Amazon-facing language for judges | What they should see |
| --- | --- | --- |
| **Standby / care plan active** | Ambient household agent ready; Fire TV as living-room object | All-clear hero; plan summary; wellness footer |
| **Rung 1 · Re-perceive** | On-device vision cue → agent **starts or resumes** an incident session | Cue in audit; slate “re-checking”; occlusion holds as **privacy**, not distress |
| **Rung 2 · Alexa+ voice check-in ×2** | **Agentic multi-turn** check-in via MCP `check_in_prompt`; fail-closed intent (`clear_ok` / `needs_human` / `unclear`) | Transcript quotes raw line + intent; soft “don’t worry” resolves; mixed hurt does **not** |
| **Rung 3 · Wait window (45s)** | Session waits; silence **advances** the same incident (stateful, not a new chat) | Wait segments / bridge to notify |
| **Rung 4 · Notify caretaker** | MCP `notify_caretaker` → push mock **+ this Fire TV** | Clay notify card; Acknowledge is an audit event |
| **Request call (optional)** | MCP `request_call` simulated; reserved fiction `(555) 010-2276` | Never PSTN; clearly simulated |
| **Emergency (off)** | Human gate only; demo **hard-locked** | Hold-to-review explains; no call possible |
| **Resolve** | MCP `resolve_incident` / caretaker Acknowledge. Trail preserved | Resolved state; history remains |

**MCP tool spine (name them once in Devpost):**  
`start_or_resume_incident` · `check_in_prompt` · `advance_rung` · `resolve_incident` · `get_incident_status` · `notify_caretaker` · `request_call`

---

## Before / after (required for pre-existing projects)

- **Before:** OpenCV cues → speaker/dial **stubs** → web console.  
- **After (in-window):** Same cue spine → **Alexa+ MCP agent path** → **Fire TV** caregiver dashboard → occlusion Path B (inform, never invent distress).

---

## Creative-bar checklist (map into description)

1. **Multi-step agentic:** not one tool, one answer.  
2. **Session state:** household + incident id across tools.  
3. **MCP in code + video:** `/mcp` Streamable HTTP; `alexa_sim.py` client transcript.  
4. **Fire TV device truth:** dashboard runs on Fire OS/Silk or simulator in the ≤3 min video.  
5. **Friction log:** `docs/friction-log.md` (+ Devpost feedback) for bonus.  
6. **Privacy / impact:** silhouette-only; credible home-care story without clinical claim.

---

## What we deliberately do not claim

- Bee, Ring, or Bedrock/AgentCore (not in this filing).  
- Medical diagnosis or automatic emergency dispatch.  
- Live caregiver video.

---

## Links block (update when repo split ships)

- GitHub: *pending Anoop* → `care-ladder-amazon` public (until then: `pamu512/opencv-care-ladder` branch `amazon/alexa-plus-fire-tv` @ `0fbfb111`)  
- Demo video: ≤3:00 English (shot list `docs/demo-video-script-amazon.md`)  
- Friction log: `docs/friction-log.md`

