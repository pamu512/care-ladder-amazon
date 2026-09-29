# Care Ladder — runnable FastAPI + OpenCV image for local docker / ECS Fargate.
# Demo entrypoint matches scripts/run_demo.sh: uvicorn care_ladder.api.app:app
# Does not require AWS at runtime; cloud wiring is documented under infra/.

FROM python:3.12-slim-bookworm

WORKDIR /app

# Runtime libs for opencv-python (cv2 import); no GUI display needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs

# Fetch ONNX models (person detection + pose, Apache-2.0) from OpenCV Zoo;
# same sources as scripts/download_models.sh.
ADD https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/person_detection_mediapipe/person_detection_mediapipe_2023mar.onnx /app/models/person_detection_mediapipe_2023mar.onnx
ADD https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/pose_estimation_mediapipe/pose_estimation_mediapipe_2023mar.onnx /app/models/pose_estimation_mediapipe_2023mar.onnx

# Editable install keeps package paths under /app/src so api.app resolves
# configs/demo_home.yaml via Path(__file__).parents[3] / "configs".
# requirements-lock.txt pins the exact, CI-verified versions for reproducible
# image builds (opencv wheel is the heavy layer; cache busts only on lock change).
COPY requirements-lock.txt /tmp/requirements-lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lock.txt
RUN pip install --no-cache-dir --no-deps -e .

ENV HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Reserved-phone / fail-closed demo API; bind all interfaces for containers.
CMD ["uvicorn", "care_ladder.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
