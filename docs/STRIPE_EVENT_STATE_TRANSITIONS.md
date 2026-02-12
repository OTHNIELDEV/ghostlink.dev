# Stripe 이벤트 상태 전이

## 목적

Stripe 웹훅 이벤트가 내부 구독/인보이스 상태에 어떤 영향을 주는지 정의합니다.

## 이벤트별 처리

### `checkout.session.completed`
- Checkout 완료 시 구독 정보를 Stripe에서 조회
- 조직(`org_id`) 기준으로 내부 구독 갱신

### `customer.subscription.created` / `updated`
- 내부 `subscription` 상태/기간/플랜 코드 동기화

### `customer.subscription.deleted`
- 내부 상태를 `canceled`로 반영
- 플랜 코드를 `free`로 전환

### `invoice.payment_succeeded`
- 인보이스 중복 여부 확인 후 저장
- 조직 매핑 순서:
  1. `metadata.org_id`
  2. `subscription_id`로 구독 조회
  3. `customer_id`로 구독 조회

### `invoice.payment_failed`
- 해당 구독 상태를 `past_due`로 반영

## 멱등성

- `(provider, event_id)` 유니크 제약으로 중복 이벤트 차단
- 이미 처리된 이벤트는 `duplicate=true`로 무시
