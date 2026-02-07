# GhostLink 프로젝트 재점검 보고서 (2026-02-07)

## 1) 점검 목적
- 현재 GhostLink의 실제 작동 상태를 기능/운영/기획 관점에서 재진단
- 작동 불가 또는 실패 가능성이 높은 구간 식별
- 단기 복구안 + 중장기 혁신안 + 실행 로드맵 제시

## 2) 점검 방식
- 코드 정적 점검: 라우터, 서비스, 템플릿, 설정, 모델
- 런타임 검증: FastAPI TestClient로 주요 플로우 재현
- 경로/권한/결제/웹훅/DB 일관성 중심 점검

## 3) 핵심 결론 (Executive Summary)
- 현재 상태는 **MVP 데모 수준은 가능**하지만, 실제 SaaS 운영 기준으로는 **핵심 결제/조직/API 경로가 단절**되어 상용 전환이 불가합니다.
- 가장 큰 이슈는 `라우터 경로 설계 불일치`, `결제 파라미터 불일치`, `조직 권한 검증 누락`, `웹훅 인보이스 처리 실패`입니다.
- 단기(1주) 내 구조 정리로 “작동 가능한 상용 베이스”까지 복구 가능하며, 이후 차별화는 “AI 가시성 측정 + 자동 최적화 루프”에 집중하는 것이 가장 효율적입니다.

---

## 4) 현재 작동 불가/고위험 항목

### P0 (즉시 수정 필요)

1. 결제/조직/API/Webhook 라우트 경로가 UI/README와 불일치
- 현상:
  - 문서/템플릿은 `/billing/plans`, `/api/organizations`, `/webhooks/stripe`를 사용
  - 실제 라우트는 `/billing/billing/plans`, `/api/organizations/organizations`, `/webhooks/webhooks/stripe`
- 근본 원인:
  - `app.main`의 `include_router(..., prefix=...)`와 각 라우터 내부 `APIRouter(prefix=...)`가 중복
- 근거 코드:
  - `app/main.py`
  - `app/routers/billing.py`
  - `app/routers/organizations.py`
  - `app/routers/api_keys.py`
  - `app/routers/webhooks.py`
- 영향:
  - 프론트/외부 연동(Stripe webhook 포함) 대부분 실패

2. 결제 체크아웃 호출 파라미터 불일치로 422 발생
- 현상:
  - 템플릿은 `plan_id`를 전송
  - 백엔드는 `plan_code`(query) 요구
  - POST body 전송인데 FastAPI에서 query 필드로 해석되어 검증 실패
- 근거 코드:
  - `app/templates/pages/billing.html`
  - `app/routers/billing.py`
- 영향:
  - 업그레이드 결제 플로우 사용 불가

3. 결제 API 조직 권한 검증 누락 (보안 취약)
- 현상:
  - 로그인 사용자 B가 사용자 A의 `org_id`로 결제 API 호출 가능
- 근본 원인:
  - billing 라우터에서 `org_id` 소유권/멤버십 검증 없음
- 근거 코드:
  - `app/routers/billing.py`
- 영향:
  - 타 조직 플랜 변경 가능성, 멀티테넌트 보안 위협

4. API Keys 엔드포인트 비인증 접근 시 500
- 현상:
  - 비로그인 상태에서 `/api/api-keys/api-keys?org_id=1` 호출 시 500
- 근본 원인:
  - `get_org_from_request`에서 `user is None` 처리 없이 `user.id` 접근
- 근거 코드:
  - `app/routers/api_keys.py`
- 영향:
  - 인증 에러가 401/403이 아닌 500으로 노출, 안정성/보안 신뢰 저하

### P1 (상용 운영 전 필수 수정)

5. 웹훅 인보이스 저장 로직 런타임 에러
- 현상:
  - invoice 처리 시 `datetime is not defined`
- 근본 원인:
  - `app/routers/webhooks.py`에서 `datetime` 미임포트
- 영향:
  - 매출/청구 이력 누락, 재무 데이터 신뢰도 하락

6. Stripe 구독 동기화 시 `plan_code` 미반영
- 현상:
  - Stripe price ID는 저장되나 plan_code는 계속 `free`
- 근본 원인:
  - `update_subscription_from_stripe`에서 price_id → plan_code 매핑 부재
- 근거 코드:
  - `app/services/subscription_service.py`
- 영향:
  - 권한/쿼터/요금 표시가 실제 결제 상태와 불일치

7. 월말(12월) 사용량 기록 함수 잠재 크래시
- 현상:
  - `month + 1` 방식으로 12월 처리 시 `ValueError`
- 근거 코드:
  - `app/services/subscription_service.py` (`record_usage`)
- 영향:
  - 연말 시점 사용량 기록 실패 가능

### P2 (품질/운영 효율 이슈)

8. Billing 페이지 데이터 계약 불일치
- 현상:
  - JS는 배열/`id`/문자열 feature 가정, API는 `{plans, currency}` + `code` + 객체 feature 반환
- 근거 코드:
  - `app/templates/pages/billing.html`
  - `app/routers/billing.py`
- 영향:
  - 플랜 렌더링 비정상, fallback 데이터 의존

9. 사이드바 사용자 표시 하드코딩
- 현상:
  - `user@example.com` 고정 텍스트
- 근거 코드:
  - `app/templates/components/sidebar.html`
- 영향:
  - UX 신뢰도 저하, 멀티유저 인식 오류

---

## 5) 혁신적 개선 제안 (차별화 관점)

### A. GhostLink 핵심 가치 재정의: “생성”에서 “성과 증명”으로
- 현재 강점: JSON-LD/llms.txt 생성
- 제안: **AI Visibility Scoreboard** 추가
  - 검색엔진 + LLM 크롤러별 노출/클릭/인덱스 반영 추적
  - “적용 전/후” uplift 자동 비교
  - 조직별 KPI 대시보드 제공

### B. Auto-Optimize Loop (반자동 최적화)
- 크롤링/분석 결과 기반으로:
  - 추천안 생성
  - 승인 워크플로우
  - 브릿지 스크립트/자산 자동 배포
  - 재측정까지 하나의 루프로 연결
- 효과: 툴 사용자가 “리포트 읽기”에서 “성과 달성”으로 이동

### C. Agent-Ready Compliance Layer
- 기업 고객용 신뢰 기능:
  - 변경 이력(Audit Log)
  - 정책 템플릿(금칙어, 산업 규제)
  - 승인된 지침만 배포
- 효과: Enterprise 판매 전환율 상승

### D. API Productization
- 현재 API Key 수준에서 확장:
  - 버전드 API (`/api/v1`)
  - Webhook 이벤트 표준화
  - SDK/CLI 제공
- 효과: 파트너/에이전시 생태계 형성

---

## 6) 실행 로드맵 (우선순위 기반)

## Phase 0: 안정화 (1주)
- 라우터 prefix 중복 제거 (단일 규칙 정립)
- 결제 파라미터 계약 통일 (`plan_code`, `org_id` 전송 방식 고정)
- billing 라우터에 조직 멤버십 검증 추가
- webhooks 인보이스 처리 에러 수정 (`datetime` import)
- API key dependency에서 비인증 401 처리

완료 기준:
- 결제 업그레이드 E2E 성공
- webhook 수신/구독 상태 반영/인보이스 저장 성공
- `/billing/plans`, `/api/organizations`, `/webhooks/stripe` 정상 응답

## Phase 1: 상용 준비 (2~3주)
- `plan_code` 동기화 로직 구현 (price_id 매핑 테이블)
- 사용량 기록 월경계 로직 수정
- Billing 페이지 데이터 계약 정합화 (백엔드/프론트 타입 통일)
- 최소 자동화 테스트 세트 구축 (auth/org/billing/webhook/api-key)

완료 기준:
- 핵심 경로 테스트 자동화
- 월경계/결제 상태 불일치 0건

## Phase 2: 성장 기능 (4~8주)
- AI Visibility Scoreboard
- Auto-Optimize Loop v1
- 조직/권한 고도화 (역할별 정책, 승인 플로우)
- 보고서 내 “성과 증거” 섹션 강화

완료 기준:
- 리텐션/활성 사용량 지표 개선
- 유료 전환 퍼널 가시화

---

## 7) 운영 KPI 제안
- Activation: 첫 사이트 등록 후 24시간 내 첫 스캔 완료율
- Value: 스캔 후 실제 브릿지 설치율
- Retention: 주간 활성 조직 비율
- Revenue: Free→Paid 전환율, Paid 유지율
- Reliability: 핵심 API 5xx 비율, webhook 처리 성공률

---

## 8) 즉시 실행 체크리스트 (기획자 관점)
- [ ] 라우팅 표준(공개 URL 계약) 문서화 및 백엔드/프론트 동기화
- [ ] 결제/조직 권한 모델 확정 (누가 어떤 org 결제 가능한지)
- [ ] Stripe 이벤트별 상태전이 다이어그램 작성
- [ ] “성과 증명 중심” 대시보드 요구사항 정의
- [ ] Phase 0 완료 전 외부 배포/마케팅 홀드

---

## 9) 최종 판단
- GhostLink는 방향성이 좋고 핵심 아이디어(LLM 친화 자산 생성)는 유효합니다.
- 다만 현재는 **경로/권한/결제 일관성 문제로 제품 신뢰를 잃기 쉬운 상태**입니다.
- 우선 1주 안정화로 “신뢰 가능한 기본기”를 복구한 뒤, 8주 내 “성과 증명형 AIO 플랫폼”으로 포지셔닝하면 경쟁력이 높습니다.

---

## 10) 추가 혁신 제안 (확장판)

### I. Answer Capture Lab (A/B 시뮬레이터)
- 개념: 주요 LLM(예: GPT/Claude/Gemini) 질의 세트를 고정하고, 사이트 변경 전/후 답변 내 브랜드 언급/링크/정확도 변화를 자동 측정
- 핵심 지표: ACR(Answer Capture Rate), Citation Rate, Negative Hallucination Rate
- 기대효과: “트래픽”이 아니라 “실제 답변 점유율”을 제품 핵심 KPI로 전환
- 첫 구현 단위: 주간 50개 질의 배치 실행 + 리포트 비교 카드

### II. Auto-Optimize Loop v2 (멀티암드 밴딧)
- 개념: 추천 액션을 동시에 여러 개 실험하고 성과 좋은 패턴을 자동으로 더 많이 배분
- 기술: Thompson Sampling 또는 UCB 기반 실험 정책
- 기대효과: 운영자 수동 판단 없이 최적화 속도 가속
- 첫 구현 단위: 액션별 보상함수(노출/클릭/전환 가중치) 정의 + 실험 로그 테이블

### III. Brand Knowledge Graph + Schema Copilot
- 개념: 브랜드 엔터티(제품, 기능, 가격, 정책, FAQ)를 그래프로 관리하고 JSON-LD/llms.txt를 일관 생성
- 기술: 엔터티 정규화 + 충돌 감지 + 스키마 검증 파이프라인
- 기대효과: 대규모 사이트에서도 문서/스키마 불일치 감소
- 첫 구현 단위: 핵심 엔터티 5종(Organization/Product/Offer/FAQ/Article) 그래프 모델링

### IV. AI Traffic Quality Attribution
- 개념: 단순 bot 카운트가 아닌 “AI 유입 이후 실제 전환 영향”을 추정
- 기술: 세션 체인 분석 + 시차 기여 모델 + 리퍼러/UTM 결합
- 기대효과: 고객이 요금 지불할 명확한 ROI 근거 확보
- 첫 구현 단위: “AI-assisted conversion” 이벤트 정의 + 대시보드 기여도 카드

### V. Policy-as-Code Compliance Gate
- 개념: 의료/금융/법률 등 산업 규칙을 코드로 선언하고, 배포 전 자동 정책 검사
- 기술: 룰 엔진(금칙어/표현 가이드/필수 고지문) + 승인 워크플로우 연계
- 기대효과: 엔터프라이즈 도입 장벽(리스크/컴플라이언스) 대폭 완화
- 첫 구현 단위: 규칙셋 버전관리 + 위반 리포트 + 승인 차단 옵션

### VI. Edge Runtime Delivery
- 개념: JSON-LD/llms.txt를 CDN/Edge Worker에서 즉시 배포하고 롤백
- 기술: 아티팩트 서명 + 캐시 무효화 + 버전 라우팅
- 기대효과: 대규모 트래픽 환경에서 배포 안정성과 반영 속도 향상
- 첫 구현 단위: `production/staging` 이중 채널 배포 + 1클릭 롤백

---

## 11) 확장 로드맵 제안 (Phase 3, 8~16주)
- Phase 3-A (8~10주): Answer Capture Lab + KPI 파이프라인
- Phase 3-B (10~12주): Auto-Optimize Loop v2(실험 정책 엔진)
- Phase 3-C (12~14주): Knowledge Graph + Schema Copilot
- Phase 3-D (14~16주): Compliance Gate + Edge Runtime Delivery

완료 기준:
- ACR/Citation KPI가 조직별로 주간 집계되고 추세 비교 가능
- 자동 실험 정책으로 “수동 승인만 하던 단계”에서 “정책 기반 자동 실행” 단계로 전환
- 엔터프라이즈 고객 대상 컴플라이언스 리포트 자동 생성 가능

---

## 12) 즉시 실행 반영 현황 (2026-02-07)
- Top-2 우선순위 확정:
  - #1 Answer Capture Lab
  - #2 AI Traffic Quality Attribution
- v1 백엔드 베이스 구현 완료:
  - DB 모델, 서비스, API 라우터, 감사로그 이벤트, 기본 스모크 검증
- 상세 실행 명세 문서:
  - `docs/PHASE3_TOP2_EXECUTION_PLAN.md`

## 13) 확장 구현 반영 현황 (2026-02-07, same day)
- Phase 3의 나머지 4개 기능 v1까지 연속 구현 완료:
  - Auto-Optimize Loop v2 (Bandit decision/feedback)
  - Brand Knowledge Graph + Schema Copilot
  - Policy-as-Code Compliance Gate
  - Edge Runtime Delivery (artifact build/deploy/rollback)
- 핵심 반영:
  - 신규 DB 모델(밴딧/그래프/컴플라이언스/엣지) 추가 및 초기화 연결
  - `/api/v1` 라우터 연결 및 감사로그 이벤트 연동
  - `bridge.js` 응답 경로에 production edge artifact 우선 적용 로직 추가
  - 통합 시나리오 테스트 추가: `tests/test_remaining_innovations.py`
- 검증 상태:
  - `python3 -m compileall -q app tests` 통과
  - `ENVIRONMENT=production python3 scripts/smoke_billing_security.py` 통과
  - 신규 기능 수동 스모크(밴딧/지식그래프/컴플라이언스/엣지) 통과
