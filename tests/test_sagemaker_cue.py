"""SageMaker cue path: mocked endpoint, canonical npz, no live AWS."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from care_ladder.aws_shape import validate_payload
from care_ladder.plan_loader import load_care_plan
from care_ladder.vision.cues import CueDetector
from care_ladder.vision.fall_train import FallFrameClassifier, train_logistic
from care_ladder.vision.sagemaker_cue import (
    SageMakerCueError,
    SageMakerCueScorer,
    local_self_check,
    resolve_fall_classifier,
    serverless_endpoint_config,
)

PLAN = Path(__file__).resolve().parents[1] / "configs" / "demo_home.yaml"


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeRuntime:
    def __init__(self, score: float = 0.91, boom: BaseException | None = None) -> None:
        self.score = score
        self.boom = boom
        self.bodies: list[dict] = []

    def invoke_endpoint(self, **kwargs):
        if self.boom:
            raise self.boom
        self.bodies.append(json.loads(kwargs["Body"]))
        return {"Body": _Body(json.dumps({"score": self.score}).encode("utf-8"))}


def _color_frame() -> np.ndarray:
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    frame[:, :] = (18, 18, 18)
    frame[15:65, 30:50] = (20, 20, 220)
    return frame


def test_create_model_shape_accepts_npz_container():
    from care_ladder.vision.sagemaker_cue import _sample_model_request

    validate_payload("sagemaker", "CreateModel", _sample_model_request())
    validate_payload(
        "sagemaker",
        "CreateEndpoint",
        {"EndpointName": "care-ladder-cue", "EndpointConfigName": "care-ladder-cue"},
    )


def test_serverless_config_is_inside_production_variant():
    payload = serverless_endpoint_config("care-ladder-cue", "care-ladder-cue")
    variant = payload["ProductionVariants"][0]
    assert "InstanceType" not in variant
    assert variant["ServerlessConfig"]["MemorySizeInMB"] == 1024
    assert variant["ServerlessConfig"]["MaxConcurrency"] == 1


def test_local_package_matches_npz_math():
    assert "local-mode self-check ok" in local_self_check()


def test_resolve_uses_local_npz_when_endpoint_unset(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CARE_LADDER_SAGEMAKER_ENDPOINT", raising=False)
    missing = tmp_path / "missing.npz"
    assert resolve_fall_classifier(missing) is None
    clf = train_logistic(
        np.vstack([np.full((4, 4), 0.1), np.full((4, 4), 0.9)]),
        np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.float64),
        epochs=5,
        input_wh=(2, 2),
    )
    path = tmp_path / "fall_classifier.npz"
    clf.save(path)
    loaded = resolve_fall_classifier(path)
    assert isinstance(loaded, FallFrameClassifier)


def test_resolve_does_not_call_boto_until_predict(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_SAGEMAKER_ENDPOINT", "care-ladder-cue")

    def boom():
        raise AssertionError("runtime client built before predict")

    monkeypatch.setattr("care_ladder.vision.sagemaker_cue._runtime_client", boom)
    scorer = resolve_fall_classifier(Path("/no/such/fall_classifier.npz"))
    assert isinstance(scorer, SageMakerCueScorer)
    assert scorer.input_wh == (32, 32)


def test_scorer_sends_privacy_features_and_returns_endpoint_score():
    fake = FakeRuntime(score=0.91)
    scorer = SageMakerCueScorer("care-ladder-cue", runtime_client=fake, input_wh=(32, 32))
    score = scorer.predict_proba(_color_frame(), (30.0, 15.0, 50.0, 65.0))
    assert score == pytest.approx(0.91)
    body = fake.bodies[0]
    assert body["artifact"] == "fall_classifier.npz"
    assert body["privacy"] in {"blur", "silhouette"}
    assert len(body["features"]) == 1024
    assert "frame" not in body and "image" not in body
    assert scorer.last_privacy == body["privacy"]


def test_observe_records_sagemaker_source(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_SAGEMAKER_ENDPOINT", "care-ladder-cue")
    fake = FakeRuntime(0.91)
    monkeypatch.setattr(
        "care_ladder.vision.sagemaker_cue._runtime_client",
        lambda: fake,
    )
    det = CueDetector.from_plan(load_care_plan(PLAN), zone_id="living_room")
    det.distress_sustain_sec = 0.0
    det.fall_score_threshold = 0.5
    det.enable_no_movement = False
    det.enable_no_visibility = False
    cue = det.observe(_color_frame(), t=0.0)
    assert cue is not None
    assert cue.detail["source"] == "sagemaker_fall_classifier"
    assert cue.detail["artifact"] == "fall_classifier.npz"
    assert cue.detail["endpoint"] == "care-ladder-cue"
    assert cue.detail["privacy"] in {"blur", "silhouette"}
    assert "not a medical diagnosis" in cue.detail["note"]


def test_endpoint_error_does_not_fall_back_to_local_weights(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CARE_LADDER_SAGEMAKER_ENDPOINT", "care-ladder-cue")
    path = tmp_path / "fall_classifier.npz"
    clf = train_logistic(
        np.vstack([np.zeros((4, 1024)), np.ones((4, 1024))]),
        np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.float64),
        epochs=5,
    )
    clf.save(path)
    monkeypatch.setattr(
        "care_ladder.vision.fall_train.default_weights_path",
        lambda: path,
    )
    fake = FakeRuntime(boom=RuntimeError("endpoint down"))
    det = CueDetector.from_plan(load_care_plan(PLAN), zone_id="living_room")
    assert isinstance(det.fall_classifier, SageMakerCueScorer)
    det.fall_classifier._runtime = fake
    det.enable_no_movement = False
    det.enable_no_visibility = False
    assert det.observe(_color_frame(), t=0.0) is None
    assert det.last_fall_error is not None
    assert "endpoint down" in det.last_fall_error
    assert "endpoint down" in (det.fall_classifier.last_error or "")


def test_bad_endpoint_name_is_rejected():
    with pytest.raises(SageMakerCueError):
        SageMakerCueScorer("has spaces", runtime_client=FakeRuntime())
    with pytest.raises(SageMakerCueError):
        SageMakerCueScorer("care-ladder-", runtime_client=FakeRuntime())


def test_blank_endpoint_env_stays_on_local_npz(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CARE_LADDER_SAGEMAKER_ENDPOINT", "   ")
    assert resolve_fall_classifier(tmp_path / "missing.npz") is None


def test_scorer_rejects_non_probability_payloads():
    frame = _color_frame()
    box = (30.0, 15.0, 50.0, 65.0)
    bodies = (
        b'{"score": 1.5}',
        b'{"score": true}',
        b'{"score": null}',
        b"[]",
        b'{"nope": 1}',
        b"not-json",
    )
    for body in bodies:
        class _Runtime:
            def invoke_endpoint(self, **kwargs):
                return {"Body": body}

        scorer = SageMakerCueScorer(
            "care-ladder-cue", runtime_client=_Runtime(), input_wh=(32, 32)
        )
        with pytest.raises(SageMakerCueError):
            scorer.predict_proba(frame, box)
        assert scorer.last_error


def test_scorer_accepts_raw_bytes_body():
    class _Runtime:
        def invoke_endpoint(self, **kwargs):
            return {"Body": b'{"score": 0.25}'}

    scorer = SageMakerCueScorer(
        "care-ladder-cue", runtime_client=_Runtime(), input_wh=(32, 32)
    )
    assert scorer.predict_proba(_color_frame(), (30.0, 15.0, 50.0, 65.0)) == pytest.approx(
        0.25
    )


def test_endpoint_error_does_not_emit_cue_when_threshold_is_zero(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_SAGEMAKER_ENDPOINT", "care-ladder-cue")
    fake = FakeRuntime(boom=RuntimeError("endpoint down"))
    monkeypatch.setattr("care_ladder.vision.sagemaker_cue._runtime_client", lambda: fake)
    det = CueDetector.from_plan(load_care_plan(PLAN), zone_id="living_room")
    det.fall_classifier._runtime = fake
    det.fall_score_threshold = 0.0
    det.distress_sustain_sec = 0.0
    det.enable_no_movement = False
    det.enable_no_visibility = False
    cue = det.observe(_color_frame(), t=0.0)
    assert det.last_fall_score is None
    assert det.last_fall_error is not None
    if cue is not None:
        assert cue.detail.get("source") != "sagemaker_fall_classifier"


def test_create_rolls_back_model_when_config_fails():
    from care_ladder.vision.sagemaker_cue import provision_serverless_endpoint

    class _SM:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_model(self, **kwargs):
            self.calls.append("create_model")

        def create_endpoint_config(self, **kwargs):
            raise RuntimeError("config rejected")

        def create_endpoint(self, **kwargs):
            raise AssertionError("endpoint created after config failure")

        def delete_model(self, **kwargs):
            self.calls.append(f"delete_model:{kwargs['ModelName']}")

        def delete_endpoint_config(self, **kwargs):
            self.calls.append("delete_endpoint_config")

    sm = _SM()
    with pytest.raises(RuntimeError, match="config rejected"):
        provision_serverless_endpoint(
            sm,
            model_payload={"ModelName": "care-ladder-cue"},
            config_payload={},
            endpoint_payload={},
        )
    assert sm.calls == ["create_model", "delete_model:care-ladder-cue"]


def test_deploy_and_delete_flags_conflict(capsys):
    from care_ladder.vision.sagemaker_cue import main

    assert main(["--deploy", "--delete"]) == 2
    assert "only one" in capsys.readouterr().out


def test_deploy_blocked_without_spend_gate(monkeypatch, capsys):
    from care_ladder.vision.sagemaker_cue import main

    monkeypatch.delenv("CARE_LADDER_SAGEMAKER_DEPLOY", raising=False)
    assert main(["--deploy"]) == 2
    assert "CARE_LADDER_SAGEMAKER_DEPLOY" in capsys.readouterr().out


def test_swapped_npz_fails_manifest_check(tmp_path: Path):
    import io
    import tarfile

    from care_ladder.vision.sagemaker_cue import package_model, score_packaged_tar

    def _fit(seed: int) -> FallFrameClassifier:
        rng = np.random.default_rng(seed)
        return train_logistic(
            rng.random((8, 4)),
            np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.float64),
            epochs=2,
            input_wh=(2, 2),
        )

    first = tmp_path / "fall_classifier.npz"
    second = tmp_path / "nested" / "fall_classifier.npz"
    _fit(0).save(first)
    _fit(1).save(second)
    tar_path = tmp_path / "model.tar.gz"
    package_model(first, tar_path)
    with tarfile.open(tar_path, "r:gz") as src:
        members = {
            member.name: src.extractfile(member).read()
            for member in src.getmembers()
            if member.isfile()
        }
    members["fall_classifier.npz"] = second.read_bytes()
    swapped = tmp_path / "swapped.tar.gz"
    with tarfile.open(swapped, "w:gz") as out:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            out.addfile(info, io.BytesIO(data))
    with pytest.raises(SageMakerCueError, match="sha256"):
        score_packaged_tar(swapped, np.zeros(4), privacy="blur")


def test_inference_rejects_raw_frame_and_bad_accept():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "infra" / "sagemaker" / "inference.py"
    spec = importlib.util.spec_from_file_location("sm_inference_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="frame"):
        module.input_fn(
            '{"features": [0.1], "privacy": "blur", "frame": "abc"}',
            "application/json",
        )
    with pytest.raises(ValueError, match="accept"):
        module.output_fn({"score": 0.2}, "text/csv")
