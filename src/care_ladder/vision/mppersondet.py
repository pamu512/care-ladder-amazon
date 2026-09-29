"""Person detection via OpenCV 5 DNN + MediaPipe person-detection model (ONNX).

Vendored from opencv_zoo ``mp_persondet.py`` (Apache-2.0, OpenCV maintainers) with one
fix for OpenCV 5's DNN graph engine: the two output blobs come back in a different
order (scores ↔ box/landmark deltas), so ``forward`` output is reordered before
postprocessing. Model file: ``models/person_detection_mediapipe_2023mar.onnx``
(downloaded from opencv/opencv_zoo via Git LFS media URL; NOT committed).

Non-clinical demo component.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import cv2 as cv


class MPPersonDet:
    def __init__(
        self,
        modelPath,
        nmsThreshold=0.3,
        scoreThreshold=0.5,
        topK=5000,
        backendId=0,
        targetId=0,
    ):
        self.model_path = modelPath
        self.nms_threshold = nmsThreshold
        self.score_threshold = scoreThreshold
        self.topK = topK
        self.backend_id = backendId
        self.target_id = targetId

        self.model = self._build_model(modelPath)
        # OpenCV 5 Net lacks getInputs(); MediaPipe person det input is 224x224
        # (verified: 224 -> 2254 anchors, matching the vendored anchor set).
        self.input_size = np.array([224, 224])

        self._anchors = self._load_anchors()

    def _build_model(self, model_path):
        net = cv.dnn.readNet(model_path)

        net.setPreferableBackend(self.backend_id)
        net.setPreferableTarget(self.target_id)
        return net

    def setBackendAndTarget(self, backendId, targetId):
        self.backend_id = backendId
        self.target_id = targetId
        self.model.setPreferableBackend(self.backend_id)
        self.model.setPreferableTarget(self.target_id)

    def name(self):
        return self.__class__.__name__

    def _preprocess(self, image):
        pad_bias = np.array([0.0, 0.0])  # left, top
        image = cv.cvtColor(image, cv.COLOR_BGR2RGB)
        image = image.astype(np.float32) / 255.0  # norm
        image = (image - 0.5) * 2  # [0, 1] -> [-1, 1]

        ratio = min(self.input_size / image.shape[:2])
        if image.shape[0] != self.input_size[0] or image.shape[1] != self.input_size[1]:
            # keep aspect ratio when resize
            ratio_size = (np.array(image.shape[:2]) * ratio).astype(np.int32)
            image = cv.resize(image, (ratio_size[1], ratio_size[0]))
            pad_h = self.input_size[0] - ratio_size[0]
            pad_w = self.input_size[1] - ratio_size[1]
            pad_bias[0] = left = pad_w // 2
            pad_bias[1] = top = pad_h // 2
            right = pad_w - left
            bottom = pad_h - top
            image = cv.copyMakeBorder(
                image, top, bottom, left, right, cv.BORDER_CONSTANT, None, (0, 0, 0)
            )

        blob = np.transpose(image, [2, 0, 1])
        pad_bias = (pad_bias / ratio).astype(np.int32)
        return blob[np.newaxis, :, :, :], pad_bias  # chw -> nchw

    def infer(self, image):
        h, w, _ = image.shape

        # Preprocess
        input_blob, pad_bias = self._preprocess(image)

        # Forward
        self.model.setInput(input_blob)
        output_blob = self.model.forward(self.model.getUnconnectedOutLayersNames())

        # OpenCV 5 graph-engine fix: outputs arrive as [scores, deltas] but the
        # zoo postprocess expects [deltas, scores]. Identify by trailing dim
        # (scores=1, deltas=12).
        if output_blob[0].shape[-1] != 12:
            output_blob = [output_blob[1], output_blob[0]]

        # Postprocess
        results = self._postprocess(output_blob, np.array([w, h]), pad_bias)

        return results

    def _postprocess(self, output_blob, original_shape, pad_bias):
        score = output_blob[1][0, :, 0]
        box_delta = output_blob[0][0, :, 0:4]
        landmark_delta = output_blob[0][0, :, 4:]
        scale = max(original_shape)

        # get scores
        score = score.astype(np.float64)
        score = np.clip(score, -100, 100)
        score = 1 / (1 + np.exp(-score))

        # get boxes
        cxy_delta = box_delta[:, :2] / self.input_size
        wh_delta = box_delta[:, 2:] / self.input_size
        xy1 = (cxy_delta - wh_delta / 2 + self._anchors) * scale
        xy2 = (cxy_delta + wh_delta / 2 + self._anchors) * scale
        boxes = np.concatenate([xy1, xy2], axis=1)
        boxes -= [pad_bias[0], pad_bias[1], pad_bias[0], pad_bias[1]]
        # NMS
        keep_idx = cv.dnn.NMSBoxes(
            boxes.tolist(),
            score.tolist(),
            self.score_threshold,
            self.nms_threshold,
            top_k=self.topK,
        )
        if len(keep_idx) == 0:
            return np.empty(shape=(0, 13))
        if isinstance(keep_idx, np.ndarray) and keep_idx.ndim > 1:
            keep_idx = keep_idx.flatten()
        selected_score = score[keep_idx]
        selected_box = boxes[keep_idx]

        # get landmarks
        selected_landmarks = landmark_delta[keep_idx].reshape(-1, 4, 2)
        selected_landmarks = selected_landmarks / self.input_size
        selected_anchors = self._anchors[keep_idx]
        for idx, landmark in enumerate(selected_landmarks):
            landmark += selected_anchors[idx]
        selected_landmarks *= scale
        selected_landmarks -= pad_bias

        # each row: [x1, y1, x2, y2, landmarks(8), score]
        return np.c_[
            selected_box.reshape(-1, 4),
            selected_landmarks.reshape(-1, 8),
            selected_score.reshape(-1, 1),
        ]

    def _load_anchors(self) -> np.ndarray:
        from care_ladder.vision.anchors import load_anchors

        return load_anchors()


def detect_people(
    frame: np.ndarray, detector: MPPersonDet | None = None
) -> list[dict[str, Any]]:
    """Convenience wrapper → list of person boxes sorted by score (desc)."""
    if detector is None:
        import functools
        from pathlib import Path

        model = Path(__file__).resolve().parents[2].parents[1] / "models" / "person_detection_mediapipe_2023mar.onnx"
        detector = functools.lru_cache(maxsize=1)(_lazy_factory)(str(model))
    rows = detector.infer(frame)
    out = []
    for r in rows:
        x1, y1, x2, y2 = (float(v) for v in r[:4])
        score = float(r[12])
        out.append(
            {
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
                "w": x2 - x1, "h": y2 - y1,
                "score": score,
            }
        )
    return sorted(out, key=lambda b: -b["score"])


_LAZY: dict[str, MPPersonDet] = {}


def _lazy_factory(path: str) -> MPPersonDet:
    if path not in _LAZY:
        _LAZY[path] = MPPersonDet(path)
    return _LAZY[path]
