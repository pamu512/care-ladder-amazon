# Amazon tools friction log

Honest record of what worked and what fought back, per Amazon surface touched.
(Submission requirement: product feedback notes on every tool/API/SDK used.)

**Attempt date for Rank 4 fill:** 2026-09-29. Demo video path is local
uvicorn → `/firetv/` + `alexa_sim` against `/mcp` (see
`scripts/amazon_demo_path.sh`). No pending surfaces remain for that path.

---

## mcp Python SDK (v2.2.0) - 2026-09-26

**Worked:** `MCPServer` (the v2 rename of FastMCP) tool registration is clean -
plain functions with type hints become MCP tools with schemas automatically.
`streamable_http_app()` returns a Starlette ASGI app; stateless mode removes
session-id bookkeeping for simple demos. The client half
(`streamable_http_client` + `ClientSession`) drove our server over real HTTP
first try once mounted correctly.

**Fought back:**

1. **v1 -> v2 rename with a hard error.** `mcp.server.fastmcp` no longer
   exists in 2.x; importing it raises a helpful-enough ModuleNotFoundError
   pointing at the migration guide. Cost: one probe cycle.
   - **Severity:** Low (one import cycle).
   - **Workaround:** Import `mcp.server.mcpserver.MCPServer`.
   - **Suggestion:** Put the v2 import path above v1 `FastMCP` examples in
     search results and the first page of the quickstart.

2. **ASGI mounts do not propagate lifespan.** `streamable_http_app()` wires
   its `StreamableHTTPSessionManager.run()` as the app's lifespan - but a
   Starlette Mount never runs a sub-app's lifespan, so every request died
   with `RuntimeError: Task group is not initialized. Make sure to use
   run().` Fix: enter `mcp.session_manager.run()` from the PARENT app's
   lifespan (`app.router.lifespan_context` wrapper). See also
   [uvicorn + FastAPI mount](#uvicorn--fastapi-mount-asgi-lifespan--trailing-slash).
   - **Severity:** High (every `/mcp` request 500s until the parent wraps
     lifespan; TestClient without `with` reproduces the same error).
   - **Workaround:** Parent-app lifespan enters `session_manager.run()`.
     Tests must use `with TestClient(app) as client:` so lifespan runs.
   - **Suggestion:** SDK mounting docs assume a standalone MCP app. A
     "mounting inside another ASGI app" recipe would have saved an hour.

3. **Session-manager attribute name.** We looked for
   `server._session_manager`; it is `server.session_manager` (public) and it
   only exists AFTER `streamable_http_app()` is called (lazy). An early
   access raises `RuntimeError: Session manager can only be accessed after
   calling streamable_http_app()`.
   - **Severity:** Low.
   - **Workaround:** Call `streamable_http_app()` first, then read
     `session_manager`.
   - **Suggestion:** Mention the lazy init in the first mounting snippet.

4. **DNS-rebinding protection defaults ON for localhost hosts** and returns
   HTTP 421 Misdirected Request for non-Host-header clients (including test
   transports). Behind an ALB/CloudFront the Host header differs from
   127.0.0.1, so we disabled it explicitly via
   `TransportSecuritySettings(enable_dns_rebinding_protection=False)`. The
   default is good security for standalone servers; confusing when mounted.
   See [CloudFront / ALB `/mcp`](#cloudfrontalbs-mcp--local-only-in-the-video).
   - **Severity:** Medium (tests and any non-localhost Host die with 421
     before you know the mount works).
   - **Workaround:** Disable DNS-rebinding on the mounted app; keep it on
     if you ever serve MCP standalone on loopback.
   - **Suggestion:** Document the 421 + Host-header contract next to the
     Streamable HTTP example, and show the `TransportSecuritySettings`
     override for reverse-proxy / TestClient hosts.

5. **Result shape:** tool dict returns arrive at the client both as
   `structuredContent` and a JSON text blob; tests must unwrap
   `structuredContent` for typed access.
   - **Severity:** Low.
   - **Workaround:** Prefer `result.structuredContent` (or the sim's
     `structured_content`).
   - **Suggestion:** One sentence in the tool-return docs: "clients should
     read `structuredContent`, not the text blob."

**Verdict:** usable, modern; the rough edges are all at the "embed in a larger
app" seam, which is exactly our deployment shape.

---

## Streamable HTTP transport (MCP 2025-11-25+) - 2026-09-26

Negotiation worked against both our TestClient-based tests and the real
uvicorn server; SSE and JSON response modes both observed. No version
mismatch errors once the client and server both declared 2025-11-25.

- **Severity:** Low (dual response shapes, not a blocker).
- **Workaround:** `_parse_sse_or_json()` in tests; `Accept:
  application/json, text/event-stream`.
- **Suggestion:** Publish the Accept-header + SSE-vs-JSON matrix on the
  transport page, not only in the spec appendix.

---

## Fire TV / Silk (or 1280×720 browser) - 2026-09-29

**Task attempted:** Launch the caregiver dashboard the demo video actually
uses, drive D-pad/remote-equivalent keys, and record at 1280×720.

**Steps:**

1. Local launch (video path): `uvicorn care_ladder.api.app:app --port 8010`
   then open `http://127.0.0.1:8010/firetv/`.
2. Chromium `--window-size=1280,720` screenshots of standby, needs-human,
   and occlusion (the shot-list fallback when a stick is not in the room;
   plan Q4 is browser-only recording).
3. Chrome DevTools: arrow keys + Enter on the notify/needs-human screen;
   Demo console → Show agent tools; Emergency gate click.
4. **Not in this session:** physical Fire TV stick / Silk, or the official
   Amazon Fire TV / Web App Tester simulator (neither is in this
   environment). Silk-specific CSS already in-tree from the original port.

**Expected vs actual:**

| Expected | Actual |
| --- | --- |
| `/firetv/` on the shared CloudFront host | **404** `{"detail":"Not Found"}` — opencv stack has `/ui/` only. Video path is local. |
| 1280×720 frame shows hero + rail + footer | Standby and occlusion fit. **Needs-human/notify overflows:** document ~787px vs a 720p window; footer (`Demo console`, wellness line) measured `visible: false`. |
| D-pad moves a visible amber ring along cards/buttons | First keypress is required (load focus is `BODY`). Buttons get `.focused` + ring. **Hero / presence take programmatic focus with `outline: none` and no `.focused` class, so they show no ring** (`:focus-visible` does not match CDP/`el.focus()`). Spatial heuristic can skip visual left-to-right (ArrowDown from the hero landed on **Request call**, not **Acknowledge**). |
| Remote Select / Enter activates the primary action | Enter on the focused **hero section** is a no-op. Emergency **Hold 3s** is `pointerdown` only — a D-pad Select never starts the hold. |
| Silk hides `[hidden]` demo-console tool list | `.agent-tools { display: flex }` would win over the `hidden` attribute. In-tree fix: `[hidden] { display: none !important; }`. After toggle, computed display is `flex` and the seven `tools/list` names appear. Fonts are self-hosted woff2 (no Google runtime). |

**Severity:** Medium for 720p notify clip + missing hero focus ring (video
shots 3–6/9). Low for Silk `[hidden]` (already patched). High only if a
judge expects a stick in-frame and we show a browser — Anoop owns that
hardware call.

**Workaround:**

- Launch URL for the tape: `http://127.0.0.1:8010/firetv/` (or whatever
  port `amazon_demo_path.sh` prints). Do not use
  `https://d2u7pls4da2poz.cloudfront.net/firetv/` until a dedicated Amazon
  deploy exists.
- Record 1280×720; for shot 5 (needs-human) hold on the hero + transcript,
  or use 1280×800, so the clipped footer is not the story.
- Arrow keys demonstrate D-pad; click **Acknowledge** / Emergency hold with
  a pointer for those beats. First Down/Right to put a ring on a button
  before talking about focus.
- Keep the `[hidden] { display: none !important; }` rule and vendored
  woff2; do not switch the tool list to `display: flex` without it.

**Suggestion (Amazon / Silk + us):**

- Silk / Fire OS docs: state that author `display:flex` beats the `hidden`
  attribute; recommend the `!important` (or `[hidden]{display:none}`)
  snippet in the Web App / 10-foot HTML guide.
- Fire TV remote: map long-press Select to `pointerdown`/`pointerup` or
  document that hold-to-confirm patterns need `keydown` repeat. We should
  also add `.focused` on hero/presence and a 720p-safe notify stack if we
  reshoot.

---

## CloudFront / ALB `/mcp` — local-only MCP in the video - 2026-09-29

**Task attempted:** Confirm whether the live demo host serves `/mcp` (and
`/firetv/`) or whether the Alexa+ tape must stay on local uvicorn.

**Steps (2026-09-29 probes):**

| URL | Result |
| --- | --- |
| `https://d2u7pls4da2poz.cloudfront.net/` | 404 JSON |
| `https://d2u7pls4da2poz.cloudfront.net/ui/` | **200** OpenCV console (~65 KB) |
| `https://d2u7pls4da2poz.cloudfront.net/incidents` | **200** (opencv household incidents) |
| `https://d2u7pls4da2poz.cloudfront.net/openapi.json` | **200**, 17 paths — **no `/mcp`, no `/firetv`** |
| `GET/POST …/mcp` and `POST …/mcp/` | **404** `{"detail":"Not Found"}` (`server: uvicorn`, `x-cache: Error from cloudfront`) |
| `https://d2u7pls4da2poz.cloudfront.net/firetv/` | **404** |
| ALB `http://care-ladder-demo-2017970097.us-east-1.elb.amazonaws.com/mcp` and `/firetv/` | **404** |
| `POST …/mcp` with `Host: 127.0.0.1` via CloudFront | **403** HTML from CloudFront (not MCP 421) |
| Local `POST http://127.0.0.1:8010/mcp/` initialize | **200** SSE, protocol `2025-11-25` |
| Local `POST /mcp` (no slash) | **307** → `/mcp/` |

`care-ladder-amazon` CI does not deploy. CloudFront is the **shared opencv
stack** (`infra/README.md`). Host-header / DNS-rebinding **421** is the
SDK default we already overrode locally; it was **not** observed on prod
because prod never reaches the MCP app.

**Expected vs actual:** A judge hitting the live HTTPS URL for `/mcp` or
`/firetv/` would expect the Alexa+ path. They get FastAPI 404 from the
pre-Amazon image.

**Severity:** High for anyone who treats CloudFront as the Amazon demo
(wrong story). Low for the planned tape — we already script local uvicorn.

**Workaround:** Video and README: **local-only MCP + Fire TV**.
`alexa_sim --url http://127.0.0.1:8010` (this session: initialize +
tools/call succeeded). Do not point judges at
`https://d2u7pls4da2poz.cloudfront.net/mcp`. Leave the opencv host
untouched until a dedicated Amazon hostname is approved.

**Suggestion:** One sentence on the CloudFront / Fargate sample: "a new
route (`/mcp`, `/firetv/`) is not live until you redeploy the task." For
the SDK: keep the 421 note (already above) for the day this *is* deployed
behind a `Host: *.cloudfront.net` header.

---

## uvicorn + FastAPI mount (ASGI lifespan + trailing slash) - 2026-09-26 / 2026-09-29

Cross-link: the MCP session manager must run on the **parent** FastAPI
lifespan. Starlette `Mount` does not start the sub-app lifespan. See mcp
SDK fight #2 and `create_app()` in `src/care_ladder/api/app.py`.

**New on 2026-09-29:** FastAPI/Starlette mount at `/mcp` issues **307
Temporary Redirect** from `POST /mcp` → `POST /mcp/`.

- `curl` without `-L`: empty 307 (looks like MCP is down).
- `curl -L` and Starlette `TestClient` (follow redirects): 200 SSE.
- `alexa_sim` uses `base_url.rstrip("/") + "/mcp"` (no trailing slash);
  the mcp client followed the redirect and initialized this session.

**Severity:** Medium for curl-from-README judges; Low once `-L` or `/mcp/`
is documented. Lifespan miss remains High (see SDK #2).

**Workaround:** Document `POST /mcp/` (slash) or `curl -L`. Keep the
parent lifespan wrapper. Use `with TestClient(...)` in any test that hits
`/mcp`.

**Suggestion:** FastAPI/Starlette: option to mount Streamable HTTP without
a slash redirect (POST + 307 drops body on naive clients). MCP SDK: show
the trailing-slash URL in the first Streamable HTTP client snippet.

---

## httpx2 / TestClient - 2026-09-29

Burned time on the MCP test seam (optional surface).

- `pyproject.toml` depends on **`httpx2>=2.0.0`**. `import httpx` is
  `ModuleNotFoundError` — FastAPI 0.141 `TestClient` imports `httpx2`.
- `TestClient(app)` **without** the context manager hits `/mcp/` with
  `RuntimeError: Task group is not initialized. Make sure to use run().`
  (same lifespan bug as the mount).
- `with TestClient(app) as client:` follows the `/mcp` → `/mcp/` 307 and
  returns SSE; tests unwrap with `_parse_sse_or_json`.
- Upstream warning we filter: Starlette TestClient still references
  `anyio.abc.BlockingPortal`.

**Severity:** Medium the first time (wrong package name + silent lifespan
skip). Low after the `with` + `httpx2` pin.

**Workaround:** Pin `httpx2`; never assume `httpx` is installed. Always
`with TestClient(create_app(...))`. Accept `application/json,
text/event-stream`.

**Suggestion:** FastAPI TestClient docs should say `httpx2` in the install
line. MCP: TestClient example should use the context manager so lifespan
runs.

---

## Devpost “tool feedback” paste (draft — not submitted)

Anoop can paste this into the Devpost field. Full log is this file. Do
**not** Final Submit from here.

1. **mcp SDK v2:** `FastMCP` import is a hard miss; use `MCPServer`. Search
   should rank the v2 path over v1 examples.
2. **ASGI mount lifespan:** mounted `streamable_http_app()` never runs
   `session_manager.run()` — every `/mcp` call dies with “Task group is
   not initialized” until the parent FastAPI lifespan wraps it. Need a
   “mount inside another ASGI app” recipe.
3. **DNS-rebinding 421:** default ON for localhost Hosts; TestClient and
   ALB/CloudFront Host headers fail closed. We set
   `TransportSecuritySettings(enable_dns_rebinding_protection=False)` on
   the mount. Document 421 next to the Streamable HTTP sample.
4. **uvicorn/FastAPI `/mcp` → `/mcp/` 307:** raw POST without a trailing
   slash (or `curl -L`) looks dead. Client snippets should show `/mcp/`.
5. **Fire TV / Silk:** no stick in this pass — recorded Chromium at
   1280×720 (`http://127.0.0.1:8010/firetv/`). Notify/needs-human clips
   the footer at 720p. D-pad spatial focus skips ring on hero cards;
   emergency hold is pointer-only. Silk: `display:flex` beats `[hidden]`
   unless `display:none !important`; we vendored woff2.
6. **CloudFront `/mcp` and `/firetv/`:** shared opencv host — both 404.
   **Local-only MCP in the video.** Do not send judges to
   `d2u7pls4da2poz.cloudfront.net/mcp`.
