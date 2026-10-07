# SageMaker cue endpoint

Canonical artifact: `models/fall_classifier.npz`. One logistic weight vector. The SageMaker tarball embeds that file plus `inference.py`. There is no ONNX export, and the local fallback reads the same npz.

`CueDetector.from_plan` calls SageMaker only when `CARE_LADDER_SAGEMAKER_ENDPOINT` is set. Unset means the npz on disk (or no trained classifier if the file is missing). A failed invoke does not silently switch back to the local weights.

## What is sent

The client blurs the frame, or falls back to a silhouette if blur does not change the 32x32 vector. The JSON body is `features`, `privacy` (`blur` or `silhouette`), and `artifact=fall_classifier.npz`. Raw frames are not in the body.

## Serverless inference

`CreateEndpointConfig` puts `ServerlessConfig` on the production variant (`MemorySizeInMB=1024`, `MaxConcurrency=1`). No `InstanceType`, so there is no idle instance. The endpoint object still exists until you delete it, and S3 keeps the tarball.

Check shapes and the local package without AWS:

```bash
python -m care_ladder.vision.sagemaker_cue
```

That command prints `endpoint: deferred` unless you opt in.

## Deploy (spend gate)

Needs a role that can read the model object, a private bucket, and an image that can run `infra/sagemaker/inference.py` (the public scikit-learn SageMaker image is the intended container). CI does not run this.

```bash
export CARE_LADDER_SAGEMAKER_DEPLOY=1
export CARE_LADDER_SAGEMAKER_ROLE_ARN=arn:aws:iam::ACCOUNT:role/CareLadderSageMaker
export CARE_LADDER_SAGEMAKER_BUCKET=your-private-bucket
export CARE_LADDER_SAGEMAKER_IMAGE=763104351884.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3
export CARE_LADDER_SAGEMAKER_REGION=us-east-1
python -m care_ladder.vision.sagemaker_cue --deploy
export CARE_LADDER_SAGEMAKER_ENDPOINT=care-ladder-cue
```

Train the npz first (`python -m care_ladder.vision.fall_train`). The deploy uploads `models/fall_classifier.npz` inside `model.tar.gz`. It does not start a SageMaker training job.

## Tear-down

```bash
export CARE_LADDER_SAGEMAKER_DEPLOY=1
python -m care_ladder.vision.sagemaker_cue --delete
unset CARE_LADDER_SAGEMAKER_ENDPOINT
```

Delete the S3 object `care-ladder/cue/model.tar.gz` in the bucket you used. With the env var unset, the app uses the local npz again.

Held-out numbers: `docs/fall-cv-metrics.md`.
