#!/usr/bin/env bash
set -euo pipefail

FILE="${1:-docs/VERCEL_PRODUCTION_ENV_FILLED_DRAFT_2026-02-12.env}"

if [[ ! -f "$FILE" ]]; then
  echo "파일을 찾을 수 없습니다: $FILE" >&2
  exit 1
fi

echo "# Vercel 환경변수 등록 명령어 (production)"
echo "# 기준 파일: $FILE"
echo

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  if [[ "$line" != *=* ]]; then
    continue
  fi

  key="${line%%=*}"
  value="${line#*=}"

  # 치환되지 않은 자리표시자는 건너뜁니다.
  if [[ "$value" == *"<REPLACE"* ]] || [[ "$value" == *"<DB_"* ]] || [[ "$value" == *"<OPENAI_API_KEY"* ]] || [[ "$value" == *"<OPTIONAL_"* ]]; then
    continue
  fi

  # 명령어만 출력합니다. 실제 실행은 하지 않습니다.
  printf "vercel env add %s production\n" "$key"
done < "$FILE"
