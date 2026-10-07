"""SageMaker cue scoring. Canonical weights stay in models/fall_classifier.npz.

Unset CARE_LADDER_SAGEMAKER_ENDPOINT: CueDetector uses that npz locally.
Set it: this client sends a blurred or silhouette feature vector and the
endpoint applies the same npz. Raw frames are not part of the payload.
There is no ONNX export.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from care_ladder.aws_shape import AwsShapeError, input_shape, validate_payload
from care_ladder.vision.fall_train import (
    FallFrameClassifier,
    load_trained_classifier,
    privacy_features,
    repo_root,
    sigmoid_score,
)

logger = logging.getLogger("care_ladder.sagemaker")

ENDPOINT_ENV = "CARE_LADDER_SAGEMAKER_ENDPOINT"
DEPLOY_ENV = "CARE_LADDER_SAGEMAKER_DEPLOY"
CANONICAL_ARTIFACT = "fall_classifier.npz"
_ENDPOINT_NAME = re.compile(r"^[A-Za-z0-9](?:-?[A-Za-z0-9]){0,62}$")


class SageMakerCueError(RuntimeError):
    """The endpoint contract or a local package step failed."""


def endpoint_name() -> str | None:
    name = os.environ.get(ENDPOINT_ENV, "").strip()
    return name or None


def _check_endpoint_name(name: str) -> str:
    if not _ENDPOINT_NAME.fullmatch(name):
        raise SageMakerCueError(
            f"{ENDPOINT_ENV} must be 1-63 letters, digits, or single hyphens: {name!r}"
        )
    return name


def _runtime_client() -> Any:
    import boto3
    from botocore.config import Config

    kwargs: dict[str, Any] = {
        "config": Config(
            connect_timeout=2,
            read_timeout=8,
            retries={"max_attempts": 2, "mode": "standard"},
        )
    }
    region = (
        os.environ.get("CARE_LADDER_SAGEMAKER_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    if region:
        kwargs["region_name"] = region
    return boto3.client("sagemaker-runtime", **kwargs)


def _read_body(body: Any) -> bytes:
    if isinstance(body, str):
        return body.encode("utf-8")
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if body is None or not hasattr(body, "read"):
        raise SageMakerCueError("endpoint response has no Body")
    data = body.read()
    if isinstance(data, str):
        return data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray)):
        raise SageMakerCueError("endpoint body is not bytes")
    return bytes(data)


def _parse_score(resp: Any) -> float:
    if not isinstance(resp, dict) or "Body" not in resp:
        raise SageMakerCueError("endpoint response has no Body")
    try:
        payload = json.loads(_read_body(resp["Body"]))
    except SageMakerCueError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SageMakerCueError(f"endpoint body is not JSON: {exc}") from exc
    if not isinstance(payload, dict) or "score" not in payload:
        raise SageMakerCueError("endpoint JSON must be an object with score")
    score_val = payload["score"]
    if isinstance(score_val, bool) or not isinstance(score_val, (int, float)):
        raise SageMakerCueError(
            f"endpoint score must be a number, got {type(score_val).__name__}"
        )
    score = float(score_val)
    if not np.isfinite(score) or not 0.0 <= score <= 1.0:
        raise SageMakerCueError(f"endpoint score out of range: {score}")
    return score


class SageMakerCueScorer:
    """predict_proba(frame, box) via InvokeEndpoint. Same call shape as the npz classifier."""

    def __init__(
        self,
        endpoint_name: str,
        *,
        runtime_client: Any | None = None,
        input_wh: tuple[int, int] = (32, 32),
    ) -> None:
        self.endpoint_name = _check_endpoint_name(endpoint_name)
        self._runtime = runtime_client
        self.input_wh = (int(input_wh[0]), int(input_wh[1]))
        self.last_error: str | None = None
        self.last_privacy: str | None = None
        self._logged_error: str | None = None

    def _client(self) -> Any:
        if self._runtime is None:
            self._runtime = _runtime_client()
        return self._runtime

    def predict_proba(
        self, frame: np.ndarray, box: tuple[float, float, float, float] | None = None
    ) -> float:
        vector, privacy = privacy_features(frame, box, self.input_wh)
        if vector.shape != (self.input_wh[0] * self.input_wh[1],):
            raise SageMakerCueError(
                f"feature size {vector.shape[0]} != {self.input_wh[0] * self.input_wh[1]}"
            )
        body = {
            "features": [float(v) for v in vector],
            "artifact": CANONICAL_ARTIFACT,
            "privacy": privacy,
        }
        if "frame" in body or "image" in body:
            raise SageMakerCueError("refusing to attach a frame to the endpoint body")
        self.last_privacy = privacy
        try:
            score = _parse_score(
                self._client().invoke_endpoint(
                    EndpointName=self.endpoint_name,
                    ContentType="application/json",
                    Accept="application/json",
                    Body=json.dumps(body).encode("utf-8"),
                )
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self._logged_error != self.last_error:
                # ponytail: one warning per distinct error. A dead endpoint
                # would otherwise log on every camera frame. Upgrade: a counter.
                logger.warning(
                    "SageMaker cue invoke failed endpoint=%s error=%s",
                    self.endpoint_name,
                    self.last_error,
                )
                self._logged_error = self.last_error
            raise
        self.last_error = None
        return score


def resolve_fall_classifier(
    path: Path | None = None,
    runtime_client: Any | None = None,
) -> FallFrameClassifier | SageMakerCueScorer | None:
    """Local npz when the endpoint env is unset. SageMaker scorer when it is set."""
    local = load_trained_classifier(path)
    name = endpoint_name()
    if not name:
        return local
    wh = local.input_wh if local is not None else (32, 32)
    return SageMakerCueScorer(name, runtime_client=runtime_client, input_wh=wh)


def inference_source() -> Path:
    return repo_root() / "infra" / "sagemaker" / "inference.py"


def package_model(npz_path: Path, dest: Path) -> Path:
    """Tar the npz plus infra/sagemaker/inference.py. Same weights, not a conversion."""
    npz_path = Path(npz_path)
    dest = Path(dest)
    if not npz_path.is_file():
        raise SageMakerCueError(f"canonical npz missing: {npz_path}")
    if npz_path.name != CANONICAL_ARTIFACT:
        raise SageMakerCueError(
            f"package expects {CANONICAL_ARTIFACT}, got {npz_path.name}"
        )
    source = inference_source()
    if not source.is_file():
        raise SageMakerCueError(f"inference entrypoint missing: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(npz_path.read_bytes()).hexdigest()
    manifest = json.dumps(
        {
            "artifact": CANONICAL_ARTIFACT,
            "format": "npz",
            "sha256": digest,
            "onnx": False,
        }
    ).encode("utf-8")
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(npz_path, arcname=CANONICAL_ARTIFACT)
        tar.add(source, arcname="code/inference.py")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return dest


def score_packaged_tar(tar_path: Path, features: np.ndarray, *, privacy: str = "blur") -> float:
    """Run the tar's inference.py. Proves the packaged entrypoint matches the npz math."""
    import importlib.util

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(root, filter="data")
        entry = root / "code" / "inference.py"
        spec = importlib.util.spec_from_file_location("care_ladder_sm_inference", entry)
        if spec is None or spec.loader is None:
            raise SageMakerCueError(f"could not load {entry}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            model = module.model_fn(str(root))
            body = json.dumps(
                {
                    "features": [float(v) for v in features],
                    "privacy": privacy,
                    "artifact": CANONICAL_ARTIFACT,
                }
            )
            parsed = module.input_fn(body, "application/json")
            pred = module.predict_fn(parsed, model)
            rendered, ctype = module.output_fn(pred, "application/json")
        except SageMakerCueError:
            raise
        except Exception as exc:
            raise SageMakerCueError(str(exc)) from exc
        if ctype != "application/json":
            raise SageMakerCueError(f"unexpected content type {ctype}")
        return float(json.loads(rendered)["score"])


def serverless_endpoint_config(config_name: str, model_name: str) -> dict[str, Any]:
    """CreateEndpointConfig body with ServerlessConfig inside ProductionVariants."""
    shape = input_shape("sagemaker", "CreateEndpointConfig")
    variants = shape.members["ProductionVariants"].member
    if "ServerlessConfig" not in variants.members:
        from care_ladder.aws_shape import shape_summary

        raise SageMakerCueError(
            "pinned boto3 ProductionVariant has no ServerlessConfig\n"
            + shape_summary(variants)
        )
    variant: dict[str, Any] = {
        "VariantName": "AllTraffic",
        "ModelName": model_name,
        "ServerlessConfig": {"MemorySizeInMB": 1024, "MaxConcurrency": 1},
    }
    if "InitialVariantWeight" in set(getattr(variants, "required_members", []) or []):
        variant["InitialVariantWeight"] = 1.0
    payload = {"EndpointConfigName": config_name, "ProductionVariants": [variant]}
    validate_payload("sagemaker", "CreateEndpointConfig", payload)
    return payload


def _sample_model_request() -> dict[str, Any]:
    return {
        "ModelName": "care-ladder-cue",
        "ExecutionRoleArn": "arn:aws:iam::000000000000:role/CareLadderSageMaker",
        "PrimaryContainer": {
            "Image": (
                "763104351884.dkr.ecr.us-east-1.amazonaws.com/"
                "sagemaker-scikit-learn:1.2-1-cpu-py3"
            ),
            "ModelDataUrl": "s3://example-bucket/care-ladder/cue/model.tar.gz",
            "Environment": {"SAGEMAKER_PROGRAM": "inference.py"},
        },
    }


def local_self_check() -> str:
    """Synthetic separable vectors through the npz and the packaged entrypoint.

    Does not write models/fall_classifier.npz and is not a Kaggle metric.
    """
    from care_ladder.vision.fall_train import train_logistic

    rng = np.random.default_rng(0)
    dim = 32 * 32
    low = np.clip(rng.normal(0.2, 0.02, size=(8, dim)), 0.0, 1.0)
    high = np.clip(rng.normal(0.8, 0.02, size=(8, dim)), 0.0, 1.0)
    matrix = np.vstack([low, high])
    labels = np.array([0.0] * 8 + [1.0] * 8)
    clf = train_logistic(matrix, labels, epochs=40, lr=0.8, seed=0)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        npz = root / CANONICAL_ARTIFACT
        tar = root / "model.tar.gz"
        clf.save(npz, slug="self-check")
        package_model(npz, tar)
        vector = matrix[0]
        local = sigmoid_score(vector, clf.weights, clf.bias)
        packaged = score_packaged_tar(tar, vector, privacy="blur")
    if abs(local - packaged) > 1e-6:
        raise SageMakerCueError(
            f"packaged inference {packaged} != npz sigmoid {local}"
        )
    return "local-mode self-check ok (synthetic features, not the Kaggle artifact)"


def _artifact_line() -> str:
    path = repo_root() / "models" / CANONICAL_ARTIFACT
    if not path.is_file():
        return (
            f"canonical artifact: models/{CANONICAL_ARTIFACT} "
            "(format=npz, no ONNX; file not on disk yet)"
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (
        f"canonical artifact: models/{CANONICAL_ARTIFACT} "
        f"format=npz sha256={digest} onnx=false"
    )


def _rollback_call(client: Any, method: str, kwargs: dict[str, Any]) -> None:
    fn = getattr(client, method, None)
    if fn is None:
        return
    try:
        fn(**kwargs)
    except Exception as exc:
        logger.warning("rollback %s failed: %s", method, type(exc).__name__)


def provision_serverless_endpoint(
    sm: Any,
    *,
    model_payload: dict[str, Any],
    config_payload: dict[str, Any],
    endpoint_payload: dict[str, Any],
) -> dict[str, Any]:
    """Create model, config, then endpoint. Drop the earlier resources if a later call fails."""
    name = str(model_payload["ModelName"])
    created_model = False
    created_config = False
    try:
        sm.create_model(**model_payload)
        created_model = True
        sm.create_endpoint_config(**config_payload)
        created_config = True
        created = sm.create_endpoint(**endpoint_payload)
    except Exception:
        if created_config:
            _rollback_call(sm, "delete_endpoint_config", {"EndpointConfigName": name})
        if created_model:
            _rollback_call(sm, "delete_model", {"ModelName": name})
        raise
    if not isinstance(created, dict):
        _rollback_call(sm, "delete_endpoint", {"EndpointName": name})
        _rollback_call(sm, "delete_endpoint_config", {"EndpointConfigName": name})
        _rollback_call(sm, "delete_model", {"ModelName": name})
        raise SageMakerCueError("CreateEndpoint returned no payload")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Care Ladder SageMaker cue model")
    parser.add_argument(
        "--local",
        action="store_true",
        help="run the synthetic package self-check (default)",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help=f"create a serverless endpoint (also requires {DEPLOY_ENV}=1)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete the cue endpoint, config, and model",
    )
    args = parser.parse_args(argv)
    if args.deploy and args.delete:
        print("BLOCKER: pass only one of --deploy or --delete")
        return 2
    try:
        print(_artifact_line())
        config = serverless_endpoint_config("care-ladder-cue", "care-ladder-cue")
        variant = config["ProductionVariants"][0]
        print(
            "ServerlessConfig inside ProductionVariants: "
            f"MemorySizeInMB={variant['ServerlessConfig']['MemorySizeInMB']} "
            f"MaxConcurrency={variant['ServerlessConfig']['MaxConcurrency']}"
        )
        validate_payload("sagemaker", "CreateModel", _sample_model_request())
        validate_payload(
            "sagemaker",
            "CreateEndpoint",
            {"EndpointName": "care-ladder-cue", "EndpointConfigName": "care-ladder-cue"},
        )
        print("CreateModel and CreateEndpoint shapes accepted by pinned boto3")
        print(local_self_check())
        if args.delete:
            return _delete_endpoint()
        if args.deploy:
            return _deploy_endpoint()
        print(
            "endpoint: deferred "
            f"({DEPLOY_ENV} is not 1; local npz remains the fallback)"
        )
        print(
            "tear-down: python -m care_ladder.vision.sagemaker_cue --delete "
            "after a demo. Unset CARE_LADDER_SAGEMAKER_ENDPOINT to force the npz."
        )
        return 0
    except (SageMakerCueError, AwsShapeError, OSError, ValueError) as exc:
        print(f"BLOCKER: {exc}")
        return 2


def _deploy_endpoint() -> int:
    if os.environ.get(DEPLOY_ENV, "").strip() != "1":
        print(f"BLOCKER: pass --deploy only with {DEPLOY_ENV}=1 (spend gate)")
        return 2
    role = os.environ.get("CARE_LADDER_SAGEMAKER_ROLE_ARN", "").strip()
    bucket = os.environ.get("CARE_LADDER_SAGEMAKER_BUCKET", "").strip()
    image = os.environ.get("CARE_LADDER_SAGEMAKER_IMAGE", "").strip()
    npz = repo_root() / "models" / CANONICAL_ARTIFACT
    missing = [
        name
        for name, value in (
            ("CARE_LADDER_SAGEMAKER_ROLE_ARN", role),
            ("CARE_LADDER_SAGEMAKER_BUCKET", bucket),
            ("CARE_LADDER_SAGEMAKER_IMAGE", image),
        )
        if not value
    ]
    gaps = list(missing)
    if not npz.is_file():
        gaps.append("models/" + CANONICAL_ARTIFACT)
    if any(token in bucket for token in ("/", " ", "s3:")):
        gaps.append("CARE_LADDER_SAGEMAKER_BUCKET (bucket name only)")
    if gaps:
        print("BLOCKER: deploy needs " + ", ".join(gaps))
        return 2
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, WaiterError

    region = os.environ.get("CARE_LADDER_SAGEMAKER_REGION") or os.environ.get("AWS_REGION")
    sm = boto3.client("sagemaker", region_name=region) if region else boto3.client("sagemaker")
    s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    name = "care-ladder-cue"
    key = "care-ladder/cue/model.tar.gz"
    uploaded = False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tar = package_model(npz, Path(tmp) / "model.tar.gz")
            s3.upload_file(
                str(tar),
                bucket,
                key,
                ExtraArgs={"ServerSideEncryption": "AES256"},
            )
        uploaded = True
        model_payload = {
            "ModelName": name,
            "ExecutionRoleArn": role,
            "PrimaryContainer": {
                "Image": image,
                "ModelDataUrl": f"s3://{bucket}/{key}",
                "Environment": {"SAGEMAKER_PROGRAM": "inference.py"},
            },
        }
        validate_payload("sagemaker", "CreateModel", model_payload)
        config_payload = serverless_endpoint_config(name, name)
        endpoint_payload = {"EndpointName": name, "EndpointConfigName": name}
        validate_payload("sagemaker", "CreateEndpoint", endpoint_payload)
        created = provision_serverless_endpoint(
            sm,
            model_payload=model_payload,
            config_payload=config_payload,
            endpoint_payload=endpoint_payload,
        )
        arn = created.get("EndpointArn", "")
        print(f"endpoint: {arn or name}")
        waiter = sm.get_waiter("endpoint_in_service")
        waiter.wait(EndpointName=name, WaiterConfig={"Delay": 15, "MaxAttempts": 40})
    except (
        ClientError,
        WaiterError,
        BotoCoreError,
        SageMakerCueError,
        AwsShapeError,
        OSError,
    ) as exc:
        print(f"BLOCKER: {exc}")
        if uploaded:
            print(
                f"S3 object left at s3://{bucket}/{key}; delete it if you are not retrying. "
                "If the endpoint was created, run --delete with the spend gate set."
            )
        return 2
    print(f"set {ENDPOINT_ENV}={name}")
    return 0


def _delete_endpoint() -> int:
    if os.environ.get(DEPLOY_ENV, "").strip() != "1":
        print(f"BLOCKER: pass --delete only with {DEPLOY_ENV}=1")
        return 2
    import boto3
    from botocore.exceptions import ClientError

    region = os.environ.get("CARE_LADDER_SAGEMAKER_REGION") or os.environ.get("AWS_REGION")
    sm = boto3.client("sagemaker", region_name=region) if region else boto3.client("sagemaker")
    name = "care-ladder-cue"
    for method, kwargs in (
        ("delete_endpoint", {"EndpointName": name}),
        ("delete_endpoint_config", {"EndpointConfigName": name}),
        ("delete_model", {"ModelName": name}),
    ):
        try:
            getattr(sm, method)(**kwargs)
            print(f"deleted {method} {name}")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            message = str(exc.response.get("Error", {}).get("Message", ""))
            gone = code in {"ResourceNotFound", "ResourceNotFoundException"} or (
                code == "ValidationException" and "could not find" in message.lower()
            )
            if gone:
                print(f"already gone {method} {name}")
                continue
            print(f"BLOCKER: {exc}")
            return 2
    print(f"unset {ENDPOINT_ENV} so CueDetector uses the local npz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
