-- ===========================================================================
-- 도매 추가 + API 원본 보관 (2026-10-15)
--
-- 01 · 07 을 실행한 DB 에 이어서 한 번 실행한다. 기존 행은 지우지 않는다.
--
-- 바뀌는 것
--   1. TBL_API_RAW 신설 — KAMIS 응답 JSON 을 손대지 않고 보관한다 (인증키만 가림).
--      변환 규칙이 바뀌거나 버그가 나와도 API 를 다시 부르지 않고 DB 안에서 다시 만들 수 있다.
--   2. TBL_DAILY_PRICE 의 자연키에 MARKET_TYPE 을 넣는다.
--      '배추 · 고랭지 · 상품' 은 소매에도 도매에도 있다. 키에 구분이 없으면
--      도매를 MERGE 하는 순간 같은 날 소매 행을 덮어쓴다.
--   3. API 가 주는데 버리던 값을 담는다 — 등급코드, 비교 기준일(1일전·1주일전·2주일전).
--      '1일전' 이 실제로 며칠인지 KAMIS 가 직접 적어 준다 (예: "1일전 (10/13)").
--      과거 CSV 분은 이 값이 없어 NULL 이다.
--   4. TBL_FETCH_LOG 에 MARKET_TYPE — 소매·도매 중 어느 쪽이 실패했는지 가린다.
--
-- 자연키를 바꾸는 동안은 유니크 인덱스가 잠깐 없다. 수집(17:30)이 도는 중에는 실행하지 말 것.
-- ===========================================================================

-- ── 1. 원본 보관 ──────────────────────────────────────────────────────────
CREATE TABLE TBL_API_RAW
(
    RAW_NO         NUMBER                NOT NULL,  -- 일련번호 (기본키)
    FETCHED_AT     DATE DEFAULT SYSDATE  NOT NULL,  -- 호출 시각
    SURVEY_DATE    DATE                  NOT NULL,  -- 요청한 조사일자 (p_regday)
    MARKET_TYPE    VARCHAR2(10 CHAR)     NOT NULL,  -- 소매 / 도매 (p_product_cls_code 01 / 02)
    CATEGORY_CODE  VARCHAR2(5 CHAR)      NOT NULL,  -- 부류코드 (p_item_category_code)
    ERROR_CODE     VARCHAR2(10 CHAR),               -- 응답의 error_code ('000' 정상)
    ITEM_COUNT     NUMBER DEFAULT 0      NOT NULL,  -- 응답 item 개수
    BODY_HASH      VARCHAR2(64 CHAR)     NOT NULL,  -- BODY 의 SHA-256. 같은 응답을 또 쌓지 않으려고 쓴다
    BODY           CLOB                  NOT NULL,  -- 응답 JSON 원문 (인증키·ID 는 *** 로 가림)
    CONSTRAINT PK_API_RAW PRIMARY KEY (RAW_NO)
);

CREATE SEQUENCE SEQ_API_RAW
START WITH 1
INCREMENT BY 1
NOCACHE;

CREATE INDEX IX_API_RAW_KEY ON TBL_API_RAW (SURVEY_DATE, MARKET_TYPE, CATEGORY_CODE, RAW_NO);

COMMENT ON TABLE  TBL_API_RAW               IS 'KAMIS OpenAPI 응답 원문. 호출 1회 = 1행. 직전 원문과 같으면 쌓지 않는다';
COMMENT ON COLUMN TBL_API_RAW.SURVEY_DATE   IS '요청한 조사일자 (p_regday)';
COMMENT ON COLUMN TBL_API_RAW.MARKET_TYPE   IS '소매(01) / 도매(02)';
COMMENT ON COLUMN TBL_API_RAW.BODY_HASH     IS 'BODY 의 SHA-256. 같은 키의 최신 행과 같으면 새로 넣지 않는다 — 매일 7일치를 다시 받으므로 그대로 쌓으면 같은 응답이 7벌씩 생긴다';
COMMENT ON COLUMN TBL_API_RAW.BODY          IS '응답 JSON. KAMIS 가 condition 에 요청 파라미터를 되돌려주므로 p_cert_key·p_cert_id 는 *** 로 가려 저장한다';

-- ── 2. 자연키에 MARKET_TYPE ───────────────────────────────────────────────
DROP INDEX UX_DAILY_PRICE_NATURAL;
CREATE UNIQUE INDEX UX_DAILY_PRICE_NATURAL
    ON TBL_DAILY_PRICE (MARKET_TYPE, SURVEY_DATE, ITEM_CODE, KIND_CODE, RANK_NAME);

-- 화면 조회는 전부 '한 시장 안에서' 이뤄진다. 시장을 앞에 둔다.
DROP INDEX IX_DAILY_ITEM_DATE;
CREATE INDEX IX_DAILY_ITEM_DATE
    ON TBL_DAILY_PRICE (MARKET_TYPE, ITEM_CODE, KIND_CODE, SURVEY_DATE);

DROP INDEX IX_DAILY_DATE;
CREATE INDEX IX_DAILY_DATE
    ON TBL_DAILY_PRICE (MARKET_TYPE, SURVEY_DATE, CATEGORY_CODE);

-- ── 3. 버리던 값 ──────────────────────────────────────────────────────────
ALTER TABLE TBL_DAILY_PRICE ADD (
    RANK_CODE      VARCHAR2(10 CHAR),
    PRICE_1D_DATE  DATE,
    PRICE_1W_DATE  DATE,
    PRICE_2W_DATE  DATE
);

COMMENT ON COLUMN TBL_DAILY_PRICE.MARKET_TYPE   IS '구분 소매/도매 — 자연키의 일부. 2026-10-15 이전 적재분은 전부 소매';
COMMENT ON COLUMN TBL_DAILY_PRICE.RANK_CODE     IS 'KAMIS 등급코드 (API 의 rank_code). CSV 적재분은 NULL';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_1D_DATE IS 'PRICE_1D 가 실제로 어느 날 값인지 (API 의 day2 "1일전 (MM/DD)"). CSV 적재분은 NULL';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_1W_DATE IS 'PRICE_1W 의 실제 날짜 (day3). CSV 적재분은 NULL';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_2W_DATE IS 'PRICE_2W 의 실제 날짜 (day4). CSV 적재분은 NULL';

-- ── 4. 수집 이력에 시장 ───────────────────────────────────────────────────
ALTER TABLE TBL_FETCH_LOG ADD (MARKET_TYPE VARCHAR2(10 CHAR));
-- 지금까지의 기록은 전부 소매 수집이었다
UPDATE TBL_FETCH_LOG SET MARKET_TYPE = '소매' WHERE MARKET_TYPE IS NULL;
COMMIT;

COMMENT ON COLUMN TBL_FETCH_LOG.MARKET_TYPE IS '소매 / 도매. 요약행(CATEGORY_CODE NULL)도 시장마다 하나씩 남는다';

-- ── 확인 ──────────────────────────────────────────────────────────────────
SELECT INDEX_NAME, UNIQUENESS FROM USER_INDEXES WHERE TABLE_NAME = 'TBL_DAILY_PRICE';
SELECT MARKET_TYPE, COUNT(*) FROM TBL_DAILY_PRICE GROUP BY MARKET_TYPE;
