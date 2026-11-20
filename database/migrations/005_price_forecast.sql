-- ═════════════════════════════════════════════════════════════════════════════
-- 005 · 가격 예측 — 매일 만든 예측과, 예측 vs 실제 비교
--
-- collector/predict.py 가 매일 가격 수집(17:30) 뒤 품종 · 등급마다 1 · 2 · 4주 뒤 가격을 예측해 넣는다.
-- 화면(/api/forecast)과 공개 API(/api/v1/forecast)는 이 표의 가장 최근 예측을 보여 준다.
-- 모델을 바꿔도(blend → lgbm) 표 · API · 화면은 그대로다 — MODEL · MODEL_VERSION 만 달라진다.
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE TBL_PRICE_FORECAST (
    BASE_DATE       DATE          NOT NULL,
    MARKET_TYPE     VARCHAR(10)   NOT NULL,
    ITEM_CODE       VARCHAR(10)   NOT NULL,
    KIND_CODE       VARCHAR(10)   NOT NULL,
    RANK_NAME       VARCHAR(30)   NOT NULL,
    H               SMALLINT      NOT NULL,
    TARGET_DATE     DATE          NOT NULL,
    BASE_PRICE      NUMERIC(12, 2) NOT NULL,
    PRICE           NUMERIC(12, 2) NOT NULL,
    MODEL           VARCHAR(30)   NOT NULL,
    MODEL_VERSION   VARCHAR(60)   NOT NULL,
    FALLBACK        BOOLEAN       NOT NULL DEFAULT FALSE,
    CREATED_AT      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT PK_PRICE_FORECAST PRIMARY KEY (BASE_DATE, MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, H, MODEL),
    CONSTRAINT CK_PRICE_FORECAST_H CHECK (H > 0),
    CONSTRAINT CK_PRICE_FORECAST_PRICE CHECK (PRICE > 0 AND BASE_PRICE > 0)
);

-- 품종 하나의 '가장 최근 예측' 을 찾는다 (화면 · API)
CREATE INDEX IX_PRICE_FORECAST_SERIES
    ON TBL_PRICE_FORECAST (MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, BASE_DATE DESC);

COMMENT ON TABLE  TBL_PRICE_FORECAST               IS '가격 예측. 기준일(그날 가격까지 알고) × 품종 · 등급 × 예측 기간(일) × 모델';
COMMENT ON COLUMN TBL_PRICE_FORECAST.BASE_DATE     IS '기준일 — 이날 가격까지 보고 예측했다 (그 품종의 마지막 조사일)';
COMMENT ON COLUMN TBL_PRICE_FORECAST.H             IS '예측 기간(일) — 7 · 14 · 28';
COMMENT ON COLUMN TBL_PRICE_FORECAST.TARGET_DATE   IS '예측 대상일 = 기준일 + H. 주말 · 공휴일이면 실제 비교는 그 뒤 3일 안의 첫 조사일과 한다';
COMMENT ON COLUMN TBL_PRICE_FORECAST.MODEL         IS '예측한 모델 이름 (blend · lgbm ...)';
COMMENT ON COLUMN TBL_PRICE_FORECAST.MODEL_VERSION IS '모델 버전 — 어떤 모델이 이 예측을 냈는지 추적한다';
COMMENT ON COLUMN TBL_PRICE_FORECAST.FALLBACK      IS '모델이 예측을 못 내 naive(기준일 가격 그대로)로 메웠는지 — 과거 자료가 2년 안 되는 품종 등';


-- 예측 vs 실제 — 목표일(또는 그 뒤 3일 안의 첫 조사일)의 실제 가격이 나온 예측만.
-- 매일 쌓이는 이 결과가 '모델이 요즘 잘 맞나' 의 근거다 (모니터링 · 모델 교체 판단).
CREATE VIEW V_FORECAST_EVAL AS
SELECT f.BASE_DATE, f.MARKET_TYPE, f.ITEM_CODE, f.KIND_CODE, f.RANK_NAME, f.H, f.TARGET_DATE,
       f.BASE_PRICE, f.PRICE AS PREDICTED, f.MODEL, f.MODEL_VERSION, f.FALLBACK,
       a.SURVEY_DATE AS ACTUAL_DATE, a.PRICE_TODAY AS ACTUAL,
       ABS(f.PRICE - a.PRICE_TODAY) / a.PRICE_TODAY AS APE,
       SIGN(f.PRICE - f.BASE_PRICE) = SIGN(a.PRICE_TODAY - f.BASE_PRICE) AS DIRECTION_OK
FROM   TBL_PRICE_FORECAST f
JOIN   LATERAL (
         SELECT p.SURVEY_DATE, p.PRICE_TODAY
         FROM   TBL_DAILY_PRICE p
         WHERE  p.MARKET_TYPE = f.MARKET_TYPE AND p.ITEM_CODE = f.ITEM_CODE
           AND  p.KIND_CODE = f.KIND_CODE AND p.RANK_NAME = f.RANK_NAME
           AND  p.SURVEY_DATE BETWEEN f.TARGET_DATE AND f.TARGET_DATE + 3
           AND  p.PRICE_TODAY > 0
         ORDER  BY p.SURVEY_DATE
         LIMIT  1
       ) a ON TRUE;

COMMENT ON VIEW V_FORECAST_EVAL IS '예측 vs 실제. APE = |예측 - 실제| / 실제. DIRECTION_OK = 오를지 내릴지 맞혔나';
