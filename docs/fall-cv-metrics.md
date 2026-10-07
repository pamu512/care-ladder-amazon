# Held-out metrics

Canonical artifact: `models/fall_classifier.npz` (one logistic weight vector). SageMaker `model.tar.gz` embeds that file. There is no ONNX export.

The CLI fits that file on the train split and scores the holdout from the reloaded npz, so the table describes the saved artifact. Both rows use those weights. The cloud row is blur or silhouette features, not a second model.

| Input | Weights | Accuracy | Precision | Recall | n |
| --- | --- | --- | --- | --- | --- |
| raw gray crop (local fallback) | npz | not run | not run | not run |  |
| blur or silhouette features (cloud payload) | npz | not run | not run | not run |  |

Not run in this commit. `python -m care_ladder.vision.fall_train` fills the numbers when the Kaggle zip is available. Do not paste synthetic self-check scores here.
