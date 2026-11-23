-- ═════════════════════════════════════════════════════════════════════════════
-- 007 · 모델 기록 — 챔피언 / 도전자 게이트
--
-- 게이트가 이번 학습(도전자)을 blend 뿐 아니라 '지금 배포된 모델의 방법'(챔피언)과도 겨룬다 (ml/model.py).
-- 챔피언도 같은 떼어 두기 전 자료로 다시 학습해 같은 8주를 채점한다 — 그 점수와 버전을 남긴다.
-- 열을 더하기만 한다. 이전 행 · 배포된 모델이 없던 학습 · 비교를 건너뛴 학습은 NULL.
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE TBL_MODEL_RUN ADD COLUMN CHAMPION_VERSION VARCHAR(60);
ALTER TABLE TBL_MODEL_RUN ADD COLUMN CHAMPION_SCORE   NUMERIC(8, 4);

COMMENT ON COLUMN TBL_MODEL_RUN.CHAMPION_VERSION IS '학습 때 배포돼 있던 모델(챔피언). 없으면 NULL';
COMMENT ON COLUMN TBL_MODEL_RUN.CHAMPION_SCORE   IS '챔피언의 방법으로 같은 8주를 채점한 점수. SCORE 가 이보다 크면 탈락. 비교를 건너뛰면 NULL';
