"""Fall-classifier training path: works without a Kaggle download."""

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from care_ladder.plan_loader import load_care_plan
from care_ladder.vision.cues import CueDetector
from care_ladder.vision.fall_train import (
    ALLOWED_SLUGS,
    BANNED_SLUG_MARKERS,
    FILTER_URL,
    BannedDatasetError,
    FallFrameClassifier,
    KaggleAuthError,
    assert_allowed_slug,
    default_weights_path,
    download_kaggle_dataset,
    iter_yolo_samples,
    load_train_config,
    load_trained_classifier,
    parse_yolo_line,
    train_logistic,
)

PLAN = Path(__file__).resolve().parents[1] / "configs" / "demo_home.yaml"
CONFIG = Path(__file__).resolve().parents[1] / "configs" / "fall_train.yaml"


def _horiz(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f = np.zeros((64, 64, 3), dtype=np.uint8)
    f[:] = 20
    f[42:52, 6:58] = 200
    f = np.clip(f.astype(np.int16) + rng.integers(-6, 7, f.shape), 0, 255).astype(np.uint8)
    return f


def _vert(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f = np.zeros((64, 64, 3), dtype=np.uint8)
    f[:] = 20
    f[6:56, 24:40] = 200
    f = np.clip(f.astype(np.int16) + rng.integers(-6, 7, f.shape), 0, 255).astype(np.uint8)
    return f


def _blob_box(frame: np.ndarray) -> tuple[float, float, float, float]:
    det = CueDetector(
        no_movement_timeout_sec=9,
        zone=[(0, 0), (64, 0), (64, 64), (0, 64)],
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blob = det._largest_blob(gray)
    assert blob is not None
    return (
        blob["cx"] - blob["w"] / 2.0,
        blob["cy"] - blob["h"] / 2.0,
        blob["cx"] + blob["w"] / 2.0,
        blob["cy"] + blob["h"] / 2.0,
    )


def _synthetic_classifier():
    fe = FallFrameClassifier(np.zeros(32 * 32), 0.0)
    X, y = [], []
    for i in range(12):
        horiz = _horiz(i)
        X.append(fe.features(horiz, _blob_box(horiz)))
        y.append(1.0)
        vert = _vert(i + 20)
        X.append(fe.features(vert, _blob_box(vert)))
        y.append(0.0)
    return train_logistic(np.stack(X), np.asarray(y), epochs=40, lr=0.4, seed=0)


def test_config_pins_filter_page_slug():
    cfg = load_train_config(CONFIG)
    assert cfg["dataset"]["filter"] == FILTER_URL
    assert FILTER_URL == "https://www.kaggle.com/datasets?search=fall&tags=13207-Computer+Vision"
    slug = cfg["dataset"]["slug"]
    assert slug == "elwalyahmad/fall-detection"
    assert slug in ALLOWED_SLUGS
    assert "urfd" not in slug.lower()
    assert "le2i" not in slug.lower()
    assert cfg["dataset"]["page"] == "https://www.kaggle.com/datasets/elwalyahmad/fall-detection"


def test_rejects_urfd_le2i_and_unknown_slugs():
    for slug in (
        "someone/urfd-fall",
        "owner/le2i-fall-dataset",
        "starxz/fe2i-fall-detection-datasetannotated",
        "uttejkumarkandagatla/fall-detection-dataset",
    ):
        with pytest.raises(BannedDatasetError):
            assert_allowed_slug(slug)
    assert_allowed_slug("elwalyahmad/fall-detection")
    for marker in ("urfd", "le2i", "fe2i"):
        assert marker in BANNED_SLUG_MARKERS


def test_parse_yolo_line_reads_class_and_box():
    assert parse_yolo_line("0 0.5 0.6 0.4 0.2") == (0, 0.5, 0.6, 0.4, 0.2)
    assert parse_yolo_line("1 0.1 0.2 0.3 0.4 0.5 0.6 2") == (1, 0.1, 0.2, 0.3, 0.4)
    assert parse_yolo_line("") is None
    assert parse_yolo_line("0 0.5") is None


def test_iter_yolo_samples_pairs_roboflow_layout(tmp_path: Path):
    img_dir = tmp_path / "train" / "images"
    lab_dir = tmp_path / "train" / "labels"
    img_dir.mkdir(parents=True)
    lab_dir.mkdir(parents=True)
    cv2.imwrite(str(img_dir / "a.jpg"), _horiz(1))
    (lab_dir / "a.txt").write_text("0 0.50 0.72 0.80 0.16\n")
    rows = list(iter_yolo_samples(tmp_path, fall_class_ids=(0,)))
    assert len(rows) == 1
    path, label, box = rows[0]
    assert path.name == "a.jpg"
    assert label == 1
    assert box[2] > box[0]


def test_download_raises_without_kaggle_auth(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.setattr(
        "care_ladder.vision.fall_train._kaggle_json_path",
        lambda: tmp_path / "missing-kaggle.json",
    )
    with pytest.raises(KaggleAuthError, match="Kaggle API credentials missing"):
        download_kaggle_dataset("elwalyahmad/fall-detection", tmp_path / "out")


def test_train_on_synthetic_separates_fall_from_upright():
    clf = _synthetic_classifier()
    fall = _horiz(99)
    stand = _vert(99)
    assert clf.predict_proba(fall, _blob_box(fall)) >= 0.6
    assert clf.predict_proba(stand, _blob_box(stand)) < 0.4


def test_classifier_save_load_roundtrip(tmp_path: Path):
    clf = _synthetic_classifier()
    path = tmp_path / "fall_classifier.npz"
    clf.save(path, slug="elwalyahmad/fall-detection")
    loaded = load_trained_classifier(path)
    assert loaded is not None
    assert abs(loaded.predict_proba(_horiz(3)) - clf.predict_proba(_horiz(3))) < 1e-6


def test_from_plan_attaches_weights_when_present(tmp_path: Path, monkeypatch):
    path = tmp_path / "fall_classifier.npz"
    _synthetic_classifier().save(path, slug="elwalyahmad/fall-detection")
    monkeypatch.setattr(
        "care_ladder.vision.fall_train.default_weights_path",
        lambda: path,
    )
    det = CueDetector.from_plan(load_care_plan(PLAN), zone_id="living_room")
    assert det.fall_classifier is not None
    assert default_weights_path().name == "fall_classifier.npz"


def test_from_plan_skips_missing_weights(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "care_ladder.vision.fall_train.default_weights_path",
        lambda: tmp_path / "nope.npz",
    )
    det = CueDetector.from_plan(load_care_plan(PLAN), zone_id="living_room")
    assert det.fall_classifier is None


def test_cue_detector_uses_trained_weights_not_shape_heuristic():
    clf = _synthetic_classifier()
    det = CueDetector(
        no_movement_timeout_sec=999,
        zone=[(0, 0), (64, 0), (64, 64), (0, 64)],
        enable_no_movement=False,
        enable_no_visibility=False,
        enable_distress_heuristic=True,
        distress_sustain_sec=0.0,
        distress_aspect_min=99.0,
        fall_classifier=clf,
        fall_score_threshold=0.55,
    )
    cue = det.observe(_horiz(7), t=0.0)
    assert cue is not None
    assert cue.kind == "distress_heuristic"
    assert cue.detail["source"] == "trained_fall_classifier"
    assert cue.detail["score"] >= 0.55

    standing = CueDetector(
        no_movement_timeout_sec=999,
        zone=[(0, 0), (64, 0), (64, 64), (0, 64)],
        enable_no_movement=False,
        enable_no_visibility=False,
        enable_distress_heuristic=True,
        distress_sustain_sec=0.0,
        distress_aspect_min=99.0,
        fall_classifier=clf,
        fall_score_threshold=0.55,
    )
    assert standing.observe(_vert(7), t=0.0) is None


def test_config_yaml_is_loadable():
    data = yaml.safe_load(CONFIG.read_text())
    assert data["weights"].endswith("fall_classifier.npz")
    assert data["dataset"]["fall_class_ids"] == [0]
