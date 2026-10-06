# Amazon demo remux

Shipped artifact: [`docs/demo/care-ladder-amazon-demo.mp4`](care-ladder-amazon-demo.mp4)

This cut is the 15-beat family-ladder script with US English edge-tts VO.
`docs/demo/care-ladder-amazon-demo.mp4` is the ship path. Intermediate frames
stay gitignored; committed VO lives in [`docs/demo/vo/edge/`](vo/edge/).

## Voice

- Edge-tts (ship voice): `./scripts/generate_amazon_demo_vo_edge.sh`
  - Narrator `en-US-BrianMultilingualNeural` at about -5%
  - Alexa `en-US-AvaNeural` (small-speaker EQ)
  - Neighbor `en-US-EmmaMultilingualNeural` (calm)
  - `LINE=b03` regenerates one clip
  - `docs/demo/vo/anoop/<clip>.wav` overrides narrator TTS through the same mix
  - Settings: [`vo/edge/SETTINGS.txt`](vo/edge/SETTINGS.txt)
- Cartesia (later swap): `CARTESIA_API_KEY=... ./scripts/generate_amazon_demo_vo.sh`
  - Refuses to invent audio without the key
  - Skips wavs that already exist
  - Voices: narrator Ricardo, Alexa Camille, neighbor Connie
  - TTS expansions only: "Alexa Plus", "M C P"
- Chatterbox (not the ship voice): `./scripts/generate_amazon_demo_vo_chatterbox.sh`

Then remux (VO dir and output are env vars so a Cartesia swap is re-time + re-render):

```bash
VO=docs/demo/vo/edge \
OUT=docs/demo/care-ladder-amazon-demo.mp4 \
CARE_LADDER_ALLOW_INSECURE_LOCAL=1 \
  ./scripts/render_amazon_demo.sh
```

Needs: local API (script starts uvicorn on 8010 if `/plan` is down), Chrome,
Node + puppeteer-core (under `/tmp/care-ladder-demo-capture`), ffmpeg, and the
beat wavs named in [`vo_lines.tsv`](vo_lines.tsv).
