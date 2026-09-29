# ECS / Fargate task outline (Care Ladder)

Outline only — not executable CDK/Terraform. Use this when creating a task definition / service in the AWS console or IaC later. **No live cluster is assumed.**

## Container image

| Field | Value |
| --- | --- |
| Build context | Repository root |
| Dockerfile | `Dockerfile` |
| Entrypoint/CMD | `uvicorn care_ladder.api.app:app --host 0.0.0.0 --port 8000` |
| Container name | `care-ladder-api` |
| Essential | `true` |

Suggested image URI after push (placeholder — replace with your account/region/repo):

`<account>.dkr.ecr.<region>.amazonaws.com/care-ladder:demo`

## Task size (demo)

| Field | Suggested demo value | Notes |
| --- | --- | --- |
| Launch type | `FARGATE` | |
| Platform | `LINUX` | Prefer `ARM64` (Graviton) when grant AMI/image supports it; else `X86_64` |
| CPU | `512` (0.5 vCPU) | Raise to `1024` if OpenCV worker shares the task |
| Memory | `1024` MiB | OpenCV + uvicorn; bump if clip encode runs in-process |
| Network mode | `awsvpc` | Required for Fargate |
| Public IP | Optional for single-task demo | Prefer private subnets + ALB for anything beyond a hackathon spike |

## Port mappings

| Container port | Protocol | Host / ALB |
| --- | --- | --- |
| `8000` | TCP | Target group health check `GET /incidents` or `/docs` |

## Environment variables (sketch)

| Name | Example | Purpose |
| --- | --- | --- |
| `CARE_LADDER_ENV` | `demo` | Label logs / metrics |
| `CLIP_BUCKET` | `care-ladder-demo` | S3 bucket for **blurred/silhouette** clips only |
| `EVENT_BUS_NAME` | `care-ladder` | EventBridge bus for cue events |
| `AWS_REGION` | `us-east-1` | SDK default (task role, not static keys) |

Do **not** put dial credentials or real phone numbers in env vars. Demo plan keeps reserved `+1212555010x` fiction and emergency **fail-closed**.

## IAM task role (least privilege sketch)

Allow:

- `s3:PutObject`, `s3:GetObject` on `arn:aws:s3:::care-ladder-demo/incidents/*`
- `events:PutEvents` on the `care-ladder` event bus ARN

Deny / omit:

- Broad `s3:*` on `*`
- Any permission that implies uploading **raw** camera archives (operational policy: only privacy-processed objects; enforce in app code before `PutObject`)

Execution role: standard ECS task execution (ECR pull, CloudWatch Logs).

## CloudWatch Logs

- Log group: `/ecs/care-ladder-demo`
- Stream prefix: `api`
- Retain 14–30 days for hackathon

## Health check

```text
CMD-SHELL, curl -f http://localhost:8000/incidents || exit 1
```

(Image may need `curl` installed, or use a Python one-liner / ALB-only checks.)

## Service sketch

1. Create ECR repository `care-ladder`; `docker push` the image built from root `Dockerfile`.
2. Create cluster `care-ladder-demo` (Fargate).
3. Register task definition from the fields above.
4. Create service desired count `1`, attach ALB listener `:80` → target group `:8000`.
5. (Optional) EventBridge rule: source `care.ladder`, detail-type `CareLadderCue` → API Destination `POST https://<alb>/…` or SQS.

## Wiring OpenCV worker vs API

**Minimal (one task):** same container runs FastAPI; demo fixture path does not need a live camera. Cue bus can be simulated by `POST /demo/run`.

**Split (grant path):** second container/task runs `CueDetector` over frames from S3, emits EventBridge events; API/orchestrator consumes and writes audit timeline (DynamoDB later).

## Safety checklist before any real deploy

- [ ] Bucket public access **blocked**
- [ ] Only blurred/silhouette clips uploaded
- [ ] Plan YAML emergency `enabled: false` (fail-closed)
- [ ] Contacts are reserved fiction or Secrets Manager–gated live grant — never real 911 in demo
- [ ] No fabricated “production URL” in README or submission unless the service is actually up
