# GhostLink

GhostLink는 웹사이트의 AI 가시성과 검색 노출 품질을 개선하기 위한 SaaS 플랫폼입니다.  
핵심 목표는 "측정 가능한 개선"이며, 분석부터 실행, 승인, 보고까지 하나의 흐름으로 제공합니다.

## 주요 기능

- AI 친화 구조화 데이터(JSON-LD) 및 `llms.txt` 생성
- 프루프 센터(Proof Center) 기반 핵심 지표 측정
  - ACR(응답 포착률)
  - 출처 인용률(Citation Rate)
  - AI 보조율(AI Assist Rate)
- 자동 최적화 루프(v1/v2)와 승인 워크플로우
- Stripe 기반 결제/구독/인보이스 연동
- 일일 리포트(JSON/PDF) 생성
- 관리자 CRM 페이지(`/admin`) 제공

## 기술 스택

- 백엔드: FastAPI, SQLModel, SQLAlchemy 비동기 스택
- DB: PostgreSQL(프로덕션), SQLite(로컬 테스트)
- 인증: 세션 + OAuth(선택)
- 결제: Stripe
- 템플릿: Jinja2

## 빠른 시작

### 1) 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 환경변수

`.env`를 생성하고 최소값을 설정합니다.

```env
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./ghostlink.db
FRONTEND_URL=http://localhost:8000
SECRET_KEY=change-me
```

Stripe 기능을 사용할 경우 아래도 추가합니다.

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### 3) 실행

```bash
uvicorn app.main:app --reload
```

기본 접속: `http://localhost:8000`

## 결제/요금제 정책

- 공개 요금제는 3단계: `starter`, `pro`, `enterprise`
- 레거시 `business`는 내부에서 `pro`로 정규화되어 하위호환
- `/billing/plans`는 3단계만 반환

## 웹훅

- 엔드포인트: `POST /webhooks/stripe`
- 멱등 처리: `(provider, event_id)` 기준 중복 방지
- 주요 이벤트:
  - `checkout.session.completed`
  - `customer.subscription.created|updated|deleted`
  - `invoice.payment_succeeded|failed`

## 관리자 기능

- `/admin`에서 조직 CRM + 사용자 CRM + 결제 상태를 확인
- superuser는 전체 조회 가능
- owner/admin은 조직 범위 조회 가능

## 테스트

```bash
PYTHONPATH=. DATABASE_URL='sqlite+aiosqlite:///./ghostlink_test.db' ENVIRONMENT=development DB_AUTO_INIT_ON_STARTUP=true pytest -q
```

## 배포 권장 절차

1. Vercel 프로덕션 환경변수 설정
2. `scripts/validate_prod_env.sh`로 사전 검증
3. 배포 후 Stripe 웹훅/결제 스모크 테스트 실행

관련 문서:
- `docs/STRIPE_PRODUCTION_CUTOVER_CHECKLIST_2026-02-12.md`
- `docs/ENV_PRODUCTION_VALIDATION_2026-02-12.md`

## 운영 원칙

- 측정값(`measured`)과 예측값(`predicted`)을 구분해 표시
- 권한 기반 승인 절차를 기본으로 적용
- 변경 이력 및 감사 로그를 보존

## 지원

- 영업: `sales@ghostlink.io`
- 지원: `support@ghostlink.io`
