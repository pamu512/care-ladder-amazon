# DEEPEN — make Amazon criteria loud without drowning the calm product

**Product north star:** Calm dementia / senior **care ladder** (empathetic Ambient Hearth, silhouette-only, fail-closed).  
**Hackathon scream:** Alexa+ primary · multi-step agentic + **session state** · MCP Streamable HTTP · Fire TV supporting · friction log (+10%) · ≤3 min device-truth video.  
**Tip:** `amazon/alexa-plus-fire-tv` @ `0fbfb111`.  
**Owners:** Hermes = Mac Cursor worker on repo; Anoop = product/voice/submit; Careladder-AWS `df7af528-…` owns leftovers after this plan.  
**Non-goals locked:** Bee, Ring, Bedrock/AgentCore (AWS Builder mini **not** filed unless something real appears).

Ranked by **judge impact ÷ product risk**. Effort: S ≤0.5d · M ~1d · L multi-day.

---

## Rank 1 — (a) Agentic multi-rung session-state narrative (code + UI copy)

### Why judges care
Alexa+ creative bar fails “thin MCP” (single-turn FAQ wrapping one API). Criteria want **multi-step agentic** flows with **session state**. Care Ladder already has incident sessions + seven tools; judges must *see* household+incident continuity and rung memory in under 3 minutes.

### What to deepen (loud, still calm)
1. **Code:** Ensure every MCP tool return includes `household_id`, `incident_id`, `rung` / `status`, and `tools` trail (partially present on `get_incident_status` / `start_or_resume_incident`). Add a single `session_snapshot` field reused by tools so the sim transcript reads as one agent memory, not disconnected calls.  
2. **alexa_sim.py:** Print a one-line “SESSION … rung=N status=…” banner between tool calls; Path A soft-OK and needs-human both show resume-same-incident.  
3. **Fire TV copy (calm):** Hero subcopy already names attempts/wait; tighten Ambient Hearth lines to say “same incident · Alexa+ agent remembers” without ops jargon. Rung rail labels stay human (“Alexa+ voice check-in ×2”), not raw tool names in the hero.  
4. **Audit trail:** Keep mono timestamps; optionally prefix MCP-driven events with a quiet `via mcp` detail flag for the video zoom — visible to judges, not shouty in standby.

### Effort / owner
- **M** · **Hermes** implements; **Anoop** approves VO/UI strings; Careladder-AWS verifies after split.

### Acceptance check
- [ ] One incident id survives start → check_in → notify/resolve in sim transcript  
- [ ] Fire TV shows intent label + raw line on soft OK and needs-human without clearing wrongly  
- [ ] README “Agentic proof” section lists session key + tool sequence  
- [ ] No new surfaces (no Bee/Ring/Bedrock)

---

## Rank 2 — (d) Demo path that shows live MCP → ladder → Fire TV

### Why judges care
Submission rules: repo must **call** the track tech in code; video must show Agent Skill or MCP (or sim) **in action**. Device-truth ≤3 min — lead with best material. Shot 8 in `docs/demo-video-script-amazon.md` already plans terminal sim; deepen so Fire TV updates *while* MCP calls land (one story, not two demos glued).

### What to deepen
1. **Single choreography script** (docs + optional `scripts/amazon_demo_path.sh`): start uvicorn → open `/firetv/` → run `alexa_sim` with `--answer "don't worry"` → TV resolves; second run needs-human → TV stays notify → Acknowledge.  
2. **Sim → API coupling:** Confirm alexa_sim mutations are the same store the Fire TV polls (already same FastAPI app); add a visible “MCP agent active” calm pill on TV **only while** an MCP session is driving (auto-clear) — optional S if time.  
3. **Video order:** Keep calm product first (shots 3–7), MCP proof mid-late (shot 8), never open on a terminal wall of JSON.  
4. **Device truth:** Prefer Fire TV stick Silk or official simulator in frame for supporting track credibility; browser-at-1280×720 acceptable fallback if stick unavailable — Anoop decides hardware.

### Effort / owner
- **S–M** · **Hermes** script + wiring; **Anoop** records VO/video; Careladder-AWS checks live URL notes.

### Acceptance check
- [ ] Cold run: third party can follow README and see TV state change from sim within one incident  
- [ ] Demo video ≤3:00 shows MCP initialize + tools/call **and** Fire TV audit/transcript  
- [ ] Before/after OpenCV stub vs Alexa+ still in first 20s  

---

## Rank 3 — (b) MCP tool visibility in Fire TV / UI

### Why judges care
Design + Tech Implementation: coherent product on the target surface. Tools must be real in repo; TV should make the **agent path** legible without turning the living-room UI into a developer console.

### What to deepen (calm visibility)
1. **Caregiver-facing (primary):** Keep “Alexa+ check-in” transcript + rung rail — already good. Add a single footer/meta line when events came from MCP: `Agent path · MCP` in ink-40, not a tool dump.  
2. **Judge-facing (secondary, toggled):** Demo console “Show agent tools” expands a mono list of the seven tool names used *this incident* (from audit/`tools` array). Off by default so standby stays calm.  
3. **Do not** put JSON-RPC payloads on the 10-foot hero.

### Effort / owner
- **S** · **Hermes** UI toggle + test anchors in `test_firetv_app.py`; **Anoop** visual OK.

### Acceptance check
- [ ] Default TV still Calm Care-Tech (one attention color, silhouette, no live video)  
- [ ] Toggle reveals exact seven tool names matching `tools/list`  
- [ ] Tests assert toggle + default-hidden  

---

## Rank 4 — (c) Friction-log completeness (+10% judging bonus)

### Why judges care
Explicit bonus up to **10%** for friction logs: task attempted, steps, expected vs actual, severity, workaround, actionable suggestion — per tool/API/SDK used. Current `docs/friction-log.md` is strong on **mcp SDK + Streamable HTTP**, weak on **Fire TV/Silk** and **CloudFront/ALB `/mcp`** (marked pending).

### What to deepen
Fill pending surfaces honestly as touched:

| Surface | Minimum entry |
| --- | --- |
| Fire TV / Silk (or simulator) | Launch URL, D-pad/remote, recording 1280×720, any focus/CSS pain |
| CloudFront/ALB `/mcp` (if deployed) | Host header / DNS-rebinding 421 already noted — confirm prod path or document “local-only MCP in video” |
| uvicorn + FastAPI mount | Cross-link ASGI lifespan lesson (already written) |
| Optional: httpx2 / TestClient | Only if it burned time |

Also paste a **short** friction summary into Devpost “tool feedback” field (draft already sketches three bullets — extend when Fire TV entry exists).

### Effort / owner
- **S** · **Hermes** drafts from real attempts; **Anoop** edits tone for submit; Careladder-AWS ensures file present in `care-ladder-amazon`.

### Acceptance check
- [ ] No “Pending surfaces” left for anything shown in the demo video  
- [ ] Each entry has severity + workaround + suggestion  
- [ ] Devpost feedback field mirrors repo log (not empty)

---

## Rank 5 — Polish that helps without scope creep

| Item | Why | Effort | Owner |
| --- | --- | --- | --- |
| LICENSE on amazon tip / new repo | OSS / Open Source mini gate | S | Hermes |
| Amazon-first README (see REPO-PLAN §5) | Judges land on scream criteria | S | Hermes; Anoop review |
| Intent badge hold frames in video | Soft OK / needs-human readable | S | Anoop (edit) |
| CI green on amazon tip | Trust | S | Hermes |

---

## (e) What NOT to add

| Temptation | Why not |
| --- | --- |
| **Bee** | Track needs live Bee (or Apple Watch Bee) data; we do not have it; filing would fail honesty bar |
| **Ring** | Out of lock; dilutes Alexa+ primary story |
| **Bedrock / AgentCore / Strands / Kiro Crew** | AWS Builder mini only if **real** in-tree; PRD/devpost say not filed — do not sprinkle imports for show |
| Classic ASK-only skill as Stage-1 gate | Not the Alexa+ MCP/Agent bar |
| Live camera on Fire TV / raw frames | Breaks privacy pillar; voyeurism risk |
| Auto-911 / enabling emergency in demo | Fail-closed lock; hard gate stays locked |
| Galuxium multi-tenant SaaS / Slack facility mode | Scope explosion |
| Renaming product / new brand for filing | Devpost draft: keep Care Ladder |
| Merging amazon → opencv `main` pre–OpenCV judging | Competition isolation lock |
| Final Submit without Anoop | Process lock |

---

## Suggested sequencing (post–repo-plan approval)

1. LICENSE + Amazon-first README (or split repo per REPO-PLAN)  
2. Rank 1 session narrative (code + calm copy)  
3. Rank 2 demo choreography + record  
4. Rank 3 MCP visibility toggle  
5. Rank 4 friction Fire TV (+ deploy if any)  
6. Anoop Final Submit gate  

