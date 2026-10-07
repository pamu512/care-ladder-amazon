# Care Ladder - AWS deployment sketch

**care-ladder-amazon CI does not deploy.** CloudFront `https://d2u7pls4da2poz.cloudfront.net/` is the **shared demo host from the opencv-care-ladder stack**. Leave it alone until a dedicated Amazon hostname is approved.

**Status:** LIVE (opencv stack). Deployed on AWS (account 367597235216, us-east-1): ECS/Fargate service `care-ladder-demo` behind an internet-facing ALB (`care-ladder-demo-2017970097.us-east-1.elb.amazonaws.com`) with CloudFront HTTPS in front (`https://d2u7pls4da2poz.cloudfront.net`). Local FastAPI (`./scripts/run_demo.sh` → `care_ladder.api.app:app`) remains the fallback judge demo.

Phase A in this repo is not deployed by CI. SageMaker cue scoring is behind `CARE_LADDER_SAGEMAKER_ENDPOINT`, with `models/fall_classifier.npz` as the fallback ([`sagemaker/README.md`](sagemaker/README.md)). AgentCore Gateway is an AWS front door for the same `/mcp` tools ([`agentcore-gateway.md`](agentcore-gateway.md)). Neither replaces the Alexa+ path. The shared host above still 404s `/mcp` (see `docs/friction-log.md`). Do not point the gateway at it until a care-ladder task serves that route.

Provisioning commands used (reproducible): see `scripts/infra.sh` (VPC, ECR, ECS cluster/service, ALB, CloudFront, DynamoDB table, task role).

The architecture matches the design spec and the separately submitted OpenCV/AWS compute grant proposal: **S3 (privacy-filtered clips) → ECS/Fargate (OpenCV + FastAPI) → EventBridge cue bus → orchestrator audit trail**.

## Why this satisfies “meaningful AWS”

| Component | Role in Care Ladder | Evidence for judges |
| --- | --- | --- |
| **S3** | Durable store for **pre-event clips** after blur/silhouette | Only privacy-processed frames leave the device path (see below) |
| **ECS/Fargate** | Runs the containerized API + OpenCV worker | Task definition outline in [`ecs-task-outline.md`](ecs-task-outline.md); root [`Dockerfile`](../Dockerfile) builds a runnable image |
| **EventBridge** | Cue bus: `CueEvent` → care-ladder orchestrator | Decouples vision detect from rung tools (`reperceive` / `speaker_prompt` / `dial_contact` / …) |

Optional later (grant path, not required for this sketch): DynamoDB audit store, SQS buffering, Step Functions for long `wait` rungs, Secrets Manager for live dial credentials, CloudFront in front of the API.

## Privacy: S3 clip upload (blurred / silhouette only)

**Rule:** never upload raw identifiable frames to S3 (or any cloud object store).

1. Edge or worker applies `care_ladder.privacy.blur_faces` and/or `to_silhouette` to each frame in the rolling pre-event buffer (`clip_buffer`).
2. Encode a short clip (e.g. 15–60s) from **only** those processed frames.
3. `PutObject` to a private bucket, e.g. `s3://care-ladder-<env>/incidents/<incident_id>/pre_event.mp4`.
4. Bucket defaults: block public access, SSE-S3 or SSE-KMS, lifecycle expire (e.g. 7–30 days), least-privilege task role (`s3:PutObject` / `GetObject` on that prefix only).

Object metadata should record `privacy=blur|silhouette` and incident id. Caregiver timeline links to the object key; raw camera bytes stay off-cloud.

## ECS / Fargate service (sketch)

- **Image:** build from repo root `Dockerfile` → runs `uvicorn care_ladder.api.app:app --host 0.0.0.0 --port 8000`.
- **Launch type:** Fargate (Graviton/`linux/arm64` preferred when the grant is available; `linux/amd64` fine for local `docker build`).
- **Service:** desired count 1 for demo; public or private ALB → target group → task port 8000.
- **Config:** mount or bake `configs/demo_home.yaml`; env for bucket name / EventBridge bus name when wired.
- **Safety rails (unchanged in cloud):**
  - Demo contacts remain **NANP reserved** `NPA-555-01XX` only.
  - Emergency rung **fail-closed** (`enabled: false` in plan; code never places real 911).
  - Stub dialer / speaker simulator unless Secrets Manager + explicit live grant are configured (out of scope for this outline).

See [`ecs-task-outline.md`](ecs-task-outline.md) for CPU/memory, ports, IAM, and health check notes.

## EventBridge cue bus (sketch)

```
OpenCV CueDetector (in worker / same task)
    → PutEvents DetailType=CareLadderCue
    → EventBridge bus `care-ladder`
    → rule target: API/orchestrator (HTTP API destination or SQS → worker)
    → run_incident(...) appends audit events (Agentic Vision trace)
```

**Event detail (illustrative JSON):**

```json
{
  "household_id": "demo_home",
  "kind": "no_movement",
  "confidence": 0.9,
  "zone_id": "living_room",
  "clip_s3_uri": "s3://care-ladder-demo/incidents/…/pre_event.mp4"
}
```

`kind` values align with local models: `no_movement` | `no_visibility` | `distress_heuristic`. The orchestrator must still log jumps and tool results so the incident timeline shows cue → rung → outcome.

## Local vs AWS demo path

| Path | When to use |
| --- | --- |
| **Local** `scripts/run_demo.sh` | Primary judge screen-share; no AWS credentials required |
| **Container** `docker build -t care-ladder .` then run uvicorn in container | Proves the image used by ECS is runnable |
| **AWS** (this outline) | Meaningful-component story for OpenCV/AWS; deploy only when account + grant credentials exist |

Do **not** invent fake deployed URLs. If nothing is deployed, say so and demo locally.

## Build the API image (no live deploy required)

```bash
# from repo root
docker build -t care-ladder:demo .

docker run --rm -p 8000:8000 care-ladder:demo
# then: POST /demo/run  {"fixture":"no_movement_silence"}
#       GET  /incidents/{id}
```

If Docker is unavailable in the build environment, the Dockerfile is still the contract for ECS; validate later on a machine with Docker.

## Related docs

- Design: `docs/superpowers/specs/2026-09-11-agentic-senior-care-ladder-design.md` §8 Architecture (AWS)
- Grant proposal (submitted separately): `grant/Care-Ladder-OpenCV-AWS-Grant-Proposal.pdf`
- Known failure modes and limitations: `docs/failure-modes.md`
- Local judge runbook: root `README.md`

## Cost of the live demo stack

Single-household demo footprint, us-east-1 (Sept 2026 prices, approx.):
Fargate 0.5 vCPU / 1 GB desired=1 ~ $16.60/mo + ALB ~ $19/mo + CloudFront
(negligible at demo traffic) + DynamoDB on-demand (tens of writes/day, < $1) +
S3 silhouette PNGs (< $0.10) + ECR storage (~ $0.50). **Total ~ $37/mo**,
i.e. the whole hosted demo costs about the same as ONE Aloe Care seat
($39.99/mo + $199 hardware) - and it scales per additional household by
camera, not by seat. Grants/credits offset this during the hackathon.
