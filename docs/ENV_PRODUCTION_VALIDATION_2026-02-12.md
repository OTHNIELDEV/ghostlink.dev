# 프로덕션 환경변수 검증 스냅샷 (2026-02-12)

기준 파일:
- `.env`
- `.env.local`
- `.env.example`

주의:
- 아래 표는 **로컬 파일 스냅샷** 기준입니다. 실제 배포값은 Vercel 프로젝트 설정(환경변수)에서 최종 확인해야 합니다.
- 민감값은 노출하지 않고 상태만 기록했습니다.

## 1) 핵심 결론
- 현재 `.env`는 Stripe 키가 `test` 모드이며 `ENVIRONMENT=development`입니다.
- 프로덕션 배포 전에는 Stripe 키를 `live`로 전환하고, `ENVIRONMENT=production`으로 설정해야 합니다.
- 요금제는 코드상 3단계(`starter/pro/enterprise`)이며, 가격 변수는 월/연 단위 키를 권장합니다.
- 현재 `.env`에는 레거시 단일 가격키(`STRIPE_PRICE_STARTER/PRO/ENTERPRISE`)만 있고, 월/연 키는 누락되어 있습니다.

## 2) 변수별 검증표

| 변수 | 프로덕션 필수 여부 | `.env` | `.env.local` | 판정 | 조치 |
|---|---|---|---|---|---|
| `ENVIRONMENT` | 필수 | `development` | 누락 | 조치 필요 | Vercel에 `production`으로 설정 |
| `FRONTEND_URL` | 필수 | 설정됨 (`localhost`) | 누락 | 조치 필요 | 실서비스 도메인 URL로 설정 |
| `DATABASE_URL` | 필수 | 설정됨 (sqlite 아님) | 설정됨 (sqlite 아님) | 확인 필요 | Vercel 값이 PostgreSQL(권장 `postgresql+asyncpg://`)인지 확인 |
| `SALES_CONTACT_EMAIL` | 권장 | 누락 (`settings` 기본값 사용) | 누락 | 권장 | 운영 연락 메일 지정 |
| `STRIPE_SECRET_KEY` | 필수 | 설정됨 (`test` 모드) | 누락 | 조치 필요 | `sk_live_...`로 교체 |
| `STRIPE_PUBLISHABLE_KEY` | 필수 | 설정됨 (`test` 모드) | 누락 | 조치 필요 | `pk_live_...`로 교체 |
| `STRIPE_WEBHOOK_SECRET` | 필수 | 설정됨 (`whsec`) | 누락 | 확인 필요 | 라이브 웹훅 엔드포인트 시크릿과 일치 확인 |
| `STRIPE_PRICE_STARTER_MONTH` | 권장 필수 | 누락 | 누락 | 조치 필요 | 라이브 스타터 월 요금 가격 ID 설정 |
| `STRIPE_PRICE_STARTER_YEAR` | 권장 필수 | 누락 | 누락 | 조치 필요 | 라이브 스타터 연 요금 가격 ID 설정 |
| `STRIPE_PRICE_PRO_MONTH` | 권장 필수 | 누락 | 누락 | 조치 필요 | 라이브 프로 월 요금 가격 ID 설정 |
| `STRIPE_PRICE_PRO_YEAR` | 권장 필수 | 누락 | 누락 | 조치 필요 | 라이브 프로 연 요금 가격 ID 설정 |
| `STRIPE_PRICE_ENTERPRISE_MONTH` | 선택\* | 누락 | 누락 | 선택 | 엔터프라이즈를 Stripe 결제로 받을 때만 설정 |
| `STRIPE_PRICE_ENTERPRISE_YEAR` | 선택\* | 누락 | 누락 | 선택 | 엔터프라이즈를 Stripe 결제로 받을 때만 설정 |
| `STRIPE_PRICE_STARTER` (레거시) | 하위호환 | 설정됨 | 누락 | 레거시 | 월/연 키 설정 후 제거 검토 |
| `STRIPE_PRICE_PRO` (레거시) | 하위호환 | 설정됨 | 누락 | 레거시 | 월/연 키 설정 후 제거 검토 |
| `STRIPE_PRICE_ENTERPRISE` (레거시) | 하위호환 | 설정됨 | 누락 | 레거시 | 월/연 키 설정 후 제거 검토 |
| `STRIPE_PRICE_BUSINESS*` (레거시 alias) | 선택 | 설정됨 (`.env` 단일키) | 누락 | 레거시 | `business -> pro` 호환용, 점진 제거 가능 |

\* 현재 코드 흐름상 엔터프라이즈는 영업 문의 플로우로도 처리 가능합니다.

## 3) 코드 연동 체크 포인트
- 요금제 정규화: `business -> pro` alias 적용
  - `app/billing/plans.py`
- Checkout 플랜 검증/정규화
  - `app/routers/billing.py`
- Stripe 가격 ID 역매핑 정규화
  - `app/services/stripe_service.py`
- 웹훅 인보이스 org 매핑 보강 (`metadata -> subscription -> customer` 순)
  - `app/routers/webhooks.py`

## 4) 배포 직전 실행 체크
- Vercel 환경변수 반영 후 아래 스크립트 실행:
  - `bash scripts/validate_prod_env.sh`
- 최소 통과 조건:
  - `ENVIRONMENT=production`
  - `STRIPE_SECRET_KEY` = `sk_live_*`
  - `STRIPE_PUBLISHABLE_KEY` = `pk_live_*`
  - `STRIPE_WEBHOOK_SECRET` = `whsec_*`
  - `DATABASE_URL` non-sqlite
  - `STRIPE_PRICE_STARTER_MONTH/YEAR`, `STRIPE_PRICE_PRO_MONTH/YEAR` 설정
