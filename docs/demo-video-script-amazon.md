# Care Ladder - Amazon Build, Ship, Shape update (in-window)

Demo video (≤3 min) - English VO, ~135 wpm pacing. Path A (clear OK + needs
human) then Path B (camera occluded). Before/after framing per PRD §6.

**Video order:** calm product first (shots 3–7). MCP proof is mid-late (shot 8).
Never open the tape on a terminal wall of JSON. Before/after OpenCV stub vs
Alexa+ still lands in the first 20s (shots 1–2).

**Device truth:** prefer a Fire TV stick (Silk) or the official simulator in
frame. Browser at 1280×720 is the fallback if a stick is not available —
Anoop decides hardware.

| # | Time | Shot | VO (word-for-word) |
|---|------|------|--------------------|
| 1 | 0:00–0:12 | BEFORE: existing OpenCV Care Ladder console (`/ui/`), fire `no_movement_silence` fixture, rail lights up cue → speaker → dial ×2 | Before this update, Care Ladder already watched the room with OpenCV and climbed a careful ladder: notice, ask, then call. But it asked through a speaker stub, and the caregiver watched from a web console. |
| 2 | 0:12–0:20 | Title card: "Care Ladder for Alexa+ - same project, significant in-window update" | This is the same project, significantly updated for Alexa+. The camera still triggers everything. What changed is what happens next. |
| 3 | 0:20–0:45 | Fire TV dashboard `/firetv/` all-clear state. Arrow keys demonstrate D-pad focus moving between cards | The caregiver surface is now a Fire T V dashboard. Calm by design — silhouette only, no live video feed, never a live camera feed — and a remote-friendly interface that works with just the D-pad. |
| 4 | 0:45–1:05 | Demo console → "Soft OK · no okay". Transcript shows the resident: "don't worry" plus a **Clear OK** label; hero flips to resolved | When OpenCV sees four minutes of stillness, Alexa+ checks in. Soft reassurance - don't worry - is a clear OK even without the word okay. The ladder stands down. The transcript is the real line plus the intent label. |
| 5 | 1:05–1:25 | Reset, then "Mixed hurt reply". Transcript quotes "I'm okay but I think I'm hurt" with **Needs human**; hero stays notify, does not resolve | The same check-in does not treat every utterance as binary OK. Okay-but-hurt stays on the TV as needs a human. The ladder does not clear. |
| 6 | 1:25–1:35 | Click "Acknowledge" → Resolved · acknowledged state, trail stays | A human closes the loop. The acknowledgement is part of the audit trail, not a silent read receipt. |
| 7 | 1:35–2:00 | Demo console → "Path B · camera occluded". Hero shows camera-blocked state; silhouette shows "No reading · lens covered"; the blanket prompt in transcript; notify card says inform, no distress claim | Cover the camera and Care Ladder does not panic. Occlusion reads as privacy, not distress. It asks the resident to move the blanket, and if there's no answer it informs the primary contact on exactly that basis - no distress is ever claimed. |
| 8 | 2:00–2:20 | Split: Fire TV stays in frame while the terminal runs `alexa_sim` (`--answer "don't worry"`). MCP initialize + tools/call; TV audit/transcript updates on the same incident; calm **MCP agent active** pill while the sim drives, then auto-clears | Under the hood, the Alexa+ path runs on a self-hosted MCP server - Streamable HTTP, current spec - exposing seven care-flow tools. This simulated Alexa+ agent is an MCP client driving the real ladder — the TV is watching the same incident, not a second demo glued on. |
| 9 | 2:20–2:40 | Footer of the TV: wellness disclaimer, emergency off; emergency gate modal opened, hold attempted, stays locked | Two things this system will not do: claim to be medical, or call emergency services on its own. Emergency is off by default and hard-locked in this build. |
| 10 | 2:40–2:55 | Split screen: OpenCV console (before) + Fire TV (after) | Same project, same fail-closed spine - now with an Alexa+ agent doing the check-in and Fire TV keeping the family in the loop. Care Ladder. |

## Pre-record checklist
- Cold run: `./scripts/amazon_demo_path.sh` (starts uvicorn on 8010, opens `/firetv/`,
  runs soft-OK then needs-human against the same store the TV polls).
- Or: `./scripts/run_demo.sh` (port 8000 occupied on the dev machine - use a free
  port like 8010), then open `/firetv/`.
- Live AWS: `https://d2u7pls4da2poz.cloudfront.net/firetv/` (after this branch deploys - until then, local only).
- Fire `alexa_path_a_soft_ok` and `alexa_path_a_needs_human` once before
  recording so the audit trail has history — or use the choreography script so
  shot 8 is the live MCP → TV story, not a glued fixture.
- Terminal ready with the sim command:
  `.venv/bin/python -m care_ladder.mcp_server.alexa_sim --url http://127.0.0.1:<port> --answer "don't worry"`
- Record Fire TV stick / Silk if available; otherwise browser at 1280×720.
  VO ~400 words ≈ 2:55 at 135 wpm.

## Remux / VO timing (reshoot beat)

Existing VO that described Path A as two silent attempts then “no answer,
notify Anoop” must be replaced. Keep shots 1–3 (0:00–0:45) and 8–10 as-is.

**Cut out:** old shot 4–5 (stillness cue → silence → wait 45s → calling Anoop).
**Cut in:** new shot 4 (Clear OK / “don’t worry”, ~20s) then shot 5 (Needs
human / mixed hurt, does not auto-resolve, ~20s). Hold 8–10 frames on the
intent badge in the transcript so the label is readable.

Optional B-roll (not required if time is tight): demo console “Unclear groan”
shows `nngh` + Unclear and still notifies — same as no clear answer.

If the locked VO track cannot be re-recorded, overlay a 3–4s lower-third on
the new shot 4/5: “Clear OK — don’t worry” / “Needs human — did not clear”.
Do not keep the old “answered / no speech” beat; it no longer matches the TV.

## Notes
- All phone numbers on screen are reserved fictional (555) 010-2276.
- The TV is data-driven: every state change reflects a real incident's audit
  events from the API - it is not a disconnected mock slideshow.
- MCP mutations land in the same AuditStore `/incidents` polls. Shot 8 should
  show the TV move (resolve / notify + MCP pill) while the sim transcript runs.
