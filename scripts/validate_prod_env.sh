#!/usr/bin/env bash
set -euo pipefail

ok=true

print_ok() {
  printf "정상  %s\n" "$1"
}

print_warn() {
  printf "주의  %s\n" "$1"
}

print_fail() {
  printf "실패  %s\n" "$1"
  ok=false
}

require_non_empty() {
  local key="$1"
  local value="${!key-}"
  if [[ -z "$value" ]]; then
    print_fail "$key 값이 없습니다"
    return 1
  fi
  print_ok "$key 설정됨"
  return 0
}

require_prefix() {
  local key="$1"
  local prefix="$2"
  local value="${!key-}"
  if [[ -z "$value" ]]; then
    print_fail "$key 값이 없습니다"
    return 1
  fi
  if [[ "$value" != "$prefix"* ]]; then
    print_fail "$key 값은 '$prefix'로 시작해야 합니다"
    return 1
  fi
  print_ok "$key 접두사 확인 완료"
  return 0
}

check_db_url() {
  local db="${DATABASE_URL-}"
  if [[ -z "$db" ]]; then
    print_fail "DATABASE_URL 값이 없습니다"
    return
  fi
  if [[ "$db" == *"sqlite"* ]]; then
    print_fail "DATABASE_URL이 sqlite를 사용 중입니다 (프로덕션 금지)"
    return
  fi
  if [[ "$db" == postgresql+asyncpg://* ]]; then
    print_ok "DATABASE_URL이 postgresql+asyncpg 형식입니다"
    return
  fi
  if [[ "$db" == postgres://* ]] || [[ "$db" == postgresql://* ]]; then
    print_warn "DATABASE_URL이 postgres/postgresql 스킴입니다 (런타임 자동 보정 가능, asyncpg 권장)"
    return
  fi
  print_warn "DATABASE_URL 스킴이 일반적이지 않습니다. SQLAlchemy async 호환성을 확인하세요"
}

echo "== GhostLink 프로덕션 환경변수 검증 =="

require_non_empty "ENVIRONMENT" || true
if [[ "${ENVIRONMENT-}" != "production" ]]; then
  print_fail "ENVIRONMENT는 'production'이어야 합니다"
else
  print_ok "ENVIRONMENT=production 확인"
fi

require_non_empty "FRONTEND_URL" || true
if [[ "${FRONTEND_URL-}" == *"localhost"* ]]; then
  print_fail "FRONTEND_URL이 localhost를 가리킵니다"
fi

check_db_url

require_prefix "STRIPE_SECRET_KEY" "sk_live_" || true
require_prefix "STRIPE_PUBLISHABLE_KEY" "pk_live_" || true
require_prefix "STRIPE_WEBHOOK_SECRET" "whsec_" || true

require_non_empty "STRIPE_PRICE_STARTER_MONTH" || true
require_non_empty "STRIPE_PRICE_STARTER_YEAR" || true
require_non_empty "STRIPE_PRICE_PRO_MONTH" || true
require_non_empty "STRIPE_PRICE_PRO_YEAR" || true

if [[ -z "${STRIPE_PRICE_ENTERPRISE_MONTH-}" ]] || [[ -z "${STRIPE_PRICE_ENTERPRISE_YEAR-}" ]]; then
  print_warn "Enterprise 월/연 가격 ID가 비어 있습니다 (영업 문의 전용이면 허용)"
else
  print_ok "Enterprise 월/연 가격 ID 설정됨"
fi

if [[ -z "${SALES_CONTACT_EMAIL-}" ]]; then
  print_warn "SALES_CONTACT_EMAIL이 비어 있습니다 (앱 기본값으로 대체됨)"
else
  print_ok "SALES_CONTACT_EMAIL 설정됨"
fi

if [[ "$ok" == true ]]; then
  echo "== 결과: 통과 =="
  exit 0
fi

echo "== 결과: 실패 =="
exit 1
