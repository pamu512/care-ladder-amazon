# Care Ladder: product website

Single-page product site for **[pamu512/care-ladder-amazon](https://github.com/pamu512/care-ladder-amazon)**
(HEAD `b7c28d7` at build time, post A1-A4).

## What's here

```
website/
├── index.html                        # the entire site, self-contained, no build step
└── assets/
    ├── firetv-allclear-1280.png      # production dashboard capture (all-clear state)
    ├── firetv-notify-1280.png        # production dashboard capture (needs-human state)
    ├── instrument-sans-latin.woff2   # self-hosted font (from the repo's own copy)
    └── jetbrains-mono-latin.woff2    # self-hosted font (from the repo's own copy)
```

## Open it

Open `index.html` in any browser. Double-click, or:

```bash
cd website
python3 -m http.server 8090   # optional; file:// works too
# → http://localhost:8090
```

No dependencies, no build step, no network calls. Fonts are self-hosted
(the same woff2 files the production dashboard serves to Silk), so the page
renders identically offline.

## Facts on the page (all verified against main @ b7c28d7)

| Claim | Source |
|---|---|
| MCP tools incl. `caregiver_ack`, `caregiver_outcome` | `src/care_ladder/mcp_server/server.py` (`@mcp.tool`) |
| MCP spec 2025-11-25+, Streamable HTTP at `/mcp` | `server.py` docstring, README |
| Notify = Alexa mobile inform card + countdown + 3 actions; Fire TV mirrors | `notify_caretaker`, `care_conversation.py`, TV copy "Family informed on Alexa mobile · this TV mirrors the trail" |
| Resident classifier buckets clear_ok / needs_human / unclear | `channels/response_intent.py` |
| Caregiver classifier buckets im_on_it / call_mom_now / pass_to_next / outcome / unclear | `channels/caregiver_intent.py` |
| Both demos are 1:1 JS ports of the Python classifiers | parity-tested against the repo tests' cases |
| Ladder rungs + fail-closed emergency + reserved (555) numbers | care plan config, orchestrator, README |
| Screenshots | captured from the running dashboard at 1280×720 (pre-A3 build; A3 reframed copy, layout unchanged) |

## Modifying it

| To change | Edit |
|---|---|
| Headline / hero copy | `index.html` → `<header class="hero">` |
| Rung descriptions | `#ladder` section, one `.rung` per rung |
| Resident intent demo examples | `#resident .ex-chip` buttons (logic: `classifyResident()`, keep in sync with `response_intent.py`) |
| Caregiver intent demo examples | `#caregiver .ex-chip` buttons (logic: `classifyCaregiver()`, keep in sync with `caregiver_intent.py`) |
| MCP transcript | `#agent` → `.transcript-body` rows |
| Screenshots | replace `assets/firetv-*.png` (re-capture at 1280×720 from `/firetv/`) |
| Colors / spacing | `:root` CSS variables (Calm Care-Tech tokens) |
| Links (repo/demo) | nav CTA + footer `.foot-meta` |

## Re-capturing screenshots

```bash
# from the care-ladder-amazon repo root
.venv/bin/uvicorn care_ladder.api.app:app --port 8111
curl -s -X POST http://127.0.0.1:8111/demo/run \
  -H 'content-type: application/json' \
  -d '{"fixture":"alexa_path_a_needs_human"}'
# then screenshot http://127.0.0.1:8111/firetv/ at 1280×720
```

## Quality notes

- Responsive: single column below 860px; nav collapses to CTA-only below 720px
- Keyboard: rungs focusable, both demos are real inputs with example chips; visible states throughout
- Accessibility: landmarks, state-aware alt text, `aria-live` verdicts, reduced-motion honored
- Honesty: "simulated" stays simulated; the Proactive Events awareness-chime stub is
  deliberately not featured (env-gated off in the repo); footer carries the product's
  own disclaimer. Em-dashes are scrubbed from editorial prose; the product's pinned
  disclaimer string keeps its own typography.
