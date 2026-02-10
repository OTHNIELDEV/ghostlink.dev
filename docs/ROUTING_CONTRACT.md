# GhostLink 공개 라우팅 계약 (v1)

업데이트: 2026-02-07

## 목적
- 프론트엔드/백엔드/연동 파트가 안정적인 공개 URL 기준으로 동기화되도록 유지
- 중복 prefix(예: `/billing/billing/*`, `/webhooks/webhooks/*`) 재발 방지

## 규칙
- prefix는 한 곳에서만 선언한다.
  - `APIRouter(prefix=...)` 또는
  - `app.include_router(..., prefix=...)`
- 동일 세그먼트에 대해 두 곳에서 중복 선언하지 않는다.

## 공개 웹 페이지
- `GET /`
- `GET /dashboard`
- `GET /report/{site_id}`
- `GET /settings`
- `GET /billing`
- `GET /approvals`
- `GET /features`
- `GET /users/profile`

## 공개 API 라우트
- Sites: `/api/sites`
- Organizations: `/api/organizations`
- API Keys: `/api/api-keys`
- Billing: `/billing/*`
- Webhooks: `/webhooks/stripe`
- Optimizations: `/api/v1/optimizations/*`
- Approvals: `/api/v1/approvals/*`
- Audit Logs: `/api/v1/audit-logs`

## 소유 매트릭스
| 라우트 그룹 | 소스 파일 |
|---|---|
| `/api/sites` | `app/routers/sites.py` |
| `/api/dashboard` | `app/routers/dashboard.py` |
| `/api/bridge` | `app/routers/bridge.py` |
| `/billing` | `app/routers/billing.py` |
| `/api/organizations` | `app/routers/organizations.py` |
| `/api/api-keys` | `app/routers/api_keys.py` |
| `/webhooks` | `app/routers/webhooks.py` |
| `/api/v1/optimizations` | `app/routers/optimizations.py` |
| `/api/v1/approvals` | `app/routers/approvals.py` |
| `/api/v1/audit-logs` | `app/routers/audit_logs.py` |

## 검증 체크리스트
- `GET /billing/plans` 응답 `200`
- `GET /billing/billing/plans` 응답 `404`
- `POST /webhooks/stripe` 접근 가능
- `POST /webhooks/webhooks/stripe` 응답 `404`
- `GET /api/api-keys?org_id=<id>`는 비인증 시 `401`

## 변경 절차
1. 라우트 변경 시 이 계약 문서를 먼저 갱신
2. `README.md`의 endpoint 섹션 반영
3. 머지 전 라우트 스모크 테스트 추가/수정
