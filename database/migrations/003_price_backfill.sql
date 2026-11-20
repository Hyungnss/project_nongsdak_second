-- ═════════════════════════════════════════════════════════════════════════════
-- 003 · 가격 과거분 백필 — 출처 표시 · 백필 진행 기록
--
-- collector/backfill.py 가 KAMIS 기간 API(신 일별 품목별 소매/도매, 최대 1년)로 과거 가격을 채운다.
-- ═════════════════════════════════════════════════════════════════════════════

-- 행이 어디서 왔는지 (데이터 계보). 이미 있는 행은 NULL 로 둔다 — 매일 수집(일별 부류별 API)과
-- 처음 적재한 CSV 에서 왔다. 백필 행은 'kamis_period'.
-- NULL 기본값이라 행을 다시 쓰지 않는다 (큰 테이블에서도 바로 끝난다).
ALTER TABLE TBL_DAILY_PRICE ADD COLUMN DATA_SOURCE VARCHAR(20);

COMMENT ON COLUMN TBL_DAILY_PRICE.DATA_SOURCE IS
    '행의 출처. NULL = 매일 수집(일별 부류별 API) 또는 처음 CSV 적재. kamis_period = 기간 API 백필 '
    '(당일가격 · 평년가격만 있고 1일전 · 1주전 등 비교 가격은 NULL)';


-- 백필 진행 기록 — (시장, 품목, 품종, 등급, 구간) 하나가 KAMIS 호출 한 번이다.
-- 끝난 구간은 다시 부르지 않으므로 중간에 멈춰도 이어서 받을 수 있다.
CREATE TABLE TBL_BACKFILL_JOB (
    MARKET_TYPE     VARCHAR(10)   NOT NULL,
    ITEM_CODE       VARCHAR(10)   NOT NULL,
    KIND_CODE       VARCHAR(10)   NOT NULL,
    RANK_CODE       VARCHAR(10)   NOT NULL,
    CHUNK_START     DATE          NOT NULL,
    CHUNK_END       DATE          NOT NULL,
    STATUS          VARCHAR(20)   NOT NULL,
    ROWS_FOUND      INTEGER       NOT NULL DEFAULT 0,
    ROWS_INSERTED   INTEGER       NOT NULL DEFAULT 0,
    MESSAGE         VARCHAR(500),
    DONE_AT         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT PK_BACKFILL_JOB PRIMARY KEY (MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, CHUNK_START),
    CONSTRAINT CK_BACKFILL_JOB_STATUS CHECK (STATUS IN ('OK', 'NO_DATA', 'ERROR'))
);

COMMENT ON TABLE  TBL_BACKFILL_JOB               IS '가격 백필 진행 기록. OK · NO_DATA 인 구간은 다시 받지 않는다 (ERROR 는 다음 실행 때 다시 시도)';
COMMENT ON COLUMN TBL_BACKFILL_JOB.ROWS_FOUND    IS 'KAMIS 가 준 전국 평균 가격 행 수';
COMMENT ON COLUMN TBL_BACKFILL_JOB.ROWS_INSERTED IS '새로 넣은 행 수. 이미 있던 날은 덮어쓰지 않으므로 FOUND 보다 작을 수 있다';
