# 라우팅 계약서

## 목적

프론트엔드 템플릿 라우트와 API 라우트의 계약을 명확히 하여 회귀를 방지합니다.

## 페이지 라우트

- `/dashboard`
- `/report/{site_id}`
- `/proof`
- `/approvals`
- `/billing`
- `/admin`

## 결제/승인 API

- `GET /billing/plans`
- `GET /billing/current`
- `POST /billing/checkout`
- `POST /api/v1/approvals`
- `POST /api/v1/approvals/{id}/approve`
- `POST /api/v1/approvals/{id}/reject`

## 최적화 API

- `POST /api/v1/optimizations/sites/{site_id}/actions/generate`
- `POST /api/v1/optimizations/sites/{site_id}/actions/decide-v2`
- `POST /api/v1/optimizations/actions/{action_id}/approve`
- `POST /api/v1/optimizations/actions/{action_id}/reject`

## 규칙

- 모든 조직 리소스는 `org_id` 컨텍스트로 접근 제어
- 오류 응답은 가능한 명확한 `detail` 포함
- 승인/결제/최적화 주요 이벤트는 감사 로그 기록
