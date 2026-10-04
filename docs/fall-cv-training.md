# Fall-frame classifier training

Optional weights for `CueDetector`. Pose heuristics stay the default path. This trainer fits a small logistic regression on grayscale person crops. Not a medical model.

## Dataset (hard filter)

Train only from datasets that appear on this Kaggle search (fall query + Computer Vision tag 13207):

https://www.kaggle.com/datasets?search=fall&tags=13207-Computer+Vision

Slug used: **elwalyahmad/fall-detection**

- Page: https://www.kaggle.com/datasets/elwalyahmad/fall-detection
- Why it matches: the card is on that filtered search. Roboflow YOLO images with classes `Fall Detected` and `NoFall Detected` (about 47 MB). It is not URFD, Le2i, or Fe2i.

Config: `configs/fall_train.yaml`. Unknown slugs and URFD/Le2i/Fe2i names are rejected.

## Download

Needs a Kaggle API token (`KAGGLE_USERNAME` + `KAGGLE_KEY`, or `~/.kaggle/kaggle.json`). The token is not committed.

```bash
# writes data/kaggle/elwalyahmad-fall-detection/ (gitignored)
python -m care_ladder.vision.fall_train --download-only
# or
./scripts/download_fall_dataset.sh
```

Equivalent API call used by the module:

```text
GET https://www.kaggle.com/api/v1/datasets/download/elwalyahmad/fall-detection
```

If auth or download fails, stop. Do not invent frames or a fake trained model. Tests cover parse/train/load without the zip.

## Train

```bash
python -m care_ladder.vision.fall_train
```

Weights land at `models/fall_classifier.npz` (gitignored, listed in `.gitignore` as `models/*.npz`). The file is a few kilobytes of logistic weights, not an ONNX dump.

## How the existing detector loads them

`CueDetector.from_plan` calls `load_trained_classifier()`, which reads `models/fall_classifier.npz` when that file exists and otherwise returns `None`. API fixtures that build a detector from the care plan pick this up automatically. When the classifier score stays at or above the configured threshold for `distress_sustain_sec`, the detector emits `distress_heuristic` with `source: trained_fall_classifier`. Pose geometry still wins if it fires first.

## Short run (when the zip is present)

```bash
python -m care_ladder.vision.fall_train
```

`configs/fall_train.yaml` caps the fit at 400 samples and 25 epochs so a real run stays short.
