# GhostLink 고객 사이트 적용 가이드

작성일: 2026-02-08

## 1) 핵심 결론

1. 가능한 경우 `index.html` 단독 삽입보다 `공통 템플릿(레이아웃)` 또는 `태그 매니저(GTM)` 배포가 더 안전합니다.
2. `index.html` 삽입은 정적 단일 엔트리 사이트에서는 유효하지만, CMS/SSR/멀티 템플릿 환경에서는 누락 위험이 큽니다.
3. 배포 후 GhostLink의 7일 감지 지표(`script requests`, `bridge events`)로 설치 성공 여부를 검증해야 합니다.

## 2) 기본 삽입 스니펫

```html
<script async src="https://{your-ghostlink-domain}/api/bridge/{script_id}.js"></script>
```

원칙:

1. 공통 head에서 1회만 삽입
2. 페이지별 중복 삽입 금지
3. CSP 사용 시 GhostLink 도메인 허용 필요

## 3) 적용 방식 선택표

### A. 정적 사이트 (단일 index.html)
- 적용 위치: `index.html`의 `</head>` 직전
- 장점: 구현 단순
- 주의: 다중 HTML 파일이면 모든 엔트리에 동기 반영 필요

### B. CMS / 템플릿 엔진
- 적용 위치: 글로벌 레이아웃 템플릿(head/footer)
- 장점: 전체 페이지 동시 배포
- 권장도: 높음

### C. 태그 매니저 (GTM)
- 적용 위치: Custom HTML Tag (All Pages)
- 장점: 코드 배포 없이 운영팀이 즉시 적용/롤백 가능
- 권장도: 매우 높음

### D. Edge 배포 API
- 적용 위치: GhostLink `edge` artifact/deployment 흐름
- 장점: staging/production 분리와 롤백 자동화
- 권장도: 대규모 운영 환경에서 높음

## 4) index.html이 정답인 경우 / 아닌 경우

index.html이 정답인 경우:

1. 사이트가 정적이며 실제 엔트리가 index 하나인 경우
2. 프론트 빌드가 index 단일 진입점으로 운영되는 경우

index.html만으로 부족한 경우:

1. Next.js/Nuxt 같은 SSR 프레임워크
2. 다중 템플릿 CMS(랜딩/블로그/상점 분리)
3. 서브도메인/멀티도메인 동시 운영

## 5) 운영 체크리스트

1. 삽입 후 5~10분 내 `/api/bridge/{script_id}.js` 요청 발생 확인
2. GhostLink 리포트에서 `Script requests (7d)`, `Bridge events (7d)` 증가 확인
3. 이벤트 미수집 시:
- 캐시/CDN 전파 지연 확인
- CSP/SRI 차단 확인
- 태그매니저 게시(Publish) 여부 확인

## 6) 권장 운영 시나리오

1. 0일차: 템플릿/GTM로 스크립트 삽입
2. 1일차: 설치 감지 및 첫 스캔 확인
3. 2~7일차: 프루프 센터에서 ACR/Citation/AI Assist 측정
4. 2주차 이후: 자동 최적화 승인 루프로 개선-검증 자동화
