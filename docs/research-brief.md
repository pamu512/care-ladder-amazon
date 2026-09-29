# Care Ladder - Research Brief: Why This Design

Substantiates the product and engineering decisions behind Care Ladder with
cited public-health data and verified competitor behavior, then states our own
limitations honestly. Written for judges reading the repo; every outside claim
carries a numbered citation resolved at the end.

## 1. The problem is large, measured, and getting worse

Falls are the leading cause of injury for adults 65+, and over 14 million -
1 in 4 older adults - report falling every year.[1] Falls are also the leading
cause of injury-related *death* in this group, and the age-adjusted death rate
rose 21% between 2018 (64.7 per 100,000) and 2024 (78.4 per 100,000).[1]
The people most exposed live alone: the dangerous fall is the one nobody
witnesses.[1] That is the specific gap Care Ladder targets - not "detect falls"
in the abstract, but *decide what to do, transparently, when a person living
alone may have stopped being okay*.

## 2. What the market does today (verified, not strawmanned)

| Product | Verified approach | What it gets right |
| --- | --- | --- |
| **AltumView Sentinare** | Edge sensor; "an onboard AI chip converts people into stick figures before transmission"[3]; alerts for falls, bed leaving, wandering, overstays, absences[3] | Privacy-first vision sells in bedrooms/bathrooms; cue breadth beyond falls |
| **Aloe Care Health** | Voice-activated Smart Hub + Care Button wired to a "24/7 Emergency Response Center"[4]; Essentials plan $39.99/mo plus $199.99 hardware[4] | Voice-first for seniors; human escalation backbone |
| **Nobi** | Smart-lamp fall detection for senior-living operators: "captures falls within seconds… alerting caregivers immediately"[6], plus preventive lighting and post-fall insights[6] | Speaks/illuminates before escalating; care-home workflow |
| **Alexa Together** | Retired by Amazon in May 2025 - "a lot of families were left without the quiet daily reassurance it provided"[8] | Proof of demand for passive everyday awareness - and of subscription fragility |
| **Kami Home** | Fall detection as a cloud add-on to consumer security cameras.[7] | Falls on mass-market hardware |

## 3. The gap none of them fill

Across these products the escalation policy is **fixed by the vendor**: a fall
or button-press routes to an alert push or a professional call center. Families
cannot see *why* an alert fired, cannot reorder the check-in-before-calling
sequence, and - when the vendor retires the service, as Amazon did - lose the
whole capability.[8] Aloe Care's model prices that opacity at $39.99/mo
forever.[4]

Care Ladder's three differentiators, each traceable in the repo:

1. **The escalation policy is the product.** A YAML care plan names the zones,
   the trigger timeouts, and the ordered rungs (re-perceive → speaker check-in
   → wait → dial primary → dial secondary → fail-closed emergency). Changing
   the plan changes the agent's behavior; nothing is vendor-locked.
2. **Every decision is audited.** Cue → rung → tool result → jump (a skipped
   rung, with reason) is a structured timeline the family can read. No
   competitor offers a family-facing "why did it escalate" trace - SafelyYou's
   review workflow is staff-facing B2B, and Nobi's insights target operators.[6]
3. **Privacy at the same bar as the leaders.** Blur/silhouette transforms are
   applied *before* any frame is persisted - mirroring AltumView's
   stick-figures-before-transmission stance, which the vendor leads with for
   exactly the bedrooms-and-bathrooms reason.[3] - and the store refuses
   non-transformed frames outright.

## 4. Why OpenCV 5 specifically (design decisions)

- **Two-ONNX chain via `cv.dnn`:** MediaPipe person detection feeds BlazePose
  keypoints; torso angle + hip height drive a temporal state machine. Porting
  the OpenCV Zoo wrappers to OpenCV 5 surfaced and fixed three real API
  differences (`Net.getInputs()` removal, swapped DNN output blobs, flattened
  `NMSBoxes` indices) - documented in the technical report.
- **Sudden-only fall signature:** the *transition speed* vertical→horizontal,
  not "person low in frame", is the classifier. This is what eliminated the
  pedestrian bend-over false positive on the vtest negative control.
- **Two-tier escalation by evidence:** pose keypoints flicker unreliable on a
  motionless subject, so gradual collapses (bed falls) can never fire the fast
  path - they escalate via the stillness ladder instead. Hard falls escalate
  instantly. Both behaviors are verified on real KU Leuven footage and encoded
  as CI eval cases.
- **MOG2 + Otsu + contours** for the stillness/zone cues: cheap, no training
  data, robust enough that the labeled harness reaches 1.00 recall / 0.00
  false-escalation including real-footage cases.

## 5. Honest limitations

- **Not a medical device.** No accuracy claims beyond the labeled eval; the
  failure-modes doc details occlusion, pet motion, lighting, and blob≠person
  failure classes. The distress heuristic is explicitly non-clinical.
- **Telephony and speaker are simulations.** Dial rungs use a stub dialer and
  reserved NANP fiction numbers; the speaker is scripted. Real ASR/carrier
  failure modes are out of scope and stated as such.
- **Single-camera, single-person assumptions.** Tracking is shape-geometry
  only - never identity or face recognition - so multi-person households are
  a documented weakness, not a claim.
- **Demo-scale validation.** Two real fall clips (one hard fall, one gradual)
  plus a pedestrian negative control, run in CI. That is evidence of correct
  behavior on real footage, not a clinical sensitivity/specificity study.
- **Upload latency.** The async cloud analysis of a 100 s clip takes ~5 min on
  the demo's 0.5-vCPU Fargate task (5 Hz sampling). A production edge build
  would run continuously on-device instead of batch-analyzing uploads.

## Sources

[1] https://www.cdc.gov/falls/data-research/index.html - CDC - Older Adult Falls Data
[3] https://altumview.com - AltumView Sentinare
[4] https://aloecare.com - Aloe Care Health
[6] https://nobi.life - Nobi Smart Lights (fall detection lamps)
[7] https://www.kamihome.com - Kami Home cloud cameras
[8] https://www.besidecare.com/blog/what-to-use-now-that-alexa-together-is-gone - Beside Care - Alexa Together retired May 2025
