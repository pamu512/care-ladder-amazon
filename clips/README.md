# Demo / evaluation clips

Real-footage clips for the fall-detection demo and evaluation. Downloaded at
setup (not committed - run `scripts/download_clips.sh`); sizes ~40 MB.

| File | Source | Content | Expected |
| --- | --- | --- | --- |
| `kul_fall_1.avi` | KU Leuven Advise "High Quality Fall Simulation Data" (800×480, 30fps) | Nursing-home fall re-enactment | `distress_heuristic` (sudden fall signature) fires |
| `kul_fall_2.avi` | same | Fall onto bed (camera angle variant) | fires (sudden or sustained-down) |
| `vtest.avi` | OpenCV samples (`samples/data/vtest.avi`) | Pedestrians walking | **no** distress cue (mild `no_visibility` when they exit frame is correct; negative control) |

## Attribution / licenses

- **KU Leuven - Advise / Intelligent Sensing Systems**: "High quality fall
  simulation data", recorded in a nursing-home setting by re-enacting actual
  falls. Publicly offered for research on the group's datasets page:
  https://iiw.kuleuven.be/onderzoek/advise/datasets - cited in our technical
  report and submission. Non-clinical research footage.
- **vtest.avi**: classic OpenCV sample video (Apache-2.0, opencv/opencv repo).

## Reproduce detection

```bash
./scripts/download_clips.sh
# Clip eval harness lives on pamu512/opencv-care-ladder (scripts/evaluate.py).
# This repo vendors vision cues; Alexa+ / Fire TV fixtures do not need ONNX or clips.
```

The pose path uses OpenCV 5 DNN with MediaPipe person-detection + pose ONNX
models from OpenCV Zoo; only the SUDDEN vertical→horizontal signature raises
`distress_heuristic` - gradual lying-down is deliberately not cue-worthy
(no_movement covers stillness with the right severity).
