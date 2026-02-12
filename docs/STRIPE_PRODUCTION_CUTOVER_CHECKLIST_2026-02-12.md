# Stripe 프로덕션 전환 체크리스트 (GhostLink)

## 1) 환경변수 점검 (Vercel 프로덕션)
- `STRIPE_SECRET_KEY`: 라이브 키 (`sk_live_...`)
- `STRIPE_WEBHOOK_SECRET`: Stripe 대시보드에서 발급된 웹훅 서명 시크릿
- `STRIPE_PRICE_STARTER_MONTH`
- `STRIPE_PRICE_STARTER_YEAR`
- `STRIPE_PRICE_PRO_MONTH`
- `STRIPE_PRICE_PRO_YEAR`
- `STRIPE_PRICE_ENTERPRISE_MONTH` (엔터프라이즈가 영업 문의 전용이면 선택)
- `STRIPE_PRICE_ENTERPRISE_YEAR` (엔터프라이즈가 영업 문의 전용이면 선택)
- `FRONTEND_URL`: 프로덕션 주소 (결제 성공/취소 리디렉션 주소의 호스트와 동일해야 함)
- `ENVIRONMENT=production`
- `DATABASE_URL`: 프로덕션 PostgreSQL URL (SQLite 금지)

참고:
- 레거시 `business` 요금제 코드는 내부에서 `pro`로 정규화되어 하위호환됩니다.
- 기존 Stripe 가격 ID가 아직 트래픽에 남아있다면, 마이그레이션 완료 전까지 `STRIPE_PRICE_BUSINESS_*`를 유지하세요.

## 2) Stripe 웹훅 엔드포인트
- 엔드포인트 URL: `https://<도메인>/webhooks/stripe`
- Stripe에서 아래 이벤트 구독:
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_succeeded`
  - `invoice.payment_failed`
  - `customer.subscription.trial_will_end`
- 엔드포인트가 **라이브 모드**인지, 시크릿이 `STRIPE_WEBHOOK_SECRET`와 일치하는지 확인

## 3) DB / 멱등성 사전 조건
- `processedwebhookevent` 테이블의 `(provider, event_id)` 유니크 제약 활성화 확인
- `auditlog` 시퀀스 상태 정상 확인  
  - 서비스에 자동 복구 로직이 있지만 DB 상태는 별도 점검 권장
- 활성 조직(`organization`)마다 `subscription` 레코드 존재 여부 확인

## 4) 프로덕션 스모크 테스트 (필수 통과)

### A. 요금제 API가 3단계만 노출되는지 확인
- 요청: `GET /billing/plans`
- 기대값: `starter`, `pro`, `enterprise`만 반환
- 공개 API 응답에 `business`가 포함되면 안 됨

### B. Checkout 시작 플로우
- owner/admin 권한 사용자로:
  - `POST /billing/checkout` 요청에 `plan_code=starter`, `interval=month`, 유효한 `org_id` 포함
  - Stripe Checkout 이동 주소(`redirect_url`) 반환 확인

### C. 웹훅 수신/처리 확인
- 실제 결제(또는 통제된 라이브 유사 시나리오) 완료
- Stripe 대시보드에서 웹훅 전송 결과가 HTTP 200인지 확인
- 앱 DB에서:
  - `processedwebhookevent.status = processed`
  - `subscription.plan_code`가 `starter/pro/enterprise` 중 하나로 갱신
  - `subscription.stripe_subscription_id`, `subscription.stripe_customer_id` 저장 확인

### D. 인보이스 적재 확인
- `invoice.payment_succeeded` 이벤트 발생
- `invoice` 테이블에 `org_id`가 유효한 값(0/null 아님)으로 저장되는지 확인
- Billing/Admin 페이지에서 해당 조직 최신 인보이스 표시 확인

### E. 권한/승인 플로우 확인
- owner/admin이 아닌 사용자가 결제 변경 시도:
  - `approval_requested` 응답 확인
- owner/admin 승인:
  - 승인 상태 전이와 실행 결과 정상 확인

### F. 최적화 루프 안정성 확인
- 리포트 페이지 `액션 생성(Generate Actions)`(v1)에서 500 미발생
- `다음 결정(Decide Next v2)`에서 `MissingGreenlet` 없이 정상 응답

## 5) 배포 후 24시간 모니터링
- 500 에러율 모니터링:
  - `/api/v1/optimizations/sites/*/actions/generate`
  - `/api/v1/optimizations/sites/*/actions/decide-v2`
  - `/webhooks/stripe`
- 주요 로그 패턴 감시:
  - `MissingGreenlet`
  - `duplicate key value violates unique constraint "auditlog_pkey"`
  - `Error processing webhook`
  - `Skipping invoice record because org_id could not be resolved`

## 6) 롤백/복구 가이드
- Stripe 가격 매핑이 잘못된 경우:
  - Vercel `STRIPE_PRICE_*` 수정
  - 재배포
  - Stripe 대시보드에서 실패 웹훅 재전송
- 웹훅 서명 검증 실패 시:
  - Stripe 웹훅 시크릿 재발급
  - `STRIPE_WEBHOOK_SECRET` 갱신
  - 재배포 후 최근 실패 이벤트 재전송

## 7) 운영 메모
- `/admin` 페이지는 superuser 전체 조회 + owner/admin 조직 범위 조회를 지원
- 조직 범위 admin 접근 시 사용자 CRM 목록은 해당 조직 구성원으로 제한
- 레거시 결제 데이터도 `business -> pro` alias로 Checkout 중단 없이 처리 가능
