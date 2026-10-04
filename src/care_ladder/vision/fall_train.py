"""Train and load a small fall-frame classifier for CueDetector.

Dataset constraint: only Kaggle slugs that appear on
https://www.kaggle.com/datasets?search=fall&tags=13207-Computer+Vision
URFD / Le2i / Fe2i families are refused. Missing Kaggle auth is a hard stop
(no synthetic stand-in for the real download).
"""

from __future__ import annotations

import argparse
import base64
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
        data = np.load(Path(path), allow_pickle=True)
        return cls(
            weights=data["weights"],
            bias=float(data["bias"]),
            input_wh=tuple(int(v) for v in data["input_wh"]),
            threshold=float(data["threshold"]),
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


def _features_for_sample(
    image: Path,
    box: tuple[float, float, float, float],
    input_wh: tuple[int, int],
) -> np.ndarray | None:
    frame = cv2.imread(str(image))
    if frame is None:
        return None
    tmp = FallFrameClassifier(np.zeros(input_wh[0] * input_wh[1]), 0.0, input_wh=input_wh)
    return tmp.features(frame, box)


def train_from_dataset(cfg: dict[str, Any], data_root: Path) -> FallFrameClassifier:
    train_cfg = cfg.get("train") or {}
    input_wh = tuple(int(v) for v in train_cfg.get("input_wh", [32, 32]))
    if len(input_wh) != 2:
        raise ValueError("train.input_wh must be [width, height]")
    max_samples = int(train_cfg.get("max_samples", 400))
    fall_ids = tuple(int(v) for v in cfg["dataset"]["fall_class_ids"])
    X: list[np.ndarray] = []
    y: list[float] = []
    for image, label, box in iter_yolo_samples(data_root, fall_class_ids=fall_ids):
        feat = _features_for_sample(image, box, input_wh)
        if feat is None:
            continue
        X.append(feat)
        y.append(float(label))
        if len(X) >= max_samples:
            break
    if not X:
        raise FileNotFoundError(
            f"no labeled YOLO samples under {data_root}; download the Kaggle set first"
        )
    if len(set(y)) < 2:
        raise ValueError("training set has only one class; refusing to fit")
    return train_logistic(
        np.stack(X),
        np.asarray(y),
        epochs=int(train_cfg.get("epochs", 25)),
        lr=float(train_cfg.get("lr", 0.3)),
        threshold=float(train_cfg.get("threshold", 0.65)),
        input_wh=input_wh,
    )


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
    try:
        clf = train_from_dataset(cfg, dest)
    except (FileNotFoundError, ValueError) as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        return 3
    weights = repo_root() / str(cfg["weights"])
    clf.save(weights, slug=slug)
    print(f"weights: {weights} (gitignored)")
    print(f"load: CueDetector.from_plan attaches {weights.name} when the file exists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
