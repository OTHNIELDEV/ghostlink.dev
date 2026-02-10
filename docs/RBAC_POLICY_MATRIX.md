# GhostLink RBAC 정책 매트릭스 (2026-02-07)

## 조직 역할
- `owner`: 조직 결제, 승인, 멤버, API 키, 최적화 승인 작업까지 전체 제어
- `admin`: owner와 유사한 수준의 운영 제어 권한
- `member`: 기본 조회/작업은 가능하나 민감 변경은 승인 필요

## 정책 요약
| 기능 | Owner | Admin | Member | 적용 방식 |
|---|---|---|---|---|
| 조직 범위 리소스 조회 | 허용 | 허용 | 허용 | 조직 멤버십 검증 |
| 결제 직접 변경 | 허용 | 허용 | 거부 | `/billing/*` + 역할 검증 |
| 결제 변경 승인 요청 | 허용(선택) | 허용(선택) | 허용 | 승인 요청 API |
| 승인 요청 승인/반려 | 허용 | 허용 | 거부 | `/api/v1/approvals/{id}/approve|reject` |
| API 키 생성/폐기 | 허용 | 허용 | 거부 | `/api/api-keys` |
| 감사 로그 조회 | 허용 | 허용 | 거부 | `/api/v1/audit-logs` |
| 최적화 액션 생성 | 허용 | 허용 | 허용 | 조직 멤버십 검증 |
| 최적화 액션 적용/반려 | 허용 | 허용 | 허용 | 조직 멤버십 검증 |

## 엔드포인트 매핑
- `GET /api/v1/approvals`: 조직 멤버 누구나 조회 가능
- `POST /api/v1/approvals`: 조직 멤버 누구나 요청 등록 가능
- `POST /api/v1/approvals/{request_id}/approve`: owner/admin 전용
- `POST /api/v1/approvals/{request_id}/reject`: owner/admin 전용
- `GET /api/v1/audit-logs`: owner/admin 전용
- `POST /billing/checkout|cancel|reactivate`: owner/admin은 직접 실행, member는 `request_approval=true` 필요
- `POST /api/api-keys`, `DELETE /api/api-keys/{id}`: owner/admin 전용

## UI 규칙
- 사이드바에 `Approvals` 메뉴와 현재 조직 pending 개수 배지 노출
- pending 요청이 있으면 Dashboard에 `Pending Approval Inbox` 노출
- 전용 인박스 페이지: `GET /approvals?org_id=<id>`

## 참고
- 모든 조직 범위 호출은 `org_id`를 포함해야 하며 `Membership`으로 검증됩니다.
- 승인/결제/API 키/최적화 작업은 audit 이벤트가 누적 기록됩니다.
