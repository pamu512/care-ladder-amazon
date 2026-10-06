# Amazon demo remux

Shipped artifact: [`docs/demo/care-ladder-amazon-demo.mp4`](care-ladder-amazon-demo.mp4)

This cut is the 15-beat family-ladder script with Chatterbox VO (Cartesia
account was out of credits). `docs/demo/care-ladder-amazon-demo.mp4` is the
ship path. Intermediate frames stay gitignored; committed VO lives in
[`docs/demo/vo/chatterbox/`](vo/chatterbox/).

## Voice

- Chatterbox (intended voice): `./scripts/generate_amazon_demo_vo_chatterbox.sh`
  - `LINE=b03` regenerates one clip
  - `docs/demo/vo/anoop/<clip>.wav` overrides narrator TTS through the same mix
  - Settings: [`vo/chatterbox/SETTINGS.txt`](vo/chatterbox/SETTINGS.txt)
- Cartesia (later swap): `CARTESIA_API_KEY=... ./scripts/generate_amazon_demo_vo.sh`
  - Refuses to invent audio without the key
  - Skips wavs that already exist
  - Voices: narrator Ricardo, Alexa Camille, neighbor Connie
  - TTS expansions only: "Alexa Plus", "M C P"

Then remux (VO dir and output are env vars so a Cartesia swap is re-time + re-render):

```bash
VO=docs/demo/vo/chatterbox \
OUT=docs/demo/care-ladder-amazon-demo.mp4 \
CARE_LADDER_ALLOW_INSECURE_LOCAL=1 \
  ./scripts/render_amazon_demo.sh
```

Needs: local API (script starts uvicorn on 8010 if `/plan` is down), Chrome,
Node + puppeteer-core (under `/tmp/care-ladder-demo-capture`), ffmpeg, and the
beat wavs named in [`vo_lines.tsv`](vo_lines.tsv).
