# 고객 사이트 연동 가이드

## 개요

고객 사이트는 `bridge` 스크립트를 1회 삽입하여 GhostLink 이벤트 수집을 시작할 수 있습니다.

## 기본 삽입 코드

```html
<script async src="https://<ghostlink-domain>/api/bridge/<script_id>.js"></script>
```

## 적용 위치

- 권장: 공통 레이아웃의 `</head>` 직전 또는 `</body>` 직전
- SPA/MPA 모두 사용 가능

## 동작 흐름

1. 페이지 로드 시 스크립트가 초기화됩니다.
2. 페이지뷰/체류/이탈 이벤트가 수집됩니다.
3. 서버에서 정규화 후 Proof/리포트 지표에 반영됩니다.

## 점검 항목

- 연동 가이드 페이지에서 설치 감지 상태 확인
- 최근 7일 `script_request_count`, `bridge_event_count` 확인
- 이벤트 유실/드롭 사유 여부 확인

## 보안 권장사항

- 서명 시크릿(`BRIDGE_SIGNING_SECRET`) 사용
- 민감정보(PII) 수집 금지
- 토큰 만료/재발급 정책 유지
