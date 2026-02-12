# RBAC 정책 매트릭스

## 역할 정의

- `owner`: 조직 최고 권한
- `admin`: 운영/결제/승인 관리 권한
- `member`: 일반 사용 권한
- `superuser`: 시스템 전체 관리자

## 권한 매트릭스

| 기능 | owner | admin | member | superuser |
|---|---|---|---|---|
| 대시보드/리포트 조회 | O | O | O | O |
| 결제 변경 실행 | O | O | X(승인 요청) | O |
| 승인 요청 검토(approve/reject) | O | O | X | O |
| API 키 발급/폐기 | O | O | X | O |
| 조직 설정 변경 | O | O | 제한 | O |
| 관리자 CRM 전체 조회 | X | X | X | O |
| 관리자 CRM 조직 범위 조회 | O | O | X | O |

## 정책 원칙

- member의 민감 작업은 승인 요청으로 우회
- 감사 로그는 가능한 모든 변경 이벤트에 기록
- 조직 경계를 넘는 조회/수정은 superuser만 허용
