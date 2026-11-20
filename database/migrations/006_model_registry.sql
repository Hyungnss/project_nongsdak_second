-- ═════════════════════════════════════════════════════════════════════════════
-- 006 · 모델 기록 — 매주 학습한 LightGBM 의 게이트 결과 · 배포 · 롤백
--
-- collector/train.py 가 학습할 때마다 한 줄 넣는다 (게이트를 못 넘어도 남긴다 — 왜 배포 안 했는지가 기록이다).
-- 모델 파일 자체는 Docker 볼륨 models(+ 버킷 models/)에 있고, 어느 버전을 쓰는지는 current.json 이 정한다.
-- 이 표는 그 이력을 DB 에서 보이게 한다 (Grafana · 발표 · '언제 왜 바뀌었나').
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE TBL_MODEL_RUN (
    MODEL_VERSION   VARCHAR(60)   PRIMARY KEY,
    MARKET_TYPE     VARCHAR(10)   NOT NULL,
    MODEL           VARCHAR(30)   NOT NULL,
    TRAINED_AT      TIMESTAMPTZ   NOT NULL,
    DATA_END        DATE          NOT NULL,
    TRAIN_ROWS      INTEGER       NOT NULL,
    HOLDOUT_START   DATE          NOT NULL,
    HOLDOUT_END     DATE          NOT NULL,
    SCORE           NUMERIC(8, 4),
    BLEND_SCORE     NUMERIC(8, 4),
    PARITY_DIFF     DOUBLE PRECISION,
    PASSED          BOOLEAN       NOT NULL,
    REASON          VARCHAR(200)  NOT NULL,
    DEPLOYED        BOOLEAN       NOT NULL DEFAULT FALSE,
    META            JSONB         NOT NULL DEFAULT '{}'::jsonb,
    CREATED_AT      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IX_MODEL_RUN_MARKET ON TBL_MODEL_RUN (MARKET_TYPE, TRAINED_AT DESC);

COMMENT ON TABLE  TBL_MODEL_RUN               IS '운영 모델 학습 기록. 한 줄 = 학습 한 번 (게이트를 못 넘은 것도)';
COMMENT ON COLUMN TBL_MODEL_RUN.MODEL_VERSION IS '예: lgbm-retail-20261122-0300. TBL_PRICE_FORECAST.MODEL_VERSION 과 같은 값';
COMMENT ON COLUMN TBL_MODEL_RUN.DATA_END      IS '학습에 쓴 가격의 마지막 조사일';
COMMENT ON COLUMN TBL_MODEL_RUN.HOLDOUT_START IS '게이트 — 학습에서 떼어 두고 채점한 최근 8주(기준일)의 시작';
COMMENT ON COLUMN TBL_MODEL_RUN.SCORE         IS '게이트 기간 점수 = 1 · 2 · 4주 MASE 중앙값 평균 (낮을수록 좋음)';
COMMENT ON COLUMN TBL_MODEL_RUN.BLEND_SCORE   IS '같은 기간 기준선 blend 점수. SCORE 가 이보다 낮아야 통과';
COMMENT ON COLUMN TBL_MODEL_RUN.PARITY_DIFF   IS '저장했다 다시 읽은 모델과 메모리 모델의 예측 차이 (최대). 0 이어야 한다';
COMMENT ON COLUMN TBL_MODEL_RUN.PASSED        IS '게이트(성능 · parity · 정상) 통과';
COMMENT ON COLUMN TBL_MODEL_RUN.DEPLOYED      IS '학습 직후 current.json 이 이 버전을 가리키게 했는지 (= PASSED)';
