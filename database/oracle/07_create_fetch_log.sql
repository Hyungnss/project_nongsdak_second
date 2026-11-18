-- =====================================================================
-- KAMIS 자동 수집 이력
--   자동화는 실패가 눈에 보여야 산다. 스케줄러가 조용히 죽으면 화면은
--   어제 값을 오늘 값처럼 계속 보여주는데, TBL_DAILY_PRICE 만 봐서는
--   "오늘 조사가 없는 것"과 "수집기가 죽은 것"을 구별할 수 없다.
--   그래서 실행할 때마다 한 줄씩 남긴다.
--
--   collector/upsert.py 가 부류별로 한 줄씩 쓰고,
--   backend/db.py 의 get_meta() 가 마지막 성공 시각을 읽어 화면에 띄운다.
-- =====================================================================

-- 다시 만들 때만 주석 해제
-- DROP TABLE TBL_FETCH_LOG PURGE;
-- DROP SEQUENCE SEQ_FETCH_LOG;

CREATE TABLE TBL_FETCH_LOG
(
    LOG_NO        NUMBER                NOT NULL,  -- 일련번호 (기본키)
    FETCHED_AT    DATE DEFAULT SYSDATE  NOT NULL,  -- 수집 실행 시각
    SURVEY_DATE   DATE                  NOT NULL,  -- 요청한 조사일자
    CATEGORY_CODE VARCHAR2(5 CHAR),                -- 부류코드 (전체 요약이면 NULL)
    STATUS        VARCHAR2(20 CHAR)     NOT NULL,  -- OK / NO_DATA / ERROR
    ROWS_FETCHED  NUMBER DEFAULT 0      NOT NULL,  -- API 가 준 행 수
    ROWS_UPSERTED NUMBER DEFAULT 0      NOT NULL,  -- MERGE 로 반영한 행 수
    MESSAGE       VARCHAR2(500 CHAR),              -- 오류 메시지 / 비고
    CONSTRAINT PK_FETCH_LOG PRIMARY KEY (LOG_NO),
    -- 오타로 엉뚱한 값이 들어가면 '마지막 성공'을 못 찾는다.
    CONSTRAINT CK_FETCH_LOG_STATUS CHECK (STATUS IN ('OK', 'NO_DATA', 'ERROR'))
);

CREATE SEQUENCE SEQ_FETCH_LOG
START WITH 1
INCREMENT BY 1
NOCACHE;

-- 주 조회 패턴: "마지막 성공이 언제였나" — 최근 것부터 훑는다
CREATE INDEX IX_FETCH_LOG_TIME ON TBL_FETCH_LOG (FETCHED_AT DESC);


-- =====================================================================
-- 주석
-- =====================================================================
COMMENT ON TABLE  TBL_FETCH_LOG                IS 'KAMIS OpenAPI 수집 이력 (실행 1회 = 부류당 1행 + 전체 요약 1행)';
COMMENT ON COLUMN TBL_FETCH_LOG.LOG_NO         IS '일련번호 (SEQ_FETCH_LOG)';
COMMENT ON COLUMN TBL_FETCH_LOG.FETCHED_AT     IS '수집을 실행한 시각';
COMMENT ON COLUMN TBL_FETCH_LOG.SURVEY_DATE    IS '요청한 조사일자 (실행 시각과 다를 수 있다)';
COMMENT ON COLUMN TBL_FETCH_LOG.CATEGORY_CODE  IS '부류코드 100~600. 실행 전체 요약행은 NULL';
COMMENT ON COLUMN TBL_FETCH_LOG.STATUS         IS 'OK=자료 받음 / NO_DATA=주말·공휴일 등 자료 없음(정상) / ERROR=호출 실패. NO_DATA 를 ERROR 로 적으면 매주 경고가 울려 아무도 안 보게 된다';
COMMENT ON COLUMN TBL_FETCH_LOG.ROWS_FETCHED   IS 'API 응답 행 수';
COMMENT ON COLUMN TBL_FETCH_LOG.ROWS_UPSERTED  IS 'MERGE 로 반영한 행 수 (신규+갱신)';
COMMENT ON COLUMN TBL_FETCH_LOG.MESSAGE        IS '오류 메시지나 비고. 401/403 같은 인증 문제는 여기 남겨 두면 원인 찾기가 빠르다';


-- =====================================================================
-- 생성 확인
-- =====================================================================
SELECT TABLE_NAME    FROM USER_TABLES    WHERE TABLE_NAME    = 'TBL_FETCH_LOG';
SELECT SEQUENCE_NAME FROM USER_SEQUENCES WHERE SEQUENCE_NAME = 'SEQ_FETCH_LOG';

-- 최근 수집 현황 (운영하면서 자주 볼 것)
SELECT TO_CHAR(FETCHED_AT, 'MM-DD HH24:MI') AS 실행시각,
       TO_CHAR(SURVEY_DATE, 'YYYY-MM-DD')   AS 조사일,
       NVL(CATEGORY_CODE, '전체')            AS 부류,
       STATUS, ROWS_FETCHED, ROWS_UPSERTED, MESSAGE
FROM   TBL_FETCH_LOG
ORDER  BY LOG_NO DESC;
