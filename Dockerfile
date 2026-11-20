# ─────────────────────────────────────────────────────────────────────────────
# 농스닥 이미지 — 웹(backend) · 수집기(collector)가 같은 이미지를 쓰고 실행 명령만 다르다.
#
#   빌드:  docker build -t nongsdak .
#   웹  :  docker compose up -d web          (uvicorn backend.app:app)
#   수집:  docker compose --profile collector up -d collector   (python -m collector.scheduler)
#
# 두 단계로 나눈다.
#   1) builder : uv 로 의존성을 .venv 에 설치한다 (uv.lock 그대로, 개발 도구 제외)
#   2) runtime : 파이썬과 .venv · 코드만 담는다. uv 도 빌드 도구도 들어가지 않는다
# ─────────────────────────────────────────────────────────────────────────────

# 버전은 정확히 고정한다 (.python-version 3.11 · 로컬 uv 0.13.7 과 같게).
ARG PYTHON_IMAGE=python:3.11.18-slim-bookworm


# ── 1. builder ──────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

# UV_COMPILE_BYTECODE : .pyc 를 미리 만들어 컨테이너 첫 기동을 빠르게
# UV_LINK_MODE=copy   : 캐시 마운트와 다른 파일시스템이라 하드링크 대신 복사
# UV_PYTHON_DOWNLOADS : 이미지에 든 파이썬을 쓰고 따로 받지 않는다
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# 의존성만 먼저 설치한다. 코드만 바뀌면 이 층은 캐시에서 그대로 쓴다 (빌드가 빨라진다).
#   --locked     : uv.lock 과 pyproject.toml 이 어긋나면 실패 (로컬과 다른 버전이 들어가는 일을 막는다)
#   --no-dev     : pytest · ruff 는 넣지 않는다
#   --no-install-project : 이 프로젝트 자체는 패키지로 설치하지 않는다 (코드는 아래에서 복사)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --locked --no-dev --no-install-project


# ── 2. runtime ──────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS runtime

# lightgbm 이 쓰는 OpenMP 런타임 (slim 이미지에는 없다)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# 컨테이너 안에서 root 로 돌지 않는다
RUN useradd --create-home --uid 10001 app
WORKDIR /app

# 운영 모델 폴더 (collector/train.py 가 쓰고 collector/predict.py 가 읽는다). Docker 볼륨 models 를 여기에 붙인다 —
# 볼륨이 처음 만들어질 때 이 폴더의 주인(app)을 그대로 물려받아야 app 사용자가 쓸 수 있다.
RUN mkdir -p /app/models && chown app:app /app/models

# PYTHONUNBUFFERED : 출력을 바로 내보낸다 (docker logs 에 바로 보이게, 죽어도 로그가 남게)
# PYTHONUTF8       : 한글 출력 · 파일을 UTF-8 로
# TZ               : 로그 시각을 한국 시각으로 (수집 판단은 코드가 config.now_kst 로 따로 한다)
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    TZ=Asia/Seoul

COPY --from=builder /app/.venv /app/.venv
COPY config.py ./
COPY backend/ backend/
COPY frontend/ frontend/
COPY collector/ collector/
# 운영 모델 학습(collector/train.py → ml/model.py) · 매일 예측(ml/predict.py). 실험 코드(ml/run.py · tune.py)도
# 같이 들어오지만 서버에서 돌리지 않는다 (mlflow · scikit-learn 은 ml 그룹이라 이미지에 없다).
COPY ml/ ml/
# 원본 CSV — 빈 DB 에 처음 넣을 때 쓴다 (python -m collector.loader)
COPY data/raws/kamis_price_data_20250901_20260818.csv data/raws/

# 버전은 CI 가 빌드할 때 넣는다 (--build-arg APP_VERSION=2.2.0). /api/health · API 문서에 나온다.
# 맨 끝에 두는 이유: 값이 바뀌어도 위의 층(의존성 · 코드)은 캐시를 그대로 쓰게.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

USER app
EXPOSE 8000

# 기본 실행은 웹. 수집기는 docker-compose.yml 에서 command 로 바꾼다.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
