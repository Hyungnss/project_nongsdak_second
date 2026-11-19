#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 서버 DB 백업 — pg_dump → Lightsail 버킷. .github/workflows/backup.yml 이 서버 runner 에서 부른다.
#
#   bash database/backup.sh dump        덤프 → 확인 → 버킷에 올리기 → 보관 기간 지난 것 지우기
#   bash database/backup.sh restore     가장 최근 백업을 임시 DB 에 실제로 복원해 행 수를 비교하고 지운다
#
# 환경변수
#   APP_DIR       compose 가 있는 폴더        (기본 /srv/nongsdak)
#   BUCKET        버킷 이름                     (필수 — GitHub Variable BACKUP_BUCKET)
#   KEEP_DAYS     보관 일수                     (기본 30)
#
# 버킷 접근은 Lightsail '리소스 액세스' 로 인스턴스에 붙은 역할을 쓴다 — 서버에 키 파일이 없다.
# 백업에는 회원 정보까지 DB 전체가 들어간다. 버킷은 반드시 비공개여야 한다 (dump 가 확인한다).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR=${APP_DIR:-/srv/nongsdak}
KEEP_DAYS=${KEEP_DAYS:-30}
: "${BUCKET:?BUCKET 이 필요합니다 (GitHub Variable BACKUP_BUCKET)}"
PREFIX="s3://$BUCKET/backup"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$APP_DIR"

psql_db() {   # 컨테이너 안의 계정 · DB 이름으로 psql
  docker compose exec -T db sh -c 'exec psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"' psql "$@"
}

# 비교할 표 — 복원 시험에서 행 수를 맞춰 본다
TABLES="tbl_daily_price tbl_user tbl_api_key tbl_weather_daily tbl_cpi_monthly tbl_fcst_raw"

counts() {   # DB 이름 → "표 행수" 줄들 (없는 표는 건너뛴다)
  local db=$1 t
  for t in $TABLES; do
    if [ "$(psql_db -d "$db" -At -c "SELECT to_regclass('$t') IS NOT NULL")" = "t" ]; then
      echo "$t $(psql_db -d "$db" -At -c "SELECT COUNT(*) FROM $t")"
    fi
  done
}

dump() {
  local stamp file size
  stamp=$(TZ=Asia/Seoul date +%Y%m%d_%H%M)
  file="$WORK/nongsdak_$stamp.dump"

  # 버킷이 비공개인지 — 익명으로 목록을 볼 수 있으면 멈춘다
  local anon
  anon=$(curl -s -o /dev/null -w "%{http_code}" "https://$BUCKET.s3.amazonaws.com/" || true)
  if [ "$anon" = "200" ]; then
    echo "::error::버킷 $BUCKET 이 공개 상태입니다. 백업을 올리지 않습니다."; exit 1
  fi

  # -Fc: 압축된 사용자 지정 형식 (pg_restore 로 표 하나만 골라 되살릴 수도 있다)
  docker compose exec -T db sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$file"
  size=$(stat -c %s "$file")
  [ "$size" -gt 100000 ] || { echo "::error::덤프가 너무 작습니다 (${size}B)"; exit 1; }
  # 읽을 수 있는 덤프인지 (목차를 읽어 본다)
  docker compose exec -T db pg_restore --list < "$file" > "$WORK/toc.txt"
  echo "덤프 $(numfmt --to=iec "$size") · 목차 $(grep -c 'TABLE DATA' "$WORK/toc.txt")개 표"

  local key
  key="$PREFIX/$(TZ=Asia/Seoul date +%Y/%m)/nongsdak_$stamp.dump"
  aws s3 cp --only-show-errors "$file" "$key"
  aws s3 ls "$key" > /dev/null
  echo "올림 → $key"

  # 보관 기간이 지난 백업 지우기 (파일 이름의 날짜 기준)
  local cutoff removed=0 name day
  cutoff=$(TZ=Asia/Seoul date -d "-$KEEP_DAYS days" +%Y%m%d)
  while read -r _ _ _ path; do
    name=$(basename "$path")
    day=$(echo "$name" | sed -nE 's/^nongsdak_([0-9]{8})_.*/\1/p')
    if [ -n "$day" ] && [ "$day" -lt "$cutoff" ]; then
      aws s3 rm --only-show-errors "s3://$BUCKET/$path"
      removed=$((removed + 1))
    fi
  done < <(aws s3 ls "$PREFIX/" --recursive)
  echo "보관 ${KEEP_DAYS}일 · 지운 옛 백업 ${removed}개 · 남은 백업 $(aws s3 ls "$PREFIX/" --recursive | wc -l)개"
}

restore() {
  local latest file db=nongsdak_restore_test
  latest=$(aws s3 ls "$PREFIX/" --recursive | sort | tail -1 | awk '{print $4}')
  [ -n "$latest" ] || { echo "::error::백업이 없습니다"; exit 1; }
  file="$WORK/restore.dump"
  aws s3 cp --only-show-errors "s3://$BUCKET/$latest" "$file"
  echo "복원 시험 — $latest"

  psql_db -d postgres -c "SET client_min_messages TO warning" -c "DROP DATABASE IF EXISTS $db"
  psql_db -d postgres -c "CREATE DATABASE $db"
  trap 'psql_db -d postgres -c "DROP DATABASE IF EXISTS '"$db"'" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
  docker compose exec -T db sh -c "exec pg_restore --no-owner -U \"\$POSTGRES_USER\" -d $db" < "$file"

  # 운영 DB 와 행 수 비교. 백업 뒤에 수집된 행이 있을 수 있어 '복원본 <= 운영' 이고 비어 있지 않으면 통과.
  local live restored fail=0 t a b
  live=$(counts "$(docker compose exec -T db sh -c 'echo $POSTGRES_DB')")
  restored=$(counts "$db")
  while read -r t b; do
    a=$(echo "$live" | awk -v t="$t" '$1==t {print $2}')
    if [ "$b" -gt 0 ] || [ "${a:-0}" -eq 0 ]; then mark="✅"; else mark="❌"; fail=1; fi
    if [ -n "$a" ] && [ "$b" -gt "$a" ]; then mark="❌"; fail=1; fi
    printf "  %-20s 운영 %10s · 복원 %10s  %s\n" "$t" "${a:-?}" "$b" "$mark"
  done <<< "$restored"
  [ "$fail" -eq 0 ] || { echo "::error::복원한 DB 의 행 수가 이상합니다"; exit 1; }
  echo "복원 시험 통과 (임시 DB 는 지운다)"
}

case "${1:-}" in
  dump) dump ;;
  restore) restore ;;
  *) echo "사용법: bash database/backup.sh dump|restore"; exit 2 ;;
esac
