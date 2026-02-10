# GhostLink 정밀 실행 매뉴얼

작성일: 2026-02-10  
대상: Product, Engineering, Customer Success, Founder

## 0) 구현 업데이트 (2026-02-10)

1. Footer 메뉴 경로가 모두 실제 상세 페이지로 연결됩니다.
2. 실행 보드 경로 `/manual/execution-board`가 활성화되었습니다.
3. 프루프/대시보드/리포트 카드에 증거 라벨(`measured`/`predicted`)과 신뢰도 표시가 반영되었습니다.
4. 일일 리포트 JSON/PDF에 증거 라벨과 프루프 신뢰도 메타데이터가 포함됩니다.
5. 최적화 보상 루프가 baseline/post snapshot 델타 기반으로 동작합니다.
6. 자동 평가 엔드포인트 `POST /api/v1/optimizations/actions/evaluate-applied`를 사용할 수 있습니다.
7. 프루프/일일 리포트에 최적화 액션 기반 고객 신뢰 내러티브 위젯이 추가되었습니다.
8. Footer `status`/`changelog`에 고객 공개용 라이브 타임라인이 표시됩니다.

## 1) 목표

본 매뉴얼은 현재 GhostLink 코드베이스를 아래 목표 중심의 실행 가능한 계획으로 전환합니다.

1. 고객 활성화 속도 개선
2. 측정 가능한 신뢰/증명 신호 확보
3. 예측 가능한 릴리스/지원 운영 체계 구축
4. 즉시 개발 착수 가능한 상태 정리

## 2) 저장소 수준 진단

### 2.1 이미 구축된 강점

1. 멀티테넌트 구조, 조직 단위 스코프, 역할 기반 접근 제어  
   근거: `app/models/organization.py`, `app/routers/organizations.py`, `app/core/rbac.py`
2. 완성도 높은 proof 지표 엔진(ACR, Citation, AI Assist, confidence)  
   근거: `app/services/proof_service.py`
3. 온보딩/고객 여정 UI의 기초 흐름  
   근거: `app/services/onboarding_service.py`, `app/templates/pages/manual.html`, `app/templates/pages/dashboard.html`
4. 구독/결제 및 승인 워크플로  
   근거: `app/routers/billing.py`, `app/services/subscription_service.py`, `app/services/approval_service.py`
5. 일일 보고 파이프라인(JSON + PDF)  
   근거: `app/services/report_service.py`, `app/routers/reports.py`, `app/templates/pages/daily_reports.html`

### 2.2 남은 고가치 개선 지점

1. changelog/status/legal 신뢰 내러티브를 지속 발행하는 운영 체계가 더 필요합니다.
2. 공개 status는 현재 수동 콘텐츠 중심이며, 외부 incident 신호와 자동 연동은 미구현입니다.
3. ROI 예측 위젯 및 trust timeline은 로드맵 단계에 머물러 있습니다.

## 3) 정밀 업그레이드 전략

### 트랙 A: 고객 신뢰 UX

1. 모든 영향 주장에 `measured` 또는 `predicted` 라벨을 고정합니다.
2. KPI 카드에 표본 수와 신뢰도를 함께 노출합니다.
3. footer 기반 법무/지원/연락 경로를 항상 접근 가능하게 유지합니다.

### 트랙 B: 증거 운영

1. proof snapshot을 매뉴얼/리포트의 핵심 신뢰 아티팩트로 격상합니다.
2. 최적화 액션의 전후(before/after) 비교를 기본 흐름에 포함합니다.
3. 일일 리포트 내러티브를 proof 델타와 confidence 메타데이터에 정렬합니다.

### 트랙 C: 운영 투명성

1. changelog/status를 고객 공개 운영 페이지로 상시 유지합니다.
2. 릴리스 변경점과 KPI 변화를 연결해 설명합니다.
3. privacy/terms/legal 접근성을 전체 제품 화면에서 보장합니다.

## 4) 혁신 기능 후보

1. Billing/Proof 문맥의 ROI Forecaster 위젯 (`predicted` 전용 + 계산식 공개)
2. Action 적용 -> Proof 변화 -> Report 발행 흐름의 Trust Timeline 컴포넌트
3. confidence 기반 메시징 게이트(저/중/고)
4. pre/post proof snapshot 기반 자동 보상 평가 스케줄러
5. 고객 공개 changelog용 변화 인텔리전스 피드(기능/수정/위험)
6. status 페이지 incident 커뮤니케이션 패널

## 5) 구현 가능성 검토

### 5.1 즉시 구현 가능 (스키마 변경 없음)

1. footer 상세 페이지 및 탐색 보드
2. 템플릿의 confidence 라벨 표준화
3. changelog/status/help/legal 콘텐츠 페이지
4. 고객 보고용 실행 보드 페이지

### 5.2 중간 난이도로 구현 완료 (서비스 로직 업데이트)

1. baseline-delta 기반 보상 계산  
   핵심 파일: `app/services/optimization_service.py`
2. 액션-지표 델타 연결 내러티브 생성  
   핵심 파일: `app/services/report_service.py`, `app/templates/pages/proof.html`, `app/templates/pages/daily_reports.html`

### 5.3 신규 데이터/연동 필요

1. 외부 incident feed 연동
2. CRM/티켓 동기화
3. 매출 가중치를 포함한 확장 ROI 모델

## 6) 유용성 통계 (실측 vs 예측)

중요: 아래 값은 증거 유형별로 분리하여 해석합니다.

### 6.1 실측 (현재 GhostLink 지표 모델 기반)

1. ACR, Citation Rate, AI Assist Rate는 기존 run/event 테이블에서 직접 계산됩니다.  
   증거 소스: `app/services/proof_service.py`
2. confidence는 표본 크기 임계치(`low`, `medium`, `high`)로 이미 산출됩니다.  
   증거 소스: `app/services/proof_service.py`
3. 사이트 수, AI crawler 방문, bridge 이벤트, 승인 건수는 일일 단위로 집계 가능합니다.  
   증거 소스: `app/services/report_service.py`

### 6.2 예측 범위 (기획 가정)

1. 첫 증명 도달 시간: 최대 94% 단축 (3일 -> 30분)
2. 온보딩 완료율: +20% ~ +35%
3. Action-to-Lift 전환율: +15% ~ +28%
4. 경영 보고 처리속도: 4배 ~ 6배

## 7) 개발 준비 체크리스트

1. Proof KPI 엔진 및 confidence 로직: `READY`
2. Onboarding/manual/daily report UX 흐름: `READY`
3. Billing + approval 거버넌스: `READY`
4. 최적화 보상 델타 로직: `READY`
5. 공개 status/changelog 운영: `READY`

## 8) 실행 계획 (권장)

### Phase 1 (0.5~1.5일)

1. Footer 전 메뉴 실경로 연결
2. 실측/예측 카드 포함 실행 보드 구축
3. 매뉴얼 링크 동선과 라우트 QA

### Phase 2 (1.5~3일)

1. optimization 서비스의 baseline 비교 보상 로직
2. dashboard/proof/report confidence 배지
3. changelog/status 운영 콘텐츠 루프

### Phase 3 (3~5일)

1. ROI forecaster 프로토타입
2. action-KPI 델타 trust timeline
3. 일일 리포트 내러티브 자동화 강화

## 9) 인수 기준

1. footer 메뉴 모든 항목이 개별 라우트로 열린다.
2. trust 관련 페이지(privacy/terms/legal/contact/status/changelog)에 즉시 접근 가능하다.
3. manual에서 execution board로 이동 가능하다.
4. 통계가 실측/예측으로 명확히 분리된다.
5. footer 라우트 및 렌더링을 검증하는 자동 테스트가 최소 1개 이상 존재한다.

## 10) 인수인계 메모

현재 코드베이스는 지표 계산 엔진과 거버넌스 토대가 이미 강합니다. 
가장 빠른 레버리지는 대규모 스키마 변경보다 고객 신뢰 표면, 운영 투명성, 측정 내러티브 품질을 강화하는 작업입니다.
