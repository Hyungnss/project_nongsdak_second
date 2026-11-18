-- ===========================================================================
-- 장바구니 (2026-10-18)
--
-- 회원마다 장바구니 하나. 품목 한 줄 = 품종 · 등급 하나 + 수량.
-- 가격은 저장하지 않는다. 화면을 열 때마다 TBL_DAILY_PRICE 의 최신 소매가로 계산해야
-- '지난주보다 얼마 더 드는지'가 오늘 값으로 나온다.
--
-- 소매만 담는다. 도매가는 10kg · 상자 단위라 장보기 합계에 섞으면 숫자가 의미를 잃는다.
--
-- 11_create_user.sql 다음에 실행한다 (TBL_USER 외래키).
-- 기존 테이블은 건드리지 않으므로 수집이 도는 중에 실행해도 된다.
-- ===========================================================================

-- 다시 만들 때만 주석 해제
-- DROP TABLE TBL_CART_ITEM PURGE;
-- DROP SEQUENCE SEQ_CART_ITEM;

CREATE TABLE TBL_CART_ITEM
(
    CART_NO        NUMBER                NOT NULL,  -- 일련번호 (기본키)
    USER_NO        NUMBER                NOT NULL,  -- 누구의 장바구니인지
    ITEM_CODE      VARCHAR2(10 CHAR)     NOT NULL,  -- 품목코드
    KIND_CODE      VARCHAR2(10 CHAR)     NOT NULL,  -- 품종코드
    RANK_NAME      VARCHAR2(30 CHAR)     NOT NULL,  -- 등급 (담을 때 본 등급 그대로)
    QTY            NUMBER(3)  DEFAULT 1  NOT NULL,  -- 수량 (조사 단위 개수)
    ADDED_AT       DATE DEFAULT SYSDATE  NOT NULL,  -- 담은 시각
    CONSTRAINT PK_CART_ITEM PRIMARY KEY (CART_NO),
    CONSTRAINT FK_CART_ITEM_USER FOREIGN KEY (USER_NO)
        REFERENCES TBL_USER (USER_NO) ON DELETE CASCADE,
    -- 같은 품종 · 등급을 또 담으면 줄을 늘리지 않고 수량을 올린다
    CONSTRAINT UX_CART_ITEM UNIQUE (USER_NO, ITEM_CODE, KIND_CODE, RANK_NAME),
    CONSTRAINT CK_CART_ITEM_QTY CHECK (QTY BETWEEN 1 AND 99)
);

CREATE SEQUENCE SEQ_CART_ITEM
START WITH 1
INCREMENT BY 1
NOCACHE;

COMMENT ON TABLE  TBL_CART_ITEM            IS '장바구니. 가격은 두지 않고 열 때마다 최신 소매가로 계산한다';
COMMENT ON COLUMN TBL_CART_ITEM.CART_NO    IS '일련번호 (SEQ_CART_ITEM)';
COMMENT ON COLUMN TBL_CART_ITEM.USER_NO    IS 'TBL_USER.USER_NO. 탈퇴하면 같이 지워진다';
COMMENT ON COLUMN TBL_CART_ITEM.RANK_NAME  IS '담을 때 화면에 보인 등급. 바꾸면 다른 가격이 된다';
COMMENT ON COLUMN TBL_CART_ITEM.QTY        IS '수량 1~99. 조사 단위(1포기 · 1kg · 10개) 개수';

-- 확인
SELECT TABLE_NAME    FROM USER_TABLES    WHERE TABLE_NAME    = 'TBL_CART_ITEM';
SELECT SEQUENCE_NAME FROM USER_SEQUENCES WHERE SEQUENCE_NAME = 'SEQ_CART_ITEM';
