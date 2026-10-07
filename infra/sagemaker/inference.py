"""SageMaker entrypoint for the canonical fall_classifier.npz weights.

The sklearn container unpacks model.tar.gz and calls these four functions.
Sigmoid clamp matches FallFrameClassifier.predict_proba in fall_train.py.
This file stays import-light (numpy + stdlib) so the container does not need OpenCV.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
from pathlib import Path

import numpy as np

_PRIVACY = frozenset({"blur", "silhouette"})
_ARTIFACT = "fall_classifier.npz"
_FORBIDDEN = frozenset(
    {"frame", "image", "pixels", "jpeg", "png", "raw", "b64", "base64"}
)
_MAX_FEATURES = 65536


def _verify_manifest(model_dir: Path, blob: bytes) -> None:
    path = model_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"manifest.json missing in {model_dir}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("manifest.json is not JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must be an object")
    if manifest.get("artifact") != _ARTIFACT or manifest.get("format") != "npz":
        raise ValueError("manifest does not describe fall_classifier.npz")
    if manifest.get("onnx") is not False:
        raise ValueError("manifest onnx flag must be false")
    expected = manifest.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("manifest sha256 is missing")
    digest = hashlib.sha256(blob).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise ValueError("manifest sha256 does not match fall_classifier.npz")


def model_fn(model_dir: str) -> dict:
    root = Path(model_dir)
    path = root / _ARTIFACT
    if not path.is_file():
        raise FileNotFoundError(f"canonical artifact missing: {path}")
    blob = path.read_bytes()
    _verify_manifest(root, blob)
    with np.load(io.BytesIO(blob), allow_pickle=False) as data:
        weights = np.array(data["weights"], dtype=np.float64, copy=True)
        bias = float(data["bias"])
        wh = None
        if "input_wh" in data.files:
            wh = tuple(int(v) for v in np.array(data["input_wh"], copy=True).reshape(-1))
    if weights.ndim != 1 or weights.size == 0 or not np.isfinite(weights).all():
        raise ValueError("weights must be a non-empty finite vector")
    if not math.isfinite(bias):
        raise ValueError("bias must be finite")
    if wh is not None and (
        len(wh) != 2 or wh[0] < 1 or wh[1] < 1 or wh[0] * wh[1] != int(weights.size)
    ):
        raise ValueError(f"input_wh {wh} does not match weights {weights.size}")
    return {"weights": weights, "bias": bias, "artifact": _ARTIFACT}


def input_fn(body: str | bytes, content_type: str) -> np.ndarray:
    if content_type.split(";")[0].strip().lower() != "application/json":
        raise ValueError(f"unsupported content type {content_type}")
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    for key in payload:
        if str(key).lower() in _FORBIDDEN:
            raise ValueError(f"refusing payload field {key}")
    privacy = payload.get("privacy")
    if privacy not in _PRIVACY:
        raise ValueError("refusing payload that is not privacy=blur or privacy=silhouette")
    if payload.get("artifact") not in (None, _ARTIFACT):
        raise ValueError(f"artifact must be {_ARTIFACT}")
    feats = payload.get("features")
    if not isinstance(feats, list) or not feats:
        raise ValueError("features must be a non-empty list")
    if len(feats) > _MAX_FEATURES:
        raise ValueError(f"features longer than {_MAX_FEATURES}")
    vec = np.asarray(feats, dtype=np.float64)
    if vec.ndim != 1 or not np.isfinite(vec).all():
        raise ValueError("features must be a finite 1-d vector")
    if float(vec.min()) < -1e-6 or float(vec.max()) > 1.0 + 1e-6:
        raise ValueError("features must be in [0, 1]")
    return vec


def _sigmoid(features: np.ndarray, weights: np.ndarray, bias: float) -> float:
    if features.shape[0] != weights.shape[0]:
        raise ValueError(
            f"feature size {features.shape[0]} != weights {weights.shape[0]}"
        )
    z = float(features @ weights + bias)
    z = min(40.0, max(-40.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def predict_fn(features: np.ndarray, model: dict) -> dict:
    score = _sigmoid(features, model["weights"], model["bias"])
    return {"score": score, "artifact": model["artifact"]}


def output_fn(prediction: dict, accept: str) -> tuple[str, str]:
    if not isinstance(prediction, dict) or "score" not in prediction:
        raise ValueError("prediction must include score")
    base = (accept or "application/json").split(";")[0].strip().lower()
    if base not in {"application/json", "*/*", ""}:
        raise ValueError(f"unsupported accept {accept}")
    return json.dumps(prediction), "application/json"
