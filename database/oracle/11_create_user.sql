-- ===========================================================================
-- 회원 · 로그인 세션 (2026-10-16)
--
-- 시세 화면은 로그인 없이 그대로 쓴다. 회원은 장바구니 · 레시피 정리처럼
-- '내 것'을 저장하는 기능에만 필요하다. 그 기능들은 TBL_USER.USER_NO 를
-- 외래키로 걸어 쓰면 된다.
--
-- 비밀번호는 원문을 저장하지 않는다. backend/auth.py 가 scrypt 로 만든
-- 해시 문자열만 넣는다.
-- 세션 토큰도 원문 대신 SHA-256 만 저장한다. DB 가 새도 그 값으로는 로그인할 수 없다.
--
-- 기존 테이블은 건드리지 않으므로 수집이 도는 중에 실행해도 된다.
-- ===========================================================================

-- 다시 만들 때만 주석 해제 (세션 -> 회원 순서. 외래키 때문)
-- DROP TABLE TBL_USER_SESSION PURGE;
-- DROP TABLE TBL_USER PURGE;
-- DROP SEQUENCE SEQ_USER;

-- ── 회원 ──────────────────────────────────────────────────────────────────
CREATE TABLE TBL_USER
(
    USER_NO        NUMBER                NOT NULL,  -- 일련번호 (기본키)
    LOGIN_ID       VARCHAR2(20 CHAR)     NOT NULL,  -- 로그인 아이디 (소문자로 저장)
    PASSWORD_HASH  VARCHAR2(300 CHAR)    NOT NULL,  -- scrypt 해시 문자열
    NICKNAME       VARCHAR2(20 CHAR)     NOT NULL,  -- 화면에 보일 이름
    CREATED_AT     DATE DEFAULT SYSDATE  NOT NULL,  -- 가입 시각
    LAST_LOGIN_AT  DATE,                            -- 마지막 로그인 시각
    CONSTRAINT PK_USER PRIMARY KEY (USER_NO),
    CONSTRAINT UX_USER_LOGIN_ID UNIQUE (LOGIN_ID)
);

-- 11g 라 IDENTITY 컬럼이 없다. 시퀀스를 쓴다.
CREATE SEQUENCE SEQ_USER
START WITH 1
INCREMENT BY 1
NOCACHE;

-- ── 로그인 세션 ───────────────────────────────────────────────────────────
CREATE TABLE TBL_USER_SESSION
(
    TOKEN_HASH     VARCHAR2(64 CHAR)     NOT NULL,  -- 쿠키 토큰의 SHA-256 (기본키)
    USER_NO        NUMBER                NOT NULL,  -- 누구의 세션인지
    CREATED_AT     DATE DEFAULT SYSDATE  NOT NULL,  -- 로그인 시각
    EXPIRES_AT     DATE                  NOT NULL,  -- 이 시각이 지나면 무효
    CONSTRAINT PK_USER_SESSION PRIMARY KEY (TOKEN_HASH),
    -- 탈퇴하면 세션도 같이 지워진다
    CONSTRAINT FK_USER_SESSION_USER FOREIGN KEY (USER_NO)
        REFERENCES TBL_USER (USER_NO) ON DELETE CASCADE
);

CREATE INDEX IX_USER_SESSION_USER ON TBL_USER_SESSION (USER_NO);


-- =====================================================================
-- 주석
-- =====================================================================
COMMENT ON TABLE  TBL_USER                  IS '회원. 시세 조회에는 필요 없고, 장바구니·레시피처럼 개인 데이터를 저장할 때만 쓴다';
COMMENT ON COLUMN TBL_USER.USER_NO          IS '일련번호 (SEQ_USER). 다른 테이블은 이 값을 외래키로 건다';
COMMENT ON COLUMN TBL_USER.LOGIN_ID         IS '로그인 아이디. 영문 소문자·숫자·_ 4~20자. 대소문자를 가리지 않도록 소문자로 저장한다';
COMMENT ON COLUMN TBL_USER.PASSWORD_HASH    IS 'scrypt$n$r$p$salt$hash 형식. 원문 비밀번호는 어디에도 남기지 않는다';
COMMENT ON COLUMN TBL_USER.NICKNAME         IS '화면 표시용 이름 (중복 허용)';
COMMENT ON TABLE  TBL_USER_SESSION          IS '로그인 세션. 로그아웃하면 행을 지워 즉시 무효화한다';
COMMENT ON COLUMN TBL_USER_SESSION.TOKEN_HASH IS '쿠키에 담긴 토큰의 SHA-256. 토큰 원문은 저장하지 않는다';
COMMENT ON COLUMN TBL_USER_SESSION.EXPIRES_AT IS '만료 시각. 지난 행은 로그인할 때 함께 정리한다';


-- =====================================================================
-- 생성 확인
-- =====================================================================
SELECT TABLE_NAME    FROM USER_TABLES    WHERE TABLE_NAME IN ('TBL_USER', 'TBL_USER_SESSION');
SELECT SEQUENCE_NAME FROM USER_SEQUENCES WHERE SEQUENCE_NAME = 'SEQ_USER';
