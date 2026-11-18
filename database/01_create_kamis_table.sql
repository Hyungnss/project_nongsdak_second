-- =====================================================================
-- KAMIS 소매 시세 적재 테이블
--   원본: data/raws/kamis_price_data_20250901_20260818.csv
--   기간: 2025-09-01 ~ 2026-08-18 (252일) · 43,480행 · 17컬럼
--   CSV 컬럼을 그대로 1:1로 옮기고, 기본키는 일련번호를 따로 둔다.
--
-- 크기 산정 근거 (실제 데이터 최대값)
--   품종명 16자(35바이트) · 품목명 7자(19바이트) · 등급 6자(10바이트)
--   가격 최대 84,061 · 소수점 존재 -> NUMBER(12,2)
--   VARCHAR2는 CHAR 기준으로 잡는다. 기본값인 BYTE 기준으로 두면
--   UTF-8 한글이 글자당 3바이트라 VARCHAR2(20)에 6글자밖에 안 들어간다.
-- =====================================================================

-- 다시 만들 때만 주석 해제
-- DROP TABLE TBL_DAILY_PRICE PURGE;
-- DROP SEQUENCE SEQ_DAILY_PRICE;

CREATE TABLE TBL_DAILY_PRICE
(
    PRICE_NO         NUMBER                NOT NULL,  -- 일련번호 (기본키)
    SURVEY_DATE      DATE                  NOT NULL,  -- 조사일자
    MARKET_TYPE      VARCHAR2(10 CHAR)     NOT NULL,  -- 구분 (전 행 '소매')
    CATEGORY_NAME    VARCHAR2(20 CHAR)     NOT NULL,  -- 부류명
    CATEGORY_CODE    VARCHAR2(5 CHAR)      NOT NULL,  -- 부류코드 100~600
    ITEM_CODE        VARCHAR2(10 CHAR)     NOT NULL,  -- 품목코드
    ITEM_NAME        VARCHAR2(40 CHAR)     NOT NULL,  -- 품목명
    KIND_CODE        VARCHAR2(10 CHAR)     NOT NULL,  -- 품종코드 (품목 안에서만 유일)
    KIND_NAME        VARCHAR2(60 CHAR),               -- 품종명 (끝에 단위가 괄호로 붙어 있음)
    RANK_NAME        VARCHAR2(30 CHAR)     NOT NULL,  -- 등급 (원본 '-' 는 '없음' 으로 적재)
    UNIT             VARCHAR2(20 CHAR),               -- 단위 (예: 100g, 1마리, 10구)
    PRICE_TODAY      NUMBER(12, 2),                   -- 당일가격   ('-'는 NULL, 약 9%)
    PRICE_1D         NUMBER(12, 2),                   -- 1일전가격  ('-'는 NULL, 약 24%)
    PRICE_1W         NUMBER(12, 2),                   -- 1주일전가격
    PRICE_2W         NUMBER(12, 2),                   -- 2주일전가격
    PRICE_1M         NUMBER(12, 2),                   -- 1개월전가격
    PRICE_1Y         NUMBER(12, 2),                   -- 1년전가격
    PRICE_NORMAL     NUMBER(12, 2),                   -- 평년가격 (KAMIS 다년 평균)
    CREATED_AT       DATE DEFAULT SYSDATE  NOT NULL,
    CONSTRAINT PK_DAILY_PRICE PRIMARY KEY (PRICE_NO)
);

-- 일련번호 채번용 시퀀스
CREATE SEQUENCE SEQ_DAILY_PRICE
START WITH 1
INCREMENT BY 1
NOCACHE;

-- 같은 조사 건이 두 번 들어가지 않도록 막는다.
-- 기본키가 일련번호라 중복을 못 막으므로, 실제 자연키에 UNIQUE를 따로 건다.
-- (실데이터 43,139행에서 이 네 컬럼 조합의 중복은 0건임을 확인했다.)
-- 재적재할 때는 TRUNCATE TABLE TBL_DAILY_PRICE; 를 먼저 실행할 것.
--
-- [중요] RANK_NAME 의 원본 '-' 는 '없음' 이라는 문자열로 바꿔 적재한다 (NULL 아님).
--   Oracle 의 UNIQUE 인덱스는 NULL 을 서로 다른 값으로 보기 때문에(NULL != NULL),
--   NULL 로 넣으면 등급이 없는 5,338행(전체의 12.4%, 수산물 대부분)에서
--   중복 적재를 막지 못한다. '없음' 으로 채우면 그 12%까지 전부 보호된다.
--   덤으로 조회 결과에서 '-' 가 하이픈인지 결측인지 헷갈리는 일도 없어진다.
--   가격 컬럼의 '-' 는 숫자형이므로 NULL 로 넣는 것이 맞다.
CREATE UNIQUE INDEX UX_DAILY_PRICE_NATURAL
    ON TBL_DAILY_PRICE (SURVEY_DATE, ITEM_CODE, KIND_CODE, RANK_NAME);

-- 서비스의 주 조회 패턴: 특정 품목·품종의 기간 조회
CREATE INDEX IX_DAILY_ITEM_DATE
    ON TBL_DAILY_PRICE (ITEM_CODE, KIND_CODE, SURVEY_DATE);

-- 부류별/일자별 집계 조회용
CREATE INDEX IX_DAILY_DATE
    ON TBL_DAILY_PRICE (SURVEY_DATE, CATEGORY_CODE);


-- =====================================================================
-- 주석 (SQL Developer 에서 컬럼 설명으로 보인다)
-- =====================================================================
COMMENT ON TABLE  TBL_DAILY_PRICE                IS 'KAMIS 소매 시세 (일별)';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_NO       IS '일련번호 (SEQ_DAILY_PRICE)';
COMMENT ON COLUMN TBL_DAILY_PRICE.SURVEY_DATE    IS '조사일자';
COMMENT ON COLUMN TBL_DAILY_PRICE.MARKET_TYPE    IS '구분 (소매/도매) — 현재 적재분은 전부 소매';
COMMENT ON COLUMN TBL_DAILY_PRICE.CATEGORY_NAME  IS '부류명';
COMMENT ON COLUMN TBL_DAILY_PRICE.CATEGORY_CODE  IS '부류코드 100 식량작물 / 200 채소류 / 300 특용작물 / 400 과실류 / 500 축산물 / 600 수산물';
COMMENT ON COLUMN TBL_DAILY_PRICE.ITEM_CODE      IS '품목코드';
COMMENT ON COLUMN TBL_DAILY_PRICE.ITEM_NAME      IS '품목명';
COMMENT ON COLUMN TBL_DAILY_PRICE.KIND_CODE      IS '품종코드 — 품목 안에서만 유일. 단독으로 쓰면 안 되고 (ITEM_CODE, KIND_CODE) 복합으로 다룰 것';
COMMENT ON COLUMN TBL_DAILY_PRICE.KIND_NAME      IS '품종명 — 끝에 단위가 괄호로 붙어 있음 (예: 흰 콩(국산)(500g))';
COMMENT ON COLUMN TBL_DAILY_PRICE.RANK_NAME      IS '등급 — 상품/중품 외에 부위(삼겹살·목심), 원산지(미국산·호주산), 제품형태(흰우유·절단육)가 섞여 있음. KAMIS 원본의 ''-''(등급없음)는 ''없음''으로 적재';
COMMENT ON COLUMN TBL_DAILY_PRICE.UNIT           IS '조사 단위 (예: 100g, 1kg, 1마리, 10구)';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_TODAY    IS '당일가격 — KAMIS 공표 시차로 약 9%가 NULL';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_1D       IS '1일전가격';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_1W       IS '1주일전가격';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_2W       IS '2주일전가격';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_1M       IS '1개월전가격';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_1Y       IS '1년전가격';
COMMENT ON COLUMN TBL_DAILY_PRICE.PRICE_NORMAL   IS '평년가격 (KAMIS 다년 평균)';


-- =====================================================================
-- 생성 확인
-- =====================================================================
SELECT TABLE_NAME    FROM USER_TABLES     WHERE TABLE_NAME    = 'TBL_DAILY_PRICE';
SELECT SEQUENCE_NAME FROM USER_SEQUENCES  WHERE SEQUENCE_NAME = 'SEQ_DAILY_PRICE';
SELECT INDEX_NAME, UNIQUENESS
FROM   USER_INDEXES  WHERE TABLE_NAME     = 'TBL_DAILY_PRICE';

SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, DATA_PRECISION, DATA_SCALE, NULLABLE
FROM   USER_TAB_COLUMNS
WHERE  TABLE_NAME = 'TBL_DAILY_PRICE'
ORDER  BY COLUMN_ID;
