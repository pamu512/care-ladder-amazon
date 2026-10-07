# Devpost field draft - Care Ladder (Amazon Build, Ship, Shape)

**NOT a submission. Draft for Anoop / Tarka-circle review. No Final Submit.**

## Project name
Care Ladder (keep repo name; no new brand for this filing)

## Elevator pitch (100 words budget)
OpenCV notices something wrong - stillness, a covered camera, a fall
signature - and a fail-closed care ladder confirms before it escalates: an
Alexa+ agent checks in by voice (two attempts, real conversation quoted on
the caregiver's Fire TV), waits, then notifies the family with a complete
timestamped audit trail. The same repo shipped the OpenCV-only version
earlier; this in-window update adds the Alexa+ MCP agent path and the Fire
TV dashboard. Not a medical device; never calls emergency services on its
own; silhouette-only video.

## Track
- **Primary: Alexa+** - self-hosted MCP server (Streamable HTTP, MCP spec
  2025-11-25+) exposing seven care-flow tools; a simulated Alexa+ agent
  (in-repo MCP client) drives the ladder at runtime over real HTTP. Multi-step,
  multi-session incident state - not single-turn Q&A.
- **Supporting: Fire TV** - Calm Care-Tech caregiver dashboard (D-pad focus,
  silhouette only, audit trail, demo console wired to the real orchestrator).
- **AWS Builder mini: in repo, not live-deployed by CI.** SageMaker cue
  endpoint is flag-gated (`CARE_LADDER_SAGEMAKER_ENDPOINT`) on the same
  `models/fall_classifier.npz` the local fallback uses (no ONNX, no Bedrock
  foundation model). AgentCore Gateway is configured to forward
  `Authorization` to self-hosted `/mcp`. ECR, ECS Fargate, ALB, CloudFront,
  DynamoDB, S3, and EventBridge are the existing shared opencv stack.
  Live SageMaker and Gateway creates stay off until the spend flags are set.
  Open Source mini: Yes (public MIT). Architecture gallery refresh is a
  follow-up. No Final Submit from this draft.

## What we built (before/after)
- **Before (pre-window, same repo):** OpenCV cue detection (person/pose ONNX
  chain on real fall footage), care-plan rungs, speaker/dial stubs, web
  console, AWS live deployment (CloudFront/ALB/ECS Fargate).
- **After (this update):** Alexa+ check-in rungs (2 attempts, 45s wait window
  with occlusion hold-and-restart), notify/request-call rungs (simulated,
  reserved fictional numbers), self-hosted MCP server at /mcp, in-repo Alexa+
  sim client (agent-callable proof), Fire TV dashboard at /firetv/, occlusion
  Path B (privacy, never distress).

## How we used the required tech (evidence)
- MCP server: `src/care_ladder/mcp_server/server.py` - MCPServer (mcp SDK
  2.2.0), Streamable HTTP, mounted in the FastAPI app.
- Agent path: `src/care_ladder/mcp_server/alexa_sim.py` - MCP client driving
  initialize → tools/call chain over HTTP; visible transcript in the demo
  video.
- Fire TV: `src/care_ladder/api/static/firetv/index.html` - data-driven from
  /incidents (not a mock slideshow); D-pad spatial focus; emergency
  hold-to-review hard-locked.

## Tool feedback (friction log summary)
Full log: `docs/friction-log.md` (paste-ready block at the bottom). Highlights:
1. mcp SDK v2 renamed FastMCP → MCPServer with a hard import error; the
   migration guide is good but the v2 import path should outrank v1 examples
   in search.
2. ASGI mounts do not propagate lifespan - the MCP session manager silently
   fails ("Task group is not initialized") unless the parent app enters
   `session_manager.run()` itself. A "mount inside another ASGI app" recipe
   would save embedders an hour.
3. DNS-rebinding protection defaults ON for localhost hosts and returns 421
   behind an ALB; needed explicit TransportSecuritySettings override.
4. FastAPI mount 307: `POST /mcp` → `/mcp/`. curl without `-L` looks dead;
   client snippets should show the trailing slash.
5. Fire TV / Silk (1280×720 Chromium fallback; no stick this pass): notify
   clips the footer at 720p; D-pad ring misses hero cards; emergency hold is
   pointer-only; Silk `display:flex` beats `[hidden]` without `!important`.
6. CloudFront `/mcp` and `/firetv/` 404 on the shared opencv host — local-only
   MCP in the video. Do not send judges to `d2u7pls4da2poz.cloudfront.net/mcp`.

## Privacy & safety (visible in product)
- Silhouette-only on the Fire TV; frames privacy-transformed before persist.
- Emergency dial off by default, hard-locked in the demo build (hold-to-review
  gate explains but never enables).
- All phone numbers reserved fictional (555) 010-2276.
- Footer: "Wellness ladder — not a medical device".

## Links
- Repo: https://github.com/pamu512/care-ladder-amazon
- Demo video: docs/demo/care-ladder-amazon-demo.mp4 (00:02:03, English). Shot list: docs/demo-video-script-amazon.md. Not a Final Submit.
- Friction log: docs/friction-log.md

## Team
(Anoop fills)
