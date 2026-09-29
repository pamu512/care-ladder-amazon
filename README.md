# Care Ladder · Alexa+ · Fire TV · MCP

[![CI](https://github.com/pamu512/care-ladder-amazon/actions/workflows/ci.yml/badge.svg)](https://github.com/pamu512/care-ladder-amazon/actions/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-232F3E)](src/care_ladder/mcp_server/server.py)
[![Alexa+](https://img.shields.io/badge/Alexa%2B-primary-00CAFF)](docs/superpowers/specs/2026-09-26-amazon-care-ladder-alexa-plus-prd.md)
[![Fire TV](https://img.shields.io/badge/Fire%20TV-supporting-FC4C02)](src/care_ladder/api/static/firetv/index.html)

Camera cue → multi-rung care ladder → **Alexa+** agent (self-hosted MCP) → **Fire TV** caregiver audit (silhouette-only). Wellness ladder, not a medical device.

Product site: https://pamu512.github.io/care-ladder-amazon/

## Hackathon map

Amazon **Build, Ship, Shape** (draft — no Final Submit).

| Surface | Role |
| --- | --- |
| **Alexa+ (primary)** | Self-hosted MCP care-flow tools + in-repo simulated Alexa+ MCP client. Multi-rung, multi-turn, incident session state — not single-turn Q&A. |
| **Fire TV (supporting)** | Calm Care-Tech caregiver surface at `/firetv/` — D-pad focus, Ambient Hearth layout, data-driven from the live ladder API. |
| **MCP** | Spec **2025-11-25+** Streamable HTTP at `/mcp`. |
| **AWS Builder mini** | **Not filed.** No Bedrock / AgentCore in-tree. |

**MCP tools:** `start_or_resume_incident` · `check_in_prompt` · `advance_rung` · `resolve_incident` · `get_incident_status` · `notify_caretaker` · `request_call` · `caregiver_ack` · `caregiver_outcome`

**Proactive Events:** optional awareness chime only. Default **off**
(`CARE_LADDER_PROACTIVE=0`). Schema-locked; no rich buttons. Local sim
only. See [docs/proactive-events-honesty.md](docs/proactive-events-honesty.md).

## Agentic proof (not thin MCP)

Session state is keyed by **household + incident** (`household_id` + `incident_id`). Every MCP tool return includes a `session_snapshot` (`household_id`, `incident_id`, `rung`, `status`, `tools` trail) so the agent carries one memory across turns — not disconnected FAQ calls.

The in-repo MCP **client** `src/care_ladder/mcp_server/alexa_sim.py` drives a real HTTP initialize → `tools/call` chain and prints a `SESSION … rung=N status=…` banner after each call:

1. `start_or_resume_incident` — open the incident
2. `start_or_resume_incident` again with the same ids — resume-same-incident (`resumed: true`)
3. `check_in_prompt` — fail-closed intent (`clear_ok` / `needs_human` / `unclear`)
4. `advance_rung` / `notify_caretaker` / `resolve_incident` — same incident id throughout

Soft “don’t worry” can stand the ladder down; “okay but hurt” will not. Both Path A soft-OK and needs-human print resume-same-incident and keep one incident id from start → check-in → resolve/notify.

## Quickstart (≤60s to something on screen)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# One story: start API → open Fire TV → sim drives the same store the TV polls
./scripts/amazon_demo_path.sh
# 1) http://127.0.0.1:8010/firetv/ stays open
# 2) alexa_sim --answer "don't worry"  → TV resolves (same incident)
# 3) second sim (needs-human)          → TV stays notify → Acknowledge
```

Manual split (same coupling):

```bash
CARE_LADDER_ALLOW_INSECURE_LOCAL=1 .venv/bin/uvicorn care_ladder.api.app:app --port 8010
# Fire TV:  http://127.0.0.1:8010/firetv/     (Demo console, bottom right)
# MCP:      POST http://127.0.0.1:8010/mcp    (Streamable HTTP)
.venv/bin/python -m care_ladder.mcp_server.alexa_sim --url http://127.0.0.1:8010 --answer "don't worry"
```

MCP tool calls write the incident into the AuditStore Fire TV polls (`GET /incidents`). A calm **MCP agent active** pill shows on the TV only while the sim is driving, then auto-clears. Keep `/firetv/` visible — you should see the same incident change state within one sim run.

Amazon household: `configs/amazon_demo_home.yaml` (resident + primary/secondary contacts, stillness 4m). `configs/demo_home.yaml` is the legacy OpenCV plan, kept for before/after regression.

## Demo paths

| Path | Fixture | What judges should see |
| --- | --- | --- |
| Silence → notify | `alexa_path_a` | Two Alexa+ check-ins, 45s wait, notify + simulated call |
| Soft OK | `alexa_path_a_soft_ok` / `--answer "don't worry"` | Resolves; no notify |
| Needs human | `alexa_path_a_needs_human` / `--answer "I'm okay but I think I'm hurt"` | Does **not** resolve; notify stays up |
| Unclear | `alexa_path_a_unclear` | Groan / garbage → re-ask, then escalate |
| Path B occlusion | `alexa_path_b` | Covered camera is **privacy**, never distress (`camera_health_inform`) |

Fire TV Demo console posts these fixtures to `/demo/run`. Or:

```bash
# Local scripts set CARE_LADDER_ALLOW_INSECURE_LOCAL=1. Hosted: add the bearer.
curl -s -X POST http://127.0.0.1:8010/demo/run \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${CARE_LADDER_API_TOKEN}" \
  -d '{"fixture":"alexa_path_a_soft_ok"}'
```

## API auth & camera sources

`/mcp` and mutating routes (`POST /demo/run`, `/demo/upload`, `/demo/camera/start|stop`, incident ack, learning writes) require `Authorization: Bearer $CARE_LADDER_API_TOKEN`. If the token is unset those routes return **401** unless `CARE_LADDER_ALLOW_INSECURE_LOCAL=1` (loopback demo / pytest only). See [`.env.example`](.env.example).

MCP Streamable HTTP has DNS-rebinding protection on (`Host` allowlist: localhost / `testserver` plus `CARE_LADDER_MCP_HOSTS` for an ALB hostname).

`POST /demo/camera/start` accepts a device index, or an `rtsp`/`http(s)` URL whose host is `localhost` / `127.0.0.1` / `::1` or listed in `CARE_LADDER_CAMERA_HOSTS`. Cloud metadata IPs and arbitrary remote hosts are rejected.

## Privacy & fail-closed

- **Silhouette-only** on Fire TV — no live video element, no raw frames.
- Frames that leave the device path go through `blur_faces` / `to_silhouette` before attach.
- Emergency dial is **off** and **hard-locked** in this demo build (hold-to-review explains; no call possible).
- Demo phones are reserved NANP fiction only: **(555) 010-2276** (`+12125550176`).
- Footer copy: *Wellness ladder — not a medical device.*

Known limits: [`docs/failure-modes.md`](docs/failure-modes.md). Why this design: [`docs/research-brief.md`](docs/research-brief.md).

## Friction log

Honest tool/SDK notes (bonus): [`docs/friction-log.md`](docs/friction-log.md).

## Tests

```bash
.venv/bin/pytest tests/ -v
```

MCP handshake + care-flow tools, Fire TV HTML/API flow, response intent, `alexa_sim` client, and the shared ladder/API spine.

## Shared demo host (read-only from this repo)

Live HTTPS today: https://d2u7pls4da2poz.cloudfront.net/ — **shared host from the opencv-care-ladder stack**. CI on this repo is **test-only** (no auto-deploy) so OpenCV judges keep a stable CloudFront. Optional AWS replay: [`infra/README.md`](infra/README.md). Local run needs no AWS credentials: `./scripts/run_demo.sh`.

Vision ONNX models and eval clips are **not** committed. If you want the optional vision-trigger proofs: `./scripts/download_models.sh` and `./scripts/download_clips.sh`. Alexa+ fixtures do not need ONNX.

## Origins

Significant in-window update of OpenCV Care Ladder ([`pamu512/opencv-care-ladder`](https://github.com/pamu512/opencv-care-ladder)). Vision cues are vendored here as the trigger; Amazon work is MCP + Fire TV + rungs. The OpenCV repo stays separate until after OpenCV judging. No Bee / Ring / Bedrock / AgentCore.

## License

MIT © 2026 Anoop Pamu. See [`LICENSE`](LICENSE).
