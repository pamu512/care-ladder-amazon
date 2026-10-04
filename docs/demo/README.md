# Amazon demo remux

Shipped artifact: [`docs/demo/care-ladder-amazon-demo.mp4`](care-ladder-amazon-demo.mp4)

- Duration: `00:02:03.38` (123.38s), 1280x720, H.264 + AAC, about 2.6 MB
- VO source: [`docs/demo-video-script-amazon.md`](../demo-video-script-amazon.md)
- Method: same remux the OpenCV pack used (live local UI stills + spoken VO, then ffmpeg). Browser at 1280x720 because a Fire TV stick was not available in this environment.

This tape does not claim a trained fall model and does not invent accuracy numbers. Fall training is a path only. Dataset slug `elwalyahmad/fall-detection`. Weights would be `models/fall_classifier.npz`. `CueDetector.from_plan` loads that file when it is present. Training did not run. Kaggle credentials were missing.

## Regenerate

1. Synthesize `docs/demo/vo/shot01.wav` through `shot10.wav` (not committed):

```bash
# needs CARTESIA_API_KEY. Spoken lines live in the script (TTS expansions only: Alexa Plus, M C P, Cue Detector from plan).
./scripts/generate_amazon_demo_vo.sh
```

2. Recapture live `/ui/` and `/firetv/` frames and remux:

```bash
CARE_LADDER_ALLOW_INSECURE_LOCAL=1 ./scripts/render_amazon_demo.sh
```

Needs: local API (script starts uvicorn on 8010 if `/plan` is down), Chrome at `/opt/google/chrome/chrome` (or `CHROME=`), Node + puppeteer-core (installed under `/tmp/care-ladder-demo-capture`), ffmpeg, and the ten VO wavs.

Intermediates (`docs/demo/vo/`, `docs/demo/frames/`) are gitignored. The mp4 is the ship file.

Local path after a successful remux: `/workspace/docs/demo/care-ladder-amazon-demo.mp4`
