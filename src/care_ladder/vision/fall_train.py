"""Train and load a small fall-frame classifier for CueDetector.

Dataset constraint: only Kaggle slugs that appear on
https://www.kaggle.com/datasets?search=fall&tags=13207-Computer+Vision
URFD / Le2i / Fe2i families are refused. Missing Kaggle auth is a hard stop
(no synthetic stand-in for the real download).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np
import yaml

FILTER_URL = "https://www.kaggle.com/datasets?search=fall&tags=13207-Computer+Vision"
ALLOWED_SLUGS: dict[str, dict[str, str]] = {
    "elwalyahmad/fall-detection": {
        "page": "https://www.kaggle.com/datasets/elwalyahmad/fall-detection",
        "why": (
            "On the fall + Computer Vision (tag 13207) search. "
            "Roboflow YOLO images labeled Fall Detected / NoFall Detected. "
            "Not URFD or Le2i."
        ),
    }
}
BANNED_SLUG_MARKERS = ("urfd", "le2i", "fe2i")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


class BannedDatasetError(ValueError):
    """Slug is banned or is not on the fall+CV filter allowlist."""


class KaggleAuthError(RuntimeError):
    """Kaggle credentials missing or the download was rejected."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_weights_path() -> Path:
    return repo_root() / "models" / "fall_classifier.npz"


def default_config_path() -> Path:
    return repo_root() / "configs" / "fall_train.yaml"


def _kaggle_json_path() -> Path:
    return Path.home() / ".kaggle" / "kaggle.json"


def assert_allowed_slug(slug: str) -> None:
    s = (slug or "").strip().lower()
    if not s or "/" not in s:
        raise BannedDatasetError(f"invalid dataset slug: {slug!r}")
    for marker in BANNED_SLUG_MARKERS:
        if marker in s:
            raise BannedDatasetError(
                f"{slug} is banned (URFD / Le2i family or not on {FILTER_URL})"
            )
    if s not in ALLOWED_SLUGS:
        raise BannedDatasetError(
            f"{slug} is not on the allowlist for {FILTER_URL}"
        )


def load_train_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("fall train config must be a mapping")
    dataset = data.get("dataset")
    if not isinstance(dataset, dict) or not dataset.get("slug"):
        raise ValueError("fall train config missing dataset.slug")
    assert_allowed_slug(str(dataset["slug"]))
    if dataset.get("filter") != FILTER_URL:
        raise ValueError(f"dataset.filter must be exactly {FILTER_URL}")
    return data


def parse_yolo_line(line: str) -> tuple[int, float, float, float, float] | None:
    parts = line.strip().split()
    if len(parts) < 5:
        return None
    try:
        cls = int(float(parts[0]))
        xc, yc, w, h = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return cls, xc, yc, w, h


def _image_for_label(label: Path) -> Path | None:
    stem = label.stem
    search_dirs = []
    if label.parent.name == "labels":
        search_dirs.append(label.parent.parent / "images")
    search_dirs.append(label.parent)
    for directory in search_dirs:
        for ext in _IMAGE_EXTS:
            for candidate in (directory / f"{stem}{ext}", directory / f"{stem}{ext.upper()}"):
                if candidate.is_file():
                    return candidate
    return None


def _yolo_to_xyxy(
    xc: float, yc: float, w: float, h: float, width: int, height: int
) -> tuple[float, float, float, float]:
    bw, bh = w * width, h * height
    cx, cy = xc * width, yc * height
    x1, y1 = cx - bw / 2.0, cy - bh / 2.0
    return x1, y1, x1 + bw, y1 + bh


def iter_yolo_samples(
    root: Path, fall_class_ids: tuple[int, ...] = (0,)
) -> Iterator[tuple[Path, int, tuple[float, float, float, float]]]:
    """Yield (image_path, binary_label, xyxy) from a Roboflow/YOLO tree."""
    fall_ids = set(int(v) for v in fall_class_ids)
    for label in sorted(Path(root).rglob("*.txt")):
        if label.parent.name not in {"labels", "train", "valid", "val", "test"}:
            if not any(label.with_suffix(ext).is_file() for ext in _IMAGE_EXTS):
                continue
        image = _image_for_label(label)
        if image is None:
            continue
        frame = cv2.imread(str(image))
        if frame is None:
            continue
        height, width = frame.shape[:2]
        for raw in label.read_text().splitlines():
            parsed = parse_yolo_line(raw)
            if parsed is None:
                continue
            cls, xc, yc, bw, bh = parsed
            box = _yolo_to_xyxy(xc, yc, bw, bh, width, height)
            yield image, 1 if cls in fall_ids else 0, box


def _letterbox_gray(gray: np.ndarray, wh: tuple[int, int]) -> np.ndarray:
    """Pad-resize so a wide fall crop stays wide after the 32x32 squash."""
    tw, th = int(wh[0]), int(wh[1])
    if tw <= 0 or th <= 0:
        raise ValueError(f"invalid input_wh {wh!r}")
    h, w = gray.shape[:2]
    scale = min(tw / max(w, 1), th / max(h, 1))
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((th, tw), dtype=np.uint8)
    x0 = (tw - nw) // 2
    y0 = (th - nh) // 2
    canvas[y0 : y0 + nh, x0 : x0 + nw] = resized
    return canvas


class FallFrameClassifier:
    """Binary logistic regression over a 32x32 grayscale crop.

    ponytail: linear model on tiny gray crops. Ceiling is linear
    separability of fall vs upright appearance. Upgrade: HOG or a
    small CNN if pose-free accuracy plateaus.
    """

    def __init__(
        self,
        weights: np.ndarray,
        bias: float,
        input_wh: tuple[int, int] = (32, 32),
        threshold: float = 0.65,
    ) -> None:
        self.weights = np.asarray(weights, dtype=np.float64).reshape(-1)
        self.bias = float(bias)
        self.input_wh = (int(input_wh[0]), int(input_wh[1]))
        self.threshold = float(threshold)
        if self.input_wh[0] < 1 or self.input_wh[1] < 1:
            raise ValueError(f"input_wh must be positive, got {self.input_wh}")
        expected = self.input_wh[0] * self.input_wh[1]
        if self.weights.shape[0] != expected:
            raise ValueError(
                f"weights {self.weights.shape[0]} != input_wh "
                f"{self.input_wh[0]}*{self.input_wh[1]}"
            )
        if not np.isfinite(self.weights).all() or not math.isfinite(self.bias):
            raise ValueError("weights and bias must be finite")
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")

    def features(
        self, frame: np.ndarray, box: tuple[float, float, float, float] | None = None
    ) -> np.ndarray:
        crop = frame
        if box is not None:
            x1, y1, x2, y2 = (int(round(v)) for v in box)
            height, width = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            crop = frame
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        return _letterbox_gray(gray, self.input_wh).reshape(-1).astype(np.float64) / 255.0

    def predict_proba(
        self, frame: np.ndarray, box: tuple[float, float, float, float] | None = None
    ) -> float:
        x = self.features(frame, box)
        if x.shape[0] != self.weights.shape[0]:
            raise ValueError(
                f"feature size {x.shape[0]} != weights {self.weights.shape[0]}"
            )
        z = float(x @ self.weights + self.bias)
        z = min(40.0, max(-40.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def save(self, path: Path, slug: str = "") -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            weights=self.weights,
            bias=np.asarray(self.bias),
            input_wh=np.asarray(self.input_wh),
            threshold=np.asarray(self.threshold),
            slug=np.asarray(slug),
        )

    @classmethod
    def load(cls, path: Path) -> FallFrameClassifier:
        with np.load(Path(path), allow_pickle=False) as data:
            weights = np.array(data["weights"], dtype=np.float64, copy=True)
            bias = float(data["bias"])
            input_wh = tuple(int(v) for v in np.array(data["input_wh"], copy=True))
            threshold = float(data["threshold"])
        return cls(
            weights=weights,
            bias=bias,
            input_wh=input_wh,
            threshold=threshold,
        )


def train_logistic(
    X: np.ndarray,
    y: np.ndarray,
    *,
    epochs: int = 40,
    lr: float = 0.3,
    seed: int = 0,
    threshold: float = 0.65,
    input_wh: tuple[int, int] = (32, 32),
) -> FallFrameClassifier:
    if X.ndim != 2 or y.ndim != 1 or X.shape[0] != y.shape[0] or X.shape[0] == 0:
        raise ValueError("X must be (n, d) and y must be (n,) with n > 0")
    rng = np.random.default_rng(seed)
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n, d = X.shape
    w = rng.normal(0.0, 0.01, size=d)
    b = 0.0
    for _ in range(int(epochs)):
        z = np.clip(X @ w + b, -40.0, 40.0)
        p = 1.0 / (1.0 + np.exp(-z))
        err = p - y
        w -= lr * (X.T @ err) / n
        b -= lr * float(err.mean())
    return FallFrameClassifier(w, b, input_wh=input_wh, threshold=threshold)


def load_trained_classifier(path: Path | None = None) -> FallFrameClassifier | None:
    weights = Path(path) if path is not None else default_weights_path()
    if not weights.is_file():
        return None
    return FallFrameClassifier.load(weights)


def _kaggle_auth() -> tuple[str, str]:
    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if user and key:
        return user, key
    json_path = _kaggle_json_path()
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text())
        except json.JSONDecodeError as exc:
            raise KaggleAuthError(
                f"Kaggle API credentials missing: {json_path} is not valid JSON"
            ) from exc
        user = str(data.get("username") or "").strip()
        key = str(data.get("key") or "").strip()
        if user and key:
            return user, key
    raise KaggleAuthError(
        "Kaggle API credentials missing: set KAGGLE_USERNAME and KAGGLE_KEY "
        "or write ~/.kaggle/kaggle.json. Refusing to invent training data."
    )


def download_kaggle_dataset(slug: str, dest: Path) -> Path:
    assert_allowed_slug(slug)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if any(True for _ in iter_yolo_samples(dest)):
        return dest
    user, key = _kaggle_auth()
    url = f"https://www.kaggle.com/api/v1/datasets/download/{slug}"
    token = base64.b64encode(f"{user}:{key}".encode("utf-8")).decode("ascii")
    req = Request(url, headers={"Authorization": f"Basic {token}"})
    zip_path = dest / "dataset.zip"
    try:
        with urlopen(req, timeout=120) as resp, zip_path.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
    except HTTPError as exc:
        raise KaggleAuthError(
            f"Kaggle download failed HTTP {exc.code}: {exc.reason} for {url}"
        ) from exc
    except URLError as exc:
        raise KaggleAuthError(f"Kaggle download failed: {exc.reason}") from exc
    if not zip_path.is_file() or zip_path.stat().st_size < 1000:
        raise KaggleAuthError(
            f"Kaggle download produced an empty or tiny file at {zip_path}"
        )
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise KaggleAuthError(
            f"Kaggle download was not a zip (auth/download blocker) at {zip_path}"
        ) from exc
    return dest


def sigmoid_score(features: np.ndarray, weights: np.ndarray, bias: float) -> float:
    """Same clamp as FallFrameClassifier.predict_proba and the SageMaker entrypoint."""
    z = float(np.asarray(features, dtype=np.float64) @ np.asarray(weights, dtype=np.float64) + float(bias))
    z = min(40.0, max(-40.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def privacy_features(
    frame: np.ndarray,
    box: tuple[float, float, float, float] | None,
    input_wh: tuple[int, int],
) -> tuple[np.ndarray, str]:
    """Feature vector safe to send off-box. Raw pixels are not returned.

    Blur the frame first. If that leaves the 32x32 vector unchanged, use a
    silhouette. The weights stay the ones in fall_classifier.npz.
    """
    from care_ladder.privacy import blur_faces, to_silhouette

    wh = (int(input_wh[0]), int(input_wh[1]))
    probe = FallFrameClassifier(np.zeros(wh[0] * wh[1]), 0.0, input_wh=wh)
    bgr = frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    raw = probe.features(bgr, box)
    blurred = blur_faces(bgr)
    blurred_vec = probe.features(blurred, box)
    if not np.array_equal(blurred, bgr) and not np.allclose(blurred_vec, raw):
        return blurred_vec, "blur"
    return probe.features(to_silhouette(bgr), box), "silhouette"


def _split_indices(
    y: np.ndarray, holdout_frac: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    if len(y) < 8:
        raise ValueError("need at least 8 samples for a held-out split")
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    n_hold = max(1, int(round(len(y) * holdout_frac)))
    n_hold = min(n_hold, len(y) - 2)
    hold = idx[:n_hold].copy()
    train = idx[n_hold:].copy()

    def classes(part: np.ndarray) -> set[int]:
        return {int(round(float(v))) for v in y[part]}

    for cls in (0, 1):
        if cls not in classes(train) and cls in classes(hold):
            hpos = next(
                i for i, row in enumerate(hold) if int(round(float(y[row]))) == cls
            )
            tpos = next(
                i for i, row in enumerate(train) if int(round(float(y[row]))) != cls
            )
            hold[hpos], train[tpos] = train[tpos], hold[hpos]
    if len(classes(train)) < 2:
        raise ValueError("held-out split could not keep both classes in train")
    return train, hold


def binary_metrics(
    y_true: np.ndarray, scores: np.ndarray, threshold: float
) -> dict[str, float | int]:
    pred = (np.asarray(scores) >= float(threshold)).astype(np.float64)
    truth = np.asarray(y_true, dtype=np.float64)
    tp = int(np.sum((pred == 1) & (truth == 1)))
    fp = int(np.sum((pred == 1) & (truth == 0)))
    fn = int(np.sum((pred == 0) & (truth == 1)))
    tn = int(np.sum((pred == 0) & (truth == 0)))
    n = int(len(truth))
    return {
        "n": n,
        "accuracy": (tp + tn) / n if n else 0.0,
        "precision": tp / (tp + fp) if (tp + fp) else 0.0,
        "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def score_matrix(clf: FallFrameClassifier, rows: np.ndarray) -> np.ndarray:
    return np.asarray(
        [sigmoid_score(row, clf.weights, clf.bias) for row in rows],
        dtype=np.float64,
    )


def fit_held_out(
    X: np.ndarray,
    y: np.ndarray,
    *,
    epochs: int,
    lr: float,
    threshold: float,
    input_wh: tuple[int, int],
    seed: int = 0,
    holdout_frac: float = 0.2,
) -> tuple[FallFrameClassifier, np.ndarray, np.ndarray]:
    """Fit on the train split only. The saved npz is this classifier, not a second model."""
    train_idx, hold_idx = _split_indices(y, holdout_frac, seed)
    clf = train_logistic(
        X[train_idx],
        y[train_idx],
        epochs=epochs,
        lr=lr,
        threshold=threshold,
        input_wh=input_wh,
        seed=seed,
    )
    return clf, train_idx, hold_idx


def format_metrics_markdown(
    raw: dict[str, float | int],
    privacy: dict[str, float | int],
    *,
    sha256: str,
    holdout_tags: dict[str, int],
) -> str:
    def row(label: str, metrics: dict[str, float | int]) -> str:
        return (
            f"| {label} | npz | {metrics['accuracy']:.4f} | "
            f"{metrics['precision']:.4f} | {metrics['recall']:.4f} | {metrics['n']} |"
        )

    tags = ", ".join(f"{k}={v}" for k, v in sorted(holdout_tags.items()))
    return "\n".join(
        [
            "# Held-out metrics",
            "",
            "Canonical artifact: `models/fall_classifier.npz` (one logistic weight vector).",
            "SageMaker `model.tar.gz` embeds that file. There is no ONNX export.",
            "The file is fit on the train split. The holdout rows were not used to fit it.",
            f"sha256: `{sha256}`",
            "",
            "| Input | Weights | Accuracy | Precision | Recall | n |",
            "| --- | --- | --- | --- | --- | --- |",
            row("raw gray crop (local fallback)", raw),
            row("blur or silhouette features (cloud payload)", privacy),
            "",
            f"Holdout privacy tags: {tags}.",
            "Same weights for both rows. Cloud input is not a second model.",
            "",
        ]
    )


def collect_samples(cfg: dict[str, Any], data_root: Path) -> dict[str, Any]:
    train_cfg = cfg.get("train") or {}
    input_wh = tuple(int(v) for v in train_cfg.get("input_wh", [32, 32]))
    if len(input_wh) != 2:
        raise ValueError("train.input_wh must be [width, height]")
    max_samples = int(train_cfg.get("max_samples", 400))
    fall_ids = tuple(int(v) for v in cfg["dataset"]["fall_class_ids"])
    raw_rows: list[np.ndarray] = []
    priv_rows: list[np.ndarray] = []
    labels: list[float] = []
    tags: list[str] = []
    for image, label, box in iter_yolo_samples(data_root, fall_class_ids=fall_ids):
        frame = cv2.imread(str(image))
        if frame is None:
            continue
        probe = FallFrameClassifier(
            np.zeros(input_wh[0] * input_wh[1]), 0.0, input_wh=input_wh
        )
        raw_rows.append(probe.features(frame, box))
        priv, tag = privacy_features(frame, box, input_wh)
        priv_rows.append(priv)
        labels.append(float(label))
        tags.append(tag)
        if len(raw_rows) >= max_samples:
            break
    if not raw_rows:
        raise FileNotFoundError(
            f"no labeled YOLO samples under {data_root}; download the Kaggle set first"
        )
    y = np.asarray(labels, dtype=np.float64)
    if len(set(int(round(float(v))) for v in y)) < 2:
        raise ValueError("training set has only one class; refusing to fit")
    return {
        "X": np.stack(raw_rows),
        "X_priv": np.stack(priv_rows),
        "y": y,
        "input_wh": input_wh,
        "tags": tags,
    }


def train_from_dataset(cfg: dict[str, Any], data_root: Path) -> FallFrameClassifier:
    """Fit on every collected sample. The CLI saves the held-out train split instead."""
    bag = collect_samples(cfg, data_root)
    train_cfg = cfg.get("train") or {}
    return train_logistic(
        bag["X"],
        bag["y"],
        epochs=int(train_cfg.get("epochs", 25)),
        lr=float(train_cfg.get("lr", 0.3)),
        threshold=float(train_cfg.get("threshold", 0.65)),
        input_wh=bag["input_wh"],
    )


def _print_held_out(
    loaded: FallFrameClassifier,
    bag: dict[str, Any],
    hold_idx: np.ndarray,
    weights: Path,
) -> None:
    raw = binary_metrics(
        bag["y"][hold_idx],
        score_matrix(loaded, bag["X"][hold_idx]),
        loaded.threshold,
    )
    priv = binary_metrics(
        bag["y"][hold_idx],
        score_matrix(loaded, bag["X_priv"][hold_idx]),
        loaded.threshold,
    )
    tags: dict[str, int] = {}
    for i in hold_idx:
        tag = bag["tags"][int(i)]
        tags[tag] = tags.get(tag, 0) + 1
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    print("artifact format: npz (canonical; SageMaker tarball embeds this file; no ONNX)")
    print(f"sha256: {digest}")
    print(
        "held-out raw-crop: "
        f"n={raw['n']} accuracy={raw['accuracy']:.4f} "
        f"precision={raw['precision']:.4f} recall={raw['recall']:.4f}"
    )
    print(
        "held-out privacy-features: "
        f"n={priv['n']} accuracy={priv['accuracy']:.4f} "
        f"precision={priv['precision']:.4f} recall={priv['recall']:.4f}"
    )
    print("holdout privacy tags: " + ", ".join(f"{k}={v}" for k, v in sorted(tags.items())))
    print(format_metrics_markdown(raw, priv, sha256=digest, holdout_tags=tags))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the Care Ladder fall-frame classifier")
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="use files already under download_dir (tests / reruns)",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="fetch the Kaggle zip and stop before fitting weights",
    )
    args = parser.parse_args(argv)
    cfg = load_train_config(Path(args.config))
    slug = str(cfg["dataset"]["slug"])
    dest = repo_root() / str(cfg["download_dir"])
    print(f"filter: {FILTER_URL}")
    print(f"slug:   {slug}")
    print(f"page:   {cfg['dataset']['page']}")
    if not args.skip_download:
        try:
            download_kaggle_dataset(slug, dest)
        except KaggleAuthError as exc:
            print(f"BLOCKER: {exc}", file=sys.stderr)
            return 2
    else:
        dest.mkdir(parents=True, exist_ok=True)
    if args.download_only:
        print(f"downloaded: {dest}")
        return 0
    train_cfg = cfg.get("train") or {}
    try:
        bag = collect_samples(cfg, dest)
        if len(bag["y"]) < 8:
            clf = train_logistic(
                bag["X"],
                bag["y"],
                epochs=int(train_cfg.get("epochs", 25)),
                lr=float(train_cfg.get("lr", 0.3)),
                threshold=float(train_cfg.get("threshold", 0.65)),
                input_wh=bag["input_wh"],
            )
            hold_idx = None
        else:
            clf, _train_idx, hold_idx = fit_held_out(
                bag["X"],
                bag["y"],
                epochs=int(train_cfg.get("epochs", 25)),
                lr=float(train_cfg.get("lr", 0.3)),
                threshold=float(train_cfg.get("threshold", 0.65)),
                input_wh=bag["input_wh"],
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        return 3
    weights = repo_root() / str(cfg["weights"])
    clf.save(weights, slug=slug)
    loaded = FallFrameClassifier.load(weights)
    if not np.allclose(loaded.weights, clf.weights) or abs(loaded.bias - clf.bias) > 1e-12:
        print("BLOCKER: saved npz does not match the fitted weights", file=sys.stderr)
        return 3
    print(f"weights: {weights} (gitignored)")
    print(f"load: CueDetector.from_plan attaches {weights.name} when the file exists")
    if hold_idx is None:
        print("held-out: skipped (fewer than 8 samples). Metrics were not invented.")
        return 0
    _print_held_out(loaded, bag, hold_idx, weights)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
