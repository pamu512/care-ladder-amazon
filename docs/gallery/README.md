# Devpost gallery assets (Care Ladder)

PNGs for Amazon Build Ship Shape Devpost upload. Silhouette-only / wellness ladder tone. Not a medical device. No emergency auto-dial.

## Included

| File | Source / notes |
| --- | --- |
| `architecture.png` | Rendered diagram: Alexa+ agent -> self-hosted `/mcp` (Streamable HTTP) -> Care Ladder FSM/orchestrator -> notify + APL + Fire TV. AWS in-repo: ECR, ECS Fargate, ALB, CloudFront, DynamoDB, S3, EventBridge. Phase A SageMaker cue + AgentCore Gateway labeled dry-run / flag-gated. |
| `decision-flowchart.png` | Rendered decision flow: OpenCV/SageMaker cue -> Alexa voice check-in (2 attempts) -> rung timers -> defer/silence OR escalate. Parallel person check-in + caregiver "call X instead". Family ladder Me -> Wife -> Sister -> Neighbor with reason. |
| `firetv-moms-home-allclear.png` | Copied from `docs/assets/firetv-allclear-1280.png` |
| `firetv-notify.png` | Copied from `docs/assets/firetv-notify-1280.png` |
| `firetv-voice-checkin.png` | Copied from `docs/superpowers/specs/fire-tv-dashboard/screenshots/rung2-voice-checkin-a.png` |
| `firetv-camera-covered-notify.png` | Copied from `docs/superpowers/specs/fire-tv-dashboard/screenshots/rung4-notify-camera-covered.png` |
| `demo-contact-sheet.png` | Copied from `docs/demo/care-ladder-amazon-demo-contact-sheet.png` |

## Still missing (not inventing screenshots)

These product surfaces exist in code/tests but have **no PNG assets in-repo** to copy:

1. **APL alert** (Echo Show APL notify surface)
2. **Alexa mobile notify** (caregiver phone notification UI)
3. **Family ladder view** (roster Me -> Wife -> Sister -> Neighbor UI)

Do not fabricate those screenshots for Devpost. Fire TV assets above are the only product screenshots sourced here.
