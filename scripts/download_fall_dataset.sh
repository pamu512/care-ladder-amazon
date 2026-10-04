#!/usr/bin/env bash
# Fetch elwalyahmad/fall-detection (Kaggle fall + Computer Vision filter).
# Requires KAGGLE_USERNAME + KAGGLE_KEY or ~/.kaggle/kaggle.json.
# Writes data/kaggle/elwalyahmad-fall-detection/ (gitignored). Does not commit weights.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" -m care_ladder.vision.fall_train --download-only
fi
exec python3 -m care_ladder.vision.fall_train --download-only
