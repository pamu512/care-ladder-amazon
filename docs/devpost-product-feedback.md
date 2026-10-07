# Devpost product feedback (draft)

**Not a Final Submit.** Paste-ready notes for the Amazon Build / Ship / Shape
per-tool field that goes to the Fire TV, Alexa+, Ring, and Bee teams. Full
engineering log: [`docs/friction-log.md`](friction-log.md). Honesty for the
optional chime: [`docs/proactive-events-honesty.md`](proactive-events-honesty.md).

Every claim below is grounded in this repo (code, comments, configs, tests,
scripts, docs, or commit messages). Builder device and console notes are
first person from Anoop. We do not invent beyond those notes. In-repo
notify, APL render, Proactive Events, and dial paths stay simulated unless
a line names a live step.

**Simulator / stub policy:** if a path never called Amazon's live API, this
doc says so. The demo that judges can run is local uvicorn plus
`alexa_sim` (`scripts/amazon_demo_path.sh`).

Ring and Bee were not used. See [Amazon tools we did not use](#amazon-tools-we-did-not-use).

---

## Amazon tools we used

### 1. Alexa+ (self-hosted MCP agent path, in-repo simulator)

**What we used it for**

Primary hackathon surface. Camera cues climb a fail-closed ladder; an Alexa+
shaped agent then drives the incident over MCP Streamable HTTP.

- Care-flow tools live in `src/care_ladder/mcp_server/server.py` (`MCPServer("Care Ladder")`).
  Tools include `start_or_resume_incident`, `check_in_prompt`, `advance_rung`,
  `resolve_incident`, `get_incident_status`, `notify_caretaker`, `request_call`,
  `caregiver_ack`, `caregiver_outcome`, `defer_escalation`, `tick_care_timers`,
  `how_is_household`, `confirm_schedule_pin`.
- The in-repo client `src/care_ladder/mcp_server/alexa_sim.py` is labeled
  "Simulated Alexa+ agent" and drives a real HTTP `initialize` then `tools/call`
  chain. It prints a `SESSION household=... incident=... rung=... status=...`
  banner after each call (`_session_banner`).
- Household plan `configs/amazon_demo_home.yaml`: cue to `reperceive` to
  `alexa_checkin` x2 to `wait_window` (45s) to `notify_caretaker` to
  `request_call` (simulated) to `emergency` (`enabled: false`).
- Orchestrator rungs `alexa_checkin` / `wait_window` / `notify_caretaker` /
  `request_call` in `src/care_ladder/ladder/orchestrator.py`.
- Resident intent buckets in `src/care_ladder/channels/response_intent.py`
  (`clear_ok` / `needs_human` / `unclear`). Spoken I/O is
  `SpeakerSimulator` in `src/care_ladder/channels/speaker.py`
  ("Nest/Alexa-style spoken check-in channel (simulator only for v1)").
- Demo fixtures `alexa_path_a`, `alexa_path_a_soft_ok`,
  `alexa_path_a_needs_human`, `alexa_path_a_unclear`, `alexa_path_b` in
  `src/care_ladder/api/app.py`, asserted by `tests/test_amazon_paths.py`.
- One-story script: `scripts/amazon_demo_path.sh`.

This is **not** a published Alexa+ Agent Skill and **not** Amazon's partner
preview Category SDK / MCP Toolkit / CLI / Web Simulator. The PRD
(`docs/superpowers/specs/2026-09-26-amazon-care-ladder-alexa-plus-prd.md`
section 4) says those partner tools were unavailable to participants. We
used the allowed sim path: self-hosted MCP plus an in-repo client
(PRD section 5 goal 1; `alexa_sim.py` docstring cites "PRD 7").

**What worked well**

- Session memory is keyed by household + incident. Every tool return includes
  `session_snapshot` (`src/care_ladder/mcp_server/server.py`). Soft OK
  (`--answer "don't worry"`) resolves; mixed "okay but hurt" does not. Tests:
  `tests/test_alexa_sim.py`, `tests/test_amazon_paths.py`,
  `tests/test_response_intent.py`.
- MCP mutations write the same `AuditStore` Fire TV polls (`bind_audit_store`).
  The TV shows an "MCP agent active" pill only while the sim drives
  (`src/care_ladder/api/static/firetv/index.html`).
- Fail-closed intent is deterministic and documented: concern tokens beat
  reassurance (`response_intent.py` comment: `"I'm okay but I think I'm hurt"`
  stays `needs_human`).
- Local hello-world is short. README "Quickstart" plus
  `./scripts/amazon_demo_path.sh` starts uvicorn, opens `/firetv/`, and runs
  both sim paths against the live store.

**What needs work**

- There is no live Alexa+ runtime in this tree. `SpeakerSimulator` queues
  scripted strings. `docs/failure-modes.md` says a real Nest/Alexa skill
  would add ASR errors the simulator does not model.
- FastAPI mounts `/mcp` with a trailing-slash 307 (`docs/friction-log.md`,
  2026-09-29). `alexa_sim` posts `base_url + "/mcp"` and relies on the MCP
  client to follow the redirect. Raw `curl` without `-L` looks dead.
- ASGI mounts do not run the MCP session-manager lifespan. Parent FastAPI
  must enter `session_manager.run()` or every `/mcp` call 500s with
  "Task group is not initialized" (`src/care_ladder/api/app.py` comments;
  friction log mcp SDK fight 2).
- We never called a hosted Alexa+ agent. Commit `a2b11bb` ("session_snapshot
  + Alexa+ SESSION banners") and `f0dd0de` ("Deepen Alexa schedule, defer,
  and caregiver utterances") are in-repo sim deepen, not console publish.

**Onboarding (zero to hello world)**

In-repo path (repo-proven): `pip install -e ".[dev]"` then
`./scripts/amazon_demo_path.sh`. First useful output is the Fire TV page plus
`ALEXA+ agent initialized (MCP Streamable HTTP)` on stdout.

Live Alexa+ path (my setup):

- Amazon developer console signup took about 10 minutes.
- I use Echo at home. I switched from Google Home because Google Home
  stopped supporting BluOS devices.
- I did not certify or publish a skill.

**Would we build with it again, and why**

Yes for the **self-hosted MCP + documented simulator** shape. It is what the
PRD allowed, it is what CI runs, and it is the only Alexa+ path that exists
in this repo. We would not claim a live Alexa+ Agent Skill from this tree.

I would build on Alexa+ again. It seems like a capable platform and more
friendly than Google Home.

---

### 2. Alexa mobile notify / inform card / caregiver skill session

**What we used it for**

Caregiver pager. Fire TV is the living-room timeline, not the pager
(Fire TV HTML comment: "Alexa mobile is the caregiver pager").

- MCP `notify_caretaker` docstring: "Notify the caregiver on Alexa mobile
  (inform card). Simulated, no real push." Returns
  `channels: ["alexa_mobile"]`, `simulated: true`, plus `inform_card` and
  `apl_card` (`src/care_ladder/mcp_server/server.py`).
- Plan lock: `configs/amazon_demo_home.yaml` `notify_caretaker.params.channels: [alexa_mobile]`.
- Shared FSM `src/care_ladder/channels/care_conversation.py`:
  `idle` to `speaker_window` to `family_paged` (then pressure / calling /
  deepen). `inform_card()` is blurred still + countdown + three actions
  (`im_on_it`, `call_mom_now`, `pass_to_next`).
- Ack / outcome / defer: MCP `caregiver_ack`, `caregiver_outcome`,
  `defer_escalation`. Classifier
  `src/care_ladder/channels/caregiver_intent.py`. Audit events stamp
  `channel: "alexa_mobile"`.
- Tests: `tests/test_alexa_mobile_ack.py`, `tests/test_caregiver_intent.py`,
  `tests/test_care_conversation_fsm.py`,
  `tests/test_alexa_schedule_defer_mcp.py`.
- Commits: `4e3e0e9` / `3653b8d` "Alexa mobile caregiver notify, ack, and
  outcome"; `f0dd0de` deepen.

**What worked well**

- The pager contract is explicit in tests: notify payload is the inform
  card; `fire_tv` is not in notify channels
  (`test_notify_payload_is_alexa_mobile_inform_card`).
- First ack wins and stops `request_call` (`escalation_stopped`). Outcome
  is required to close with documentation. Fail-closed: groan / garbage is
  `unclear`, never an invented ack.
- Spoken confirms in `spoken_confirmation()` are written without em dashes
  (comment in `caregiver_intent.py`: "Spoken Alexa confirm. No em dashes.").
- Defer to another contact is a **simulated Alexa mobile page**, not PSTN
  (`care_conversation.py` `notify_x.simulated: True`,
  `channel: "alexa_mobile"`). Plan comment: "Call someone else" means page,
  not dial.

**What needs work**

- **In-repo notify is still simulated.** Every notify/ack path in this tree
  sets `simulated: true`. There is no Alexa Skills Kit package, no
  interaction model, no SMAPI call, and no push campaign in the repo.
- `SpeakerSimulator` and MCP `request_call` (`note: "demo_stub_no_real_dial"`)
  stand in for the phone hop. Reserved fiction only: `+12125550176`
  (`(555) 010-2276`) in `configs/amazon_demo_home.yaml`.
- The Fire TV "Family informed on Alexa mobile" line is copy that mirrors
  the audit trail (`tests/test_firetv_app.py`). That line is not itself
  the live push.

**Onboarding (zero to hello world)**

In-repo: after the API is up, `python -m care_ladder.mcp_server.alexa_sim --url http://127.0.0.1:8010 --caregiver-answer "I'm on it"`
exercises notify then ack on the same incident.

I did not get a real Alexa mobile notification on my phone before this
project. During this project a real Alexa mobile notification did reach
my phone.

**Would we build with it again, and why**

Yes as the **product model** (pager on the phone, TV as timeline). The FSM
and inform-card slots are reusable. I did get a real Alexa mobile
notification on my phone during this project. The in-repo `notify_caretaker`
path is still a simulator (`simulated: true`). We would not treat the
repo stub as the production pager.

---

### 3. Alexa Presentation Language (APL) 2024.3

**What we used it for**

In-process notify card document, additive to `inform_card`. Not a second
skill package.

- `src/care_ladder/channels/apl_notify.py`: `APL_DOCUMENT` with
  `"type": "APL"`, `"version": "2024.3"`, `mainTemplate` (Image + Text
  slots for thumbnail, household, time since cue, cue text).
- `apl_notify_card(...)` builds datasources under key `notify` plus voice
  actions (`false_alarm`, `on_my_way`, `need_second_look`, `snooze_alert`)
  and the three legacy inform actions.
- Wired on `family_paged` via `CareConversation._refresh_apl` and on MCP
  `notify_caretaker` as `apl_card`.
- Plan: `docs/plans/alexa-schedule-defer.md` section 2 ("APL is a JSON
  document + datasource built in-process (no live Alexa console publish
  required)").
- Tests: `tests/test_apl_notify.py` (slots, voice ids, no em dash in
  labels, `apl.type == "APL"`).
- Commit: `f0dd0de` / `9845e8b` "deepen Alexa caregiver intents, defer,
  and schedule pin".

**What worked well**

- The document is small and testable. We could assert thumbnail, household
  label, `timeSinceCue` ("just now" vs "4 min ago"), and action ids without
  an APL runtime.
- Datasource key `notify` matches the `${payload.notify.*}` bindings in
  `APL_DOCUMENT`.
- Labels stay ASCII-hyphen clean (`test_apl_card_slots_and_voice_actions`).

**What needs work**

- **Never rendered on a device.** The in-repo path does not send an
  `Alexa.Presentation.APL` directive. I previewed APL in the developer
  console, not on Echo Show or Fire TV. The JSON in this tree is stored
  on the incident and returned to the MCP client.
- Thumbnail is a string ref (`blurred:{incident_id}` or
  `last-frame-placeholder`), not a hosted image URL a real APL `Image`
  component could fetch.
- Fire TV may mirror fields; it does not execute APL
  (`docs/plans/alexa-schedule-defer.md`: "Fire TV may mirror fields; it is
  not the pager").

**Onboarding (zero to hello world)**

In-repo: `from care_ladder.channels.apl_notify import apl_notify_card` and
call it (see `tests/test_apl_notify.py`). Zero Amazon console steps.

I previewed APL in the developer console, not on a device.

**Would we build with it again, and why**

Yes as a **schema for the notify card**, because it gave us a named Amazon
document type without blocking the demo on console publish. I previewed
APL in the developer console, not on a device. We would not call the
in-repo JSON an on-device APL experience.

---

### 4. Alexa Proactive Events API

**What we used it for**

Optional awareness chime only. Not the pager.

- Stub: `src/care_ladder/channels/proactive_events.py`.
  `send_awareness_chime(household_id, incident_id)` always returns
  `simulated: true` and
  `note: "local sim only; schema-locked; not a rich notify"`.
- Flag `CARE_LADDER_PROACTIVE` defaults off (`"0"`). When off, the stub
  also returns `skipped: true`, `reason: "flag_off"`.
- Hook: `CareConversation.expire_to_family_paged` appends a
  `proactive_chime` audit event only if the flag is on.
- Honesty doc: `docs/proactive-events-honesty.md`. Friction log section
  "Alexa Proactive Events (stub, flag off) - 2026-09-29".
- Tests: `tests/test_proactive_events.py`.
- Commit: `b7c28d7` "A4: Proactive Events awareness-chime stub".

**What worked well**

- The flag-off default keeps demo and pytest green without claiming a push
  button arrived via Proactive Events (`docs/proactive-events-honesty.md`).
- The stub sits on the `family_paged` hop without changing MCP notify/ack.
- Schema-lock is written into the return note and the honesty doc, so
  oversell is a documentation failure, not a silent one.

**What needs work**

- **Local sim only.** Friction log: "Account/API access for a real
  proactive campaign was not available." No LWA token, no catalog
  (`AMAZON.MessageAlert.Activated` or similar), no
  `api.amazonalexa.com` call.
- Schema-locked catalogs cannot carry the three caregiver actions. Those
  stay in the skill-session inform card. High severity if a demo claimed
  otherwise (friction log).
- I did not apply for a live Proactive Events catalog, as far as I recall.

**Onboarding (zero to hello world)**

In-repo: `CARE_LADDER_PROACTIVE=1` then expire a conversation to
`family_paged` (`tests/test_proactive_events.py::test_family_paged_chimes_when_flag_on`).
That still returns `simulated: true`.

Live PE hello world: not started in this repo.

**Would we build with it again, and why**

Only as a **thin awareness chime**, never as the caregiver pager. The stub
plus honesty doc was the right call for this window. We would not block a
hackathon demo on a live PE catalog again.

---

### 5. Fire TV (Silk / 10-foot HTML web app)

**What we used it for**

Supporting living-room timeline at `/firetv/`.

- App: `src/care_ladder/api/static/firetv/index.html` (Ambient Hearth).
  Served by FastAPI `StaticFiles` mount in `src/care_ladder/api/app.py`.
- Data-driven from `GET /incidents` and `GET /plan` (unauthenticated reads
  so the TV can poll). Demo console posts fixtures to `/demo/run`.
- D-pad: arrow-key spatial focus (`spatialMove` / `.focused` ring).
- Silhouette-only: no live `<video>`; frames go through blur/silhouette
  before persist (`README.md`, Fire TV HTML comment).
- Silk-specific CSS already in tree: self-hosted woff2 (no Google runtime);
  `[hidden] { display: none !important; }` because author `display:flex`
  beats the `hidden` attribute on Silk (HTML comment + friction log).
- Tests: `tests/test_firetv_app.py`.
- Commits: `e32ac4f` / `ea2c2ae` "Fire TV supporting timeline";
  `4f650e0` "MCP tool visibility on Fire TV"; `606da4e` friction-log
  fill for Fire TV and CloudFront.

**What worked well**

- One store: MCP writes, TV polls. `scripts/amazon_demo_path.sh` proves
  soft-OK resolves on the same incident the TV sees; needs-human leaves
  notify up for Acknowledge.
- 10-foot layout (hero, rail, footer, demo console) is usable in a
  1280x720 Chromium window for standby and occlusion
  (`docs/friction-log.md` 2026-09-29).
- Vendored woff2 avoided a Silk / runtime font fetch.
- Emergency hold-to-review is hard-locked in this build (pointer hold
  explains; no call).

**What needs work**

- **No Fire TV stick and no official simulator in the environments that
  wrote the friction log.** `docs/demo/README.md`: "Browser at 1280x720
  because a Fire TV stick was not available in this environment."
  `scripts/amazon_demo_path.sh` still prints "prefer a Fire TV stick
  (Silk) or the official simulator."
- Needs-human / notify overflows a 720p window (document ~787px; footer
  `visible: false` in the 2026-09-29 Chromium pass).
- First keypress is required (load focus is `BODY`). Hero / presence take
  programmatic focus with `outline: none` and do not get `.focused`, so
  they show no ring. Spatial heuristic can skip left-to-right (ArrowDown
  from the hero landed on Request call, not Acknowledge).
- Enter on the focused hero is a no-op. Emergency Hold 3s is `pointerdown`
  only; a D-pad Select never starts the hold
  (`firetv/index.html` `pointerdown` listener).
- Shared CloudFront host 404s `/firetv/` (see CloudFront section). Video
  path is local uvicorn.

**Onboarding (zero to hello world)**

In-repo: start the API, open `http://127.0.0.1:8010/firetv/`. Demo console
is bottom right. No Fire OS SDK, no Vega OS package, no Web App Tester
project file.

My device notes:

- I do not have a real Fire TV stick.
- I did not use the official Amazon Fire TV / Web App Tester, as far as
  I recall.

**Would we build with it again, and why**

Yes as a **supporting 10-foot HTML surface**. Serving static HTML from the
same FastAPI app as `/mcp` kept the TV on the live incident without a
second backend. We would budget real-stick time earlier: 720p notify
overflow and pointer-only hold are the kind of bugs Silk would have
caught on day one.

---

### 6. Amazon CloudFront and Application Load Balancer

**What we used it for**

Shared HTTPS demo host from the **opencv-care-ladder** stack, not a
deploy from this repo.

- URL in README and `infra/README.md`:
  `https://d2u7pls4da2poz.cloudfront.net/` in front of ALB
  `care-ladder-demo-2017970097.us-east-1.elb.amazonaws.com`
  (AWS account `367597235216`, `us-east-1`).
- This repo's CI is test-only (`.github/workflows/ci.yml`: "Do not
  deploy"). `infra/README.md`: "care-ladder-amazon CI does not deploy."
- 2026-09-29 probes in `docs/friction-log.md`: `/ui/` and `/incidents`
  200 (OpenCV console); `openapi.json` has 17 paths and **no `/mcp` or
  `/firetv/`**; `GET/POST /mcp` and `/firetv/` are FastAPI 404
  (`x-cache: Error from cloudfront`). Same 404 on the ALB origin.
- `scripts/infra.sh` can create a CloudFront distribution in front of
  the ALB (optional replay, not run by CI).

**What worked well**

- CloudFront as a stable OpenCV judge URL is documented and left alone
  so that track does not break.
- Local MCP initialize against `http://127.0.0.1:8010/mcp/` returned
  200 SSE, protocol `2025-11-25` (friction log table). That is the
  path the tape uses.

**What needs work**

- A judge who treats the live HTTPS URL as the Amazon demo gets 404 on
  `/mcp` and `/firetv/`. Severity: high for that mistake, low for the
  planned tape (already scripted local).
- Host-header / DNS-rebinding 421 was **not** observed on prod because
  prod never reaches the MCP app. The MCP SDK default still matters
  the day this is deployed behind `Host: *.cloudfront.net`
  (`CARE_LADDER_MCP_HOSTS` allowlist in `src/care_ladder/api/app.py`).
- `POST …/mcp` with `Host: 127.0.0.1` via CloudFront returned 403 HTML
  from CloudFront, not MCP 421 (friction log).

**Onboarding (zero to hello world)**

In-repo: none required. Local demo needs no AWS credentials
(`./scripts/run_demo.sh`).

My first AWS deploy (ECS / CloudFront) was easy. This repo's CI still
does not provision that stack.

**Would we build with it again, and why**

Yes as HTTPS in front of a single ALB/Fargate service, with the caveat
that **a new route is not live until you redeploy the task**. We would
give the Amazon filing its own hostname instead of sharing the OpenCV
CloudFront.

---

### 7. Amazon ECS on Fargate, Amazon ECR, and AWS CLI

**What we used it for**

Container contract and optional replay of the shared demo service.

- Root `Dockerfile` runs `uvicorn care_ladder.api.app:app`.
- `infra/task-definition.json`: Fargate, 0.5 vCPU / 1 GB, image
  `367597235216.dkr.ecr.us-east-1.amazonaws.com/care-ladder:demo`,
  env `CARE_LADDER_STORE=dynamodb`, `CLIP_BUCKET`, `EVENT_BUS_NAME`.
- `infra/ecs-task-outline.md` and `scripts/infra.sh` (cluster, service,
  task definition, ECR implied by the image URI).
- README: "Optional AWS replay"; "Local run needs no AWS credentials."

**What worked well**

- The image contract is boring and local: `docker build` then uvicorn
  on 8000 (`infra/README.md`). Demo fixtures do not need a live camera.
- Task definition is checked in; judges can read CPU/memory/IAM without
  a live console.

**What needs work**

- This repo never auto-deploys. The live service is the pre-Amazon
  OpenCV image (no `/mcp`, no `/firetv/`).
- `infra/README.md` still describes EventBridge / S3 as a sketch in
  places, while `scripts/infra.sh` and `src/care_ladder/cloud/sinks.py`
  are env-gated code. Easy to over-claim "the cue bus is live."
- Task role in `task-definition.json` is the execution role ARN reused
  as `taskRoleArn`. Least-privilege is documented as the intent
  (`ecs-task-outline.md`); that file is the outline, not proof the live
  role matches.

**Onboarding (zero to hello world)**

`docker build -t care-ladder:demo .` then
`docker run --rm -p 8000:8000`. AWS CLI hello world is `scripts/infra.sh`
when credentials exist. No credentials are committed.

**Would we build with it again, and why**

Yes for a one-task demo. We would split Amazon and OpenCV services so
CI on this repo cannot 404 a judge, and would not reuse the execution
role as the task role in a real lock-down.

---

### 8. Amazon DynamoDB (AWS SDK for Python, boto3)

**What we used it for**

Optional durable audit store.

- `src/care_ladder/audit/dynamo_store.py`: table
  `CARE_LADDER_DDB_TABLE` (default `care-ladder-incidents`), PK
  `incident_id`. Env gate: `CARE_LADDER_STORE=dynamodb`.
- API factory in `src/care_ladder/api/app.py`: dynamodb when that env is
  set and boto3 works, else in-memory. Failure prints a WARNING and
  falls back to memory.
- `scripts/infra.sh` `aws dynamodb create-table` for the same table name.
- Local/tests default to memory (`dynamo_store.py` module docstring).

**What worked well**

- Env gate keeps pytest hermetic. No local DynamoDB required.
- Privacy rule is the same as memory: only blur/silhouette PNG bytes
  are stored (`_frames_png_b64`).
- boto3 is a declared dependency (`pyproject.toml`).

**What needs work**

- Resource-client typing: "boto3 resource clients reject floats;
  convert to Decimal recursively" and a comment that a manual
  AttributeValue marshaller wrapped the key as `{"S": ...}` which boto3
  re-wrapped as a Map and broke the schema (`dynamo_store.py`). That is
  a real SDK footgun we hit in code comments.
- `put_item` failure is best-effort: incident stays in memory, WARNING
  on stdout. Easy to miss in a Fargate log if persistence is the point.
- This Amazon repo's CI does not assert a live table.

**Onboarding (zero to hello world)**

Code path: set `CARE_LADDER_STORE=dynamodb` plus standard AWS credentials
and region. Table is created on demand (`_ensure_table`). We have no
in-repo log of a first successful live put from this fork.

**Would we build with it again, and why**

Yes as an optional store behind a flag. We would keep the memory fallback
for demos and add one live put/get smoke test before calling it
production.

---

### 9. Amazon S3 and Amazon EventBridge (boto3)

**What we used it for**

Optional clip sink and cue bus.

- `src/care_ladder/cloud/sinks.py`: `CLIP_BUCKET` / `EVENT_BUS_NAME`.
  Both "silently no-op when unconfigured."
- S3: `put_object` PNG frames only when `privacy` is `blur` or
  `silhouette`. Missing tag refuses the upload (logged warning, `[]`).
- EventBridge: `put_events` `Source=care.ladder`,
  `DetailType=CareLadderCue` on bus `EVENT_BUS_NAME`.
- Task env in `infra/task-definition.json`:
  `CLIP_BUCKET=care-ladder-demo-367597235216`,
  `EVENT_BUS_NAME=care-ladder`.
- `scripts/infra.sh` creates the bucket (public access blocked) and an
  EventBridge archive note.

**What worked well**

- Local/tests stay hermetic because empty env means no client.
- The no-raw-bytes rule is enforced at the sink, not only at attach
  time (`upload_clip_frames`).

**What needs work**

- Failures are `logger.warning` and a boolean / empty list. No retry.
- `infra/README.md` still calls EventBridge a sketch in the "Why this
  satisfies meaningful AWS" table. Treat live bus claims as
  opencv-stack history, not as something this repo's CI proves.
- Secrets Manager is mentioned as a future for live dial credentials
  (`infra/README.md`) and is **not** implemented.

**Onboarding (zero to hello world)**

Set `CLIP_BUCKET` and/or `EVENT_BUS_NAME` with AWS credentials. Without
those env vars the class constructs and `enabled` is false. No in-repo
proof of a first live `PutObject` / `PutEvents` from this fork.

**Would we build with it again, and why**

Yes as env-gated sinks. The privacy refuse-without-tag behavior is the
part we would keep even if the bus stayed off for a demo.

---

## Amazon tools we did not use

Named so the Ring / Bee / Alexa+ / Fire TV teams are not left guessing.

| Tool | Evidence we skipped it |
| --- | --- |
| **Ring** | README origins: "No Bee / Ring." PRD lock: "Ring: Out for this filing." |
| **Bee** | Same README line. PRD: "Bee: Out for this hack (Apple Watch alone is not Bee live data)." |
| **Amazon Bedrock foundation models** | Not used. No Bedrock model id in this repo. |
| **AgentCore Gateway** | In-repo config and local `/mcp` smoke (`infra/agentcore-gateway.md`). Live `CreateGateway` stays off unless `CARE_LADDER_AGENTCORE_DEPLOY=1`. |
| **Classic Alexa Skills Kit (ASK) skill** | PRD: "Classic ASK-only skill: Not the Stage 1 gate." No `skill.json` / interaction model in tree. |
| **Alexa+ Category SDK / MCP Toolkit / CLI / Web Simulator** | PRD non-goals: "unavailable to participants." |
| **Amazon Fire TV / Web App Tester official simulator** | Friction log 2026-09-29: not in that environment. Chromium 1280x720 fallback. |
| **Alexa Voice Service / published custom skill on a device** | `SpeakerSimulator` only. |

---

## Other tools

Brief. These are not Amazon product-team surfaces.

### MCP Python SDK v2.2.0 and Streamable HTTP (2025-11-25+)

Used as the Alexa+ agent transport (`mcp` in `pyproject.toml`;
`MCPServer` in `server.py`; `streamable_http_client` / `ClientSession`
in `alexa_sim.py`). Worked: tool registration from typed functions;
stateless Streamable HTTP; client drove the server over real HTTP once
mounted. Fought back (all in `docs/friction-log.md`): v1 `FastMCP`
import is a hard miss; ASGI mount lifespan; lazy `session_manager`;
DNS-rebinding 421 for non-localhost Host; dual
`structuredContent` vs JSON text. Verdict in the friction log: usable;
rough edges are the embed-in-a-larger-app seam.

### Cartesia Sonic TTS

Demo remux VO only. `scripts/generate_amazon_demo_vo.sh` needs
`CARTESIA_API_KEY`; refuses to invent wavs if the key is missing.
Default voice id `8499aae3-022c-4d55-8283-0c2e8adbefb4` (public voice
id, not a secret). Intermediates `docs/demo/vo/` are gitignored.
`docs/demo/README.md`: shipped mp4 was remuxed with spoken VO.

Cartesia signup was smooth.

### Kaggle API (fall-frame classifier, optional)

`docs/fall-cv-training.md` + `src/care_ladder/vision/fall_train.py`.
Slug `elwalyahmad/fall-detection`. Credentials
`KAGGLE_USERNAME` / `KAGGLE_KEY` (or `~/.kaggle/kaggle.json`) are **not**
committed. `data/kaggle/` and `models/*.npz` are gitignored.
`docs/demo/README.md`: "Training did not run. Kaggle credentials were
missing." Tests cover parse/train/load without the zip
(`tests/test_fall_train.py`).

Kaggle token setup was smooth.

### OpenCV

Vision trigger vendored from `pamu512/opencv-care-ladder`. Person/pose
ONNX chain, fixtures, privacy blur/silhouette. Alexa+ fixtures do not
need ONNX (`README.md`). Not an Amazon tool.

---

## Built With list suggestion

Paste on Devpost. Only claim what this repo runs or clearly stubs.

**Amazon**

- Alexa+ (self-hosted MCP agent path; in-repo `alexa_sim` client)
- Alexa mobile notify / inform card (simulated skill session)
- Alexa Presentation Language 2024.3 (in-process document, not device-rendered)
- Alexa Proactive Events (awareness-chime stub, flag off)
- Fire TV (10-foot HTML at `/firetv/`; Chromium 1280x720 fallback)
- Amazon CloudFront + Application Load Balancer (shared OpenCV host; `/mcp` and `/firetv/` 404 there)
- Amazon ECS on Fargate + Amazon ECR (task definition / Dockerfile; this CI does not deploy)
- Amazon DynamoDB (optional `CARE_LADDER_STORE=dynamodb`)
- Amazon S3 + Amazon EventBridge (optional env-gated sinks)
- AWS SDK for Python (boto3)

**Other**

- MCP Python SDK (Streamable HTTP, spec 2025-11-25+)
- FastAPI / uvicorn
- OpenCV
- Cartesia Sonic (demo VO)
- Kaggle (optional fall-classifier download; not run in the shipped tape)
- pytest
