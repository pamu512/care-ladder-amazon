# REPO-PLAN — minimal `care-ladder-amazon`

**Status:** Plan only. Do **not** create the GitHub repo or move code until Anoop says go.  
**Authority tip:** `pamu512/opencv-care-ladder` branch `amazon/alexa-plus-fire-tv` @ `0fbfb111` (2026-09-28 22:51 UTC / **2026-09-29 06:51 HKT**). Mac may lag at `f6b74a6`; GitHub tip wins.  
**Owner after approval:** Careladder-AWS agent `df7af528-eaf2-497f-950f-674d952c2c00` for leftovers; Hermes = Mac Cursor worker on the repo (not chat teammate `d80bb35c`).  
**Hard locks:** Do **not** merge `amazon/*` into OpenCV `main` until after OpenCV judging. No Final Submit without Anoop.

---

## 1. Why a separate public repo

Amazon submission needs a **public OSS repo** (or private + Amazon collaborator invites that expire in 7 days). Preferred path: **new public `care-ladder-amazon`** so:

1. Devpost GitHub URL can point at an Amazon-first README (Alexa+ / Fire TV / MCP scream) without rewriting the OpenCV competition narrative on `opencv-care-ladder`.
2. OpenCV judging stays on `opencv-care-ladder` `main` + OpenCV docs; Amazon branch stays isolated until after OpenCV judging.
3. Open Source mini-challenge can cite the **new** public repo as the in-window OSS ship (license file required).

Working name: **`care-ladder-amazon`** under `pamu512` (confirm exact login/org with Anoop). Product name on Devpost stays **Care Ladder**.

---

## 2. Source of truth & branch strategy

| Surface | Role |
| --- | --- |
| `opencv-care-ladder` `main` | OpenCV competition spine + live AWS demo; **do not merge amazon until after OpenCV judging** |
| `opencv-care-ladder` `amazon/alexa-plus-fire-tv` | Implementation workshop branch; tip = authority for what to copy |
| **NEW** `care-ladder-amazon` `main` | Amazon-facing public submission repo |

### Recommended cutover (after Anoop approves)

1. Create empty public `care-ladder-amazon` with MIT LICENSE + `.gitignore`.
2. One-shot import from tip:  
   `git clone --branch amazon/alexa-plus-fire-tv --single-branch <opencv-url> tmp && cd tmp && git checkout --orphan amazon-ship && git reset` then add only the **copy set** below, commit, push as `main` of `care-ladder-amazon`.  
   *Alternative (faster, noisier history):* push the amazon tip as `main` then delete OpenCV-only paths in a follow-up commit. Prefer orphan/minimal for judge clarity.
3. Keep developing Amazon deepeners on **both** until freeze:  
   - Hermes continues PRs into `opencv-care-ladder` `amazon/alexa-plus-fire-tv` (existing CI/tests habit).  
   - Careladder-AWS cherry-picks or mirrors into `care-ladder-amazon` `main` for Devpost URL.  
   *Or* flip: after split, Hermes works primarily on `care-ladder-amazon` and periodically backports ladder fixes to opencv amazon branch. **Pick one primary** at cutover; default = **primary = care-ladder-amazon** once created so Devpost URL never drifts.
4. Tag release `amazon-hack-2026` only when Anoop approves Final Submit pack (video + friction + Devpost fields). No tag = not submitted.

### What not to do

- Do not force-push or delete `amazon/alexa-plus-fire-tv` on opencv until after OpenCV judging + Amazon submit buffer.
- Do not point Devpost at the opencv amazon **branch URL** long-term (branch URLs confuse judges; separate repo README is clearer). Short-term draft may still say branch until swap (see §6).
- Do not merge amazon → opencv `main` before OpenCV judging completes (~Oct 26).

---

## 3. What to COPY vs submodule/vendor vs leave behind

### 3A. COPY (first-class in `care-ladder-amazon`)

These are the Amazon product + shared care-ladder spine needed to run the demo.

| Path | Why |
| --- | --- |
| `src/care_ladder/` (entire package) | Ladder, MCP server (`mcp_server/`), Fire TV static (`api/static/firetv/`), channels, audit, privacy, plan loader, learning — required to run |
| `configs/amazon_demo_home.yaml` | Amazon demo household / rung order |
| `configs/demo_home.yaml` | Keep for regression + before/after story; rename prominence in README to “legacy OpenCV plan” |
| `tests/` Amazon + shared: `test_mcp_server.py`, `test_alexa_sim.py`, `test_amazon_*.py`, `test_firetv_app.py`, `test_response_intent.py`, `test_routine_profile.py`, `test_learning_api.py`, `test_detector_learning.py`, plus core ladder/API/privacy/orchestrator tests the Amazon paths depend on | Prove MCP + Fire TV + intent at runtime |
| `scripts/run_demo.sh`, `scripts/infra.sh` (if still used for Amazon deploy) | Local + optional AWS replay |
| `Dockerfile`, `.github/workflows/ci.yml`, `.dockerignore`, `.gitignore` | Ship + CI; retarget badge URLs to new repo |
| `infra/` | Optional but honest if claiming live HTTPS; document whether CloudFront still points at opencv deploy |
| `docs/friction-log.md` | **Required** for ≤10% bonus |
| `docs/demo-video-script-amazon.md`, `docs/devpost-draft-amazon.md` | Ship pack |
| `docs/superpowers/specs/2026-09-26-amazon-care-ladder-alexa-plus-prd.md` | Judge-facing design lock |
| `docs/superpowers/specs/fire-tv-dashboard/` | UX lock + screenshots (Calm Care-Tech) |
| `docs/superpowers/plans/2026-09-26-amazon-care-ladder-alexa-plus.md` | Implementation history |
| `docs/failure-modes.md`, `docs/research-brief.md` (short cite) | Credibility without OpenCV-competition framing |
| `pyproject.toml`, `requirements-lock.txt` | Retitle description to Amazon Alexa+/Fire TV; keep `mcp>=2.2.0` |
| **LICENSE** | **Critical gap:** MIT exists on opencv `main` but is **missing** on `amazon/alexa-plus-fire-tv`. Copy MIT from `main` into new repo root on day one |
| Root `README.md` | Replace with Amazon-first structure (§5) |

### 3B. VENDOR / SUBMODULE (prefer **vendor snapshot**, not live submodule)

OpenCV vision stack is the **trigger**, not the Amazon track gate. Judges need it to run cues; they do not need a nested OpenCV competition repo.

| Approach | Recommendation |
| --- | --- |
| **Vendor (preferred)** | Keep `src/care_ladder/vision/` **copied** into care-ladder-amazon as-is (already in package). No git submodule. Document: “vision cues vendored from opencv-care-ladder; Amazon work is MCP + Fire TV + rungs.” |
| **Submodule** | Only if Anoop wants a hard split later. Adds clone friction for judges — **avoid for hackathon**. |
| **Models / clips** | Keep `scripts/download_models.sh`, `scripts/download_clips.sh`, `clips/README.md`. Do **not** commit large binaries; README points at download scripts. Demo fixtures that need synthetic frames still work without ONNX for Alexa path fixtures. |

### 3C. LEAVE BEHIND — OpenCV-only (do not copy, or demote to `/archive` if history-imported)

| Path / concern | Why stay OpenCV-only |
| --- | --- |
| `grant/` (if/when present on opencv main or filing pack) | OpenCV / AWS grant materials — not Amazon submission surface |
| OpenCV competition Devpost draft `docs/devpost-draft-opencv.md` | Wrong track narrative |
| `docs/demo-video-script.md`, `docs/demo-script.md`, `docs/demo/care-ladder-demo.mp4` | OpenCV judge video assets |
| `docs/technical-report.md`, `docs/eval-metrics.json`, `docs/competitive-landscape.md` (optional thin cite only) | OpenCV Agentic Vision judging pack |
| `docs/agentic-workflow.html` | OpenCV narrative unless retitled |
| OpenCV-heavy fixture emphasis in README (`opencv_stillness`, `opencv_dnn_person` as primary demo) | Keep as optional “vision trigger proofs”; do not lead README |
| OpenCV CI badge / “OpenCV AI Competition 2026” as the **title** framing | Move to a short “Origins” footnote |
| Any Bee / Ring / Bedrock scaffolding | Explicit non-goals (see DEEPEN.md) |

---

## 4. Minimal tree sketch (target `care-ladder-amazon`)

```
care-ladder-amazon/
  LICENSE                 # MIT (from opencv main)
  README.md               # Amazon-first (§5)
  pyproject.toml          # description retitled
  Dockerfile
  configs/
    amazon_demo_home.yaml # primary
    demo_home.yaml        # legacy / before
  src/care_ladder/        # full package incl. mcp_server + firetv + vision
  tests/                  # Amazon + shared spine
  docs/
    friction-log.md
    demo-video-script-amazon.md
    failure-modes.md
    superpowers/specs/...amazon... + fire-tv-dashboard/
  scripts/run_demo.sh
  infra/                  # optional
```

---

## 5. README structure that screams Alexa+ / Fire TV / MCP

Order matters — judges skim.

1. **Title + badges:** Care Ladder · Alexa+ (primary) · Fire TV (supporting) · MCP Streamable HTTP  
2. **One-liner:** Camera cue → multi-rung care ladder → Alexa+ agent (self-hosted MCP) → Fire TV caregiver audit (silhouette-only). Wellness ladder, not a medical device.  
3. **Hackathon map (table):** Primary track Alexa+ · Supporting Fire TV · MCP spec 2025-11-25+ Streamable HTTP at `/mcp` · seven tools listed by name · AWS Builder mini: **not filed** (no Bedrock/AgentCore in-tree).  
4. **Agentic proof (not thin MCP):** session state keyed by household+incident; tools `start_or_resume_incident` → `check_in_prompt` → `advance_rung` / `notify_caretaker` / `resolve_incident`; in-repo MCP **client** `alexa_sim.py`.  
5. **Quickstart (≤60s to something on screen):** uvicorn + `/firetv/` + `python -m care_ladder.mcp_server.alexa_sim`.  
6. **Demo paths:** soft OK / needs human / unclear / Path B occlusion — map to fixtures.  
7. **Privacy & fail-closed:** silhouette; emergency off + hard lock; reserved `(555) 010-2276`.  
8. **Friction log link** (bonus).  
9. **Origins footnote:** significant in-window update of OpenCV Care Ladder (`opencv-care-ladder`); vision cues retained; OpenCV repo stays separate until after OpenCV judging.  
10. **License:** MIT.

Do **not** lead with OpenCV DNN eval tables or grant language.

---

## 6. Devpost GitHub URL swap steps (when Anoop approves repo create)

1. Create `care-ladder-amazon` public + MIT; push minimal tree from tip `0fbfb111` (+ LICENSE from main).  
2. Verify clone-and-run from a clean machine: tests for MCP + Fire TV green; `/mcp` initialize; `/firetv/` loads.  
3. On Devpost project https://devpost.com/software/care-ladder : replace GitHub field from `pamu512/opencv-care-ladder` (branch note) → `https://github.com/pamu512/care-ladder-amazon`.  
4. Update in-repo `docs/devpost-draft-amazon.md` Links section to match.  
5. Re-check Open Source mini fields if filing that mini: contribution/repo URL = new repo; describe in-window Amazon delta.  
6. **Do not Final Submit** — leave draft until Anoop + video + friction completeness.  
7. If ever forced to stay private: add Amazon DR GitHub users (`chris-trag`, `knmeiss`, `giolaq`, `anishamalde`, `mosesroth`, `emersonsklar`) **at submit time** (invites expire 7 days).

---

## 7. License

- **MIT**, copyright Anoop Pamu (2026), verbatim from opencv `main` `LICENSE`.  
- Ensure LICENSE is present on `care-ladder-amazon` **main** before any public Devpost link (amazon branch currently lacks the file).  
- Keep third-party attributions (`docs/demo/ATTRIBUTION.txt` if any demo assets are copied).

---

## 8. Deploy / CI notes for the split

- opencv CI deploys **only** on push to `main` — amazon branch does not burn the live OpenCV demo.  
- New repo: either (a) no auto-deploy until Anoop wants a separate CloudFront, or (b) duplicate infra with a distinct hostname so OpenCV URL stays stable. Default: **CI = test-only** on care-ladder-amazon until explicitly approved.  
- Restored: `.github/workflows/ci.yml` is test-only (`pytest`). Parked copy `docs/amazon-split/ci.yml.pending` removed.  
- Live demo today: `https://d2u7pls4da2poz.cloudfront.net/` — document as “shared demo host from opencv stack” until a dedicated Amazon host exists; do not break OpenCV judges.

---

## 9. Acceptance check (repo plan done)

- [ ] Anoop approved create + exact repo name/visibility  
- [ ] LICENSE on day-one commit  
- [ ] README leads Alexa+/Fire TV/MCP; OpenCV is footnote  
- [ ] `grant/` and OpenCV video/eval pack absent  
- [ ] Devpost URL swap checklist executed only after clone-and-run verified  
- [ ] No merge into opencv `main`; no Final Submit  

