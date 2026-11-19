#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# DB 마이그레이션 — database/migrations/NNN_*.sql 중 아직 적용하지 않은 것만 순서대로 적용한다.
#
#   bash database/migrate.sh          (docker compose 의 db 서비스에 적용 — 로컬 · 서버 · CI 공통)
#
# 왜 필요한가
#   database/schema.sql 은 '빈 DB 를 처음 만들 때' 한 번만 돈다 (docker-entrypoint-initdb.d).
#   이미 데이터가 있는 서버 DB 에 새 테이블을 더하려면 변경분만 따로 적용해야 한다.
#
# 규칙
#   · 파일 이름 앞 세 자리가 버전이다. 001 은 schema.sql(처음 만든 모양)이라 파일이 없다.
#   · 한 번 적용한(머지한) 파일은 고치지 않는다. 바꿀 게 생기면 다음 번호로 새 파일을 만든다.
#   · 파일 하나는 한 트랜잭션으로 적용된다 (psql -1). 실패하면 그 파일은 통째로 되돌아가고 여기서 멈춘다.
#   · 적용한 버전은 TBL_SCHEMA_MIGRATION 에 남는다.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

# DB 이름 · 사용자는 compose 가 db 컨테이너에 넣어 준 값을 컨테이너 안에서 읽는다 (.env 를 따로 읽지 않는다).
psql_db() {
  docker compose exec -T db sh -c 'exec psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' psql "$@"
}

psql_db -c "SET client_min_messages TO warning;
CREATE TABLE IF NOT EXISTS TBL_SCHEMA_MIGRATION (
    VERSION     VARCHAR(10)  PRIMARY KEY,
    NAME        VARCHAR(100) NOT NULL,
    APPLIED_AT  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
INSERT INTO TBL_SCHEMA_MIGRATION (VERSION, NAME) VALUES ('001', 'schema.sql')
ON CONFLICT (VERSION) DO NOTHING;"

applied=$(psql_db -At -c "SELECT VERSION FROM TBL_SCHEMA_MIGRATION")

count=0
for f in database/migrations/[0-9][0-9][0-9]_*.sql; do
  [ -e "$f" ] || continue
  name=$(basename "$f" .sql)
  ver=${name%%_*}
  if grep -qx "$ver" <<< "$applied"; then
    continue
  fi
  echo "적용: $name"
  # 파일 내용과 기록을 한 트랜잭션에 넣는다 — 둘 중 하나만 되는 일이 없게.
  { cat "$f"; printf "\nINSERT INTO TBL_SCHEMA_MIGRATION (VERSION, NAME) VALUES ('%s', '%s');\n" "$ver" "$name"; } \
    | psql_db -1
  count=$((count + 1))
done

if [ "$count" -eq 0 ]; then
  echo "마이그레이션: 새로 적용할 것 없음 ($(echo "$applied" | tr '\n' ' '))"
else
  echo "마이그레이션: ${count}개 적용"
fi
