# GhostLink 고객 사용 명확화 + AI 검색 효율 증명 혁신 제안서

작성일: 2026-02-08  
대상: Product / Design / Engineering / GTM

## 1. 문제 정의 (고객 관점)

현재 고객이 느끼는 핵심 문제는 아래 두 가지입니다.

1. 어떻게 써야 하는지 명확하지 않다.  
2. 써서 실제로 얼마나 좋아졌는지 증명되지 않는다.

이 문제는 기능 부족보다 `가치 전달 구조 부족`에서 발생합니다.

## 2. 현재 상태 진단 (코드 기준)

현재 구현에는 강력한 기능이 이미 존재합니다. 그러나 고객 체감까지 연결이 약합니다.

1. 대시보드에서 점수/트래픽은 보이지만, 시작 가이드가 없다.  
근거: `app/templates/pages/dashboard.html`

2. 대시보드 백엔드에는 `traffic_visibility_score`가 계산되지만 핵심 카드에 노출되지 않는다.  
근거: `app/routers/pages.py`

3. 리포트의 `ghostlink_impact` 개선치(`+35%`, `+28%` 등)는 실제 측정값이 아니라 생성/기본값에 의존할 수 있다.  
근거: `app/services/core_engine.py`

4. “효율 증명”의 핵심인 Answer Capture/Attribution API는 구현되어 있으나 UI 퍼널에 연결되지 않았다.  
근거: `app/routers/answer_capture.py`, `app/routers/attribution.py`, `docs/PHASE3_TOP2_EXECUTION_PLAN.md`

5. Auto-Optimize v1/v2는 리포트 페이지 하단 고급 기능으로 존재해, 초보 고객이 가치를 발견하기 어렵다.  
근거: `app/templates/pages/report.html`

## 3. 목표 재정의

GhostLink를 “AI SEO 생성 도구”에서 “AI 검색 성과 증명 엔진”으로 재정의합니다.

90일 목표:

1. 신규 고객의 첫 가치 인지 시간(첫 증명 도달 시간)을 3일 -> 30분 이내로 단축
2. “효율이 좋은지 모르겠다” 불만 비율 50% 이상 감소
3. Free->Paid 전환에 직접 연결되는 증명 지표(ACR/Citation/AI Assist) 대시보드 도입

## 4. 혁신 제안 아키텍처 (4개 트랙)

## 트랙 A. 가이드형 활성화 운영체계 (사용법 명확화)

핵심 아이디어: 고객이 생각하지 않아도 “다음 행동”이 보이는 운영체제형 온보딩.

구성:

1. 대시보드 상단 `시작하기` 패널 도입  
항목: `사이트 등록 -> 스캔 완료 -> 브릿지 설치 확인 -> 질문세트 선택 -> 첫 증명 실행`

2. 진행 상태를 퍼센트가 아닌 행동 단위로 표시  
예: `2/5 완료 (다음: 브릿지 설치 확인)`

3. 조직별 온보딩 상태 저장  
초기 14일 동안 모든 페이지에 다음 행동 CTA를 고정 노출

구현 제안:

1. 신규 테이블: `onboarding_progress`  
컬럼: `org_id`, `step_key`, `status`, `completed_at`, `owner_user_id`

2. 신규 API:
- `GET /api/v1/onboarding/status?org_id=...`
- `POST /api/v1/onboarding/complete-step?org_id=...`

3. UI 변경:
- `dashboard.html` 상단에 온보딩 레일 추가
- `report.html`에 단계 기반 CTA 삽입

성공 지표:

1. 활성화율: 가입 후 24시간 내 3단계 완료 비율
2. 첫 스캔 완료율
3. 첫 증명 도달 시간

## 트랙 B. 효율 증명 엔진 (Proof of Efficiency)

핵심 아이디어: “좋아 보이는 점수”가 아니라 “실제 질의 결과와 전환 기여”를 증명합니다.

고객이 보는 화면:

1. 프루프 센터 (신규 탭/페이지)  
카드: `Answer Capture Rate`, `Citation Rate`, `AI Assist Rate`, `전주 대비 변화`

2. 전후 비교 증거 카드  
항목: `질의`, `개선 전 답변`, `개선 후 답변`, `브랜드 언급 여부`, `우리 도메인 인용 여부`

3. 신뢰도 배지  
항목: 표본 수, 측정 기간, 유효 질의 수를 함께 표시

구현 제안:

1. 기존 Answer Capture + Attribution을 UI에 통합  
활용 API: `app/routers/answer_capture.py`, `app/routers/attribution.py`

2. 신규 집계 엔드포인트:
- `GET /api/v1/proof/overview?org_id=...&period_days=30`
- `GET /api/v1/proof/before-after?org_id=...&query_set_id=...`

3. 신규 스냅샷 테이블: `proof_snapshot`  
컬럼:
- `org_id`
- `period_start`, `period_end`
- `answer_capture_rate_pct`
- `citation_rate_pct`
- `ai_assist_rate_pct`
- `sample_size`
- `confidence_level`
- `metadata_json`

핵심 지표 정의:

1. ACR(Answer Capture Rate)  
`브랜드 언급된 답변 수 / 총 평가 답변 수`

2. Citation Rate  
`자사 도메인 인용 답변 수 / 총 평가 답변 수`

3. AI Assist Rate  
`AI 세션이 포함된 전환 세션 / 총 전환 세션`

4. 증명 신뢰도  
표본수 기반 배지 (`low`, `medium`, `high`)

## 트랙 C. 실험 자동화 루프 고도화 (체감 혁신)

핵심 아이디어: 추천을 읽는 제품이 아니라, 실험-적용-학습을 자동으로 반복하는 제품.

구성:

1. 액션 팩 생성 시 “예상 KPI 영향” 선표시  
예: `예상 ACR +4.2%`, `예상 Citation +2.1%`

2. 적용 후 자동 측정 예약  
액션 승인 시 24시간/72시간 후 자동 재평가 작업 예약

3. Bandit 피드백 자동 수집  
수동 `+1.0/+0.0` 버튼 외에 실제 지표 변화를 reward로 반영

구현 제안:

1. `optimization_action`에 필드 추가:
- `predicted_acr_lift`
- `predicted_citation_lift`
- `evaluation_due_at`
- `auto_reward_json`

2. 스케줄러 잡:
- `evaluate_action_outcome_job`
- `update_bandit_reward_job`

3. 리포트 UI 재구성:
- 기존 Auto-Optimize 섹션을 상단 배치
- “다음 최적 액션 1개”를 기본 강조

성공 지표:

1. 액션 승인율
2. 액션-개선 전환율 (`승인된 액션 중 실제 지표 개선 비율`)
3. 반복 사용률 (`주당 2회 이상 실험 실행 조직 비율`)

## 트랙 D. ROI 내러티브 계층 (구매 설득 강화)

핵심 아이디어: 기술 지표를 매출/리드 지표로 번역하여 의사결정자 설득력을 높입니다.

구성:

1. 월간 Executive Brief 자동 생성  
내용: `AI 검색 존재감`, `전환 기여`, `다음 투자 우선순위`

2. 팀별 뷰 제공  
`마케팅`: 질의 점유율/인용률  
`제품`: 개선 과제/실험결과  
`리더십`: AI 기여 전환 및 추세

3. 외부 공유 링크(PDF/URL)  
영업·리포팅 활용 가능

구현 제안:

1. `GET /api/v1/proof/executive-summary?org_id=...&period_days=30`
2. `pages/proof.html` + `pages/executive_report.html`
3. 스냅샷 캐시 저장으로 렌더 비용 절감

## 5. 제품 경험 시나리오 (신규 고객 기준)

0~1일차:

1. URL 입력 후 즉시 스캔 시작
2. `시작하기` 패널에서 다음 액션 제시
3. 브릿지 설치 성공 여부 자동 확인
4. 질의셋 1개 선택 후 Answer Capture 1회 실행

2~7일차:

1. 첫 전후 비교 카드 확인
2. 자동 추천 액션 1개 승인
3. 72시간 후 변화 측정 카드 표시

8~30일차:

1. 주간 자동 증명 리포트 전달
2. AI Assist Rate와 전환 지표 연결
3. 유료 전환 트리거: “지난 30일 증명 리포트 기반”

## 6. 화면 단위 개선안

대시보드:

1. 상단 고정 `시작하기` + `지금 증명` 듀얼 CTA
2. 가시성 점수 단일 수치에서 `구성요소(콘텐츠/크롤러/답변점유)`로 분해
3. `traffic_visibility_score` 카드 노출 및 설명 툴팁 추가

리포트:

1. 첫 섹션을 `증명 결과`로 재배치 (현재는 분석 중심)
2. Auto-Optimize를 하단 부가 기능에서 핵심 경로로 승격
3. 기술 문구를 행동 문구로 전환  
예: `액션 생성` -> `다음 72시간 성과 개선 실행`

신규 프루프 센터:

1. 질의별 증거 테이블
2. 전후 비교 카드
3. 신뢰도/표본수 표시
4. 다운로드 및 공유 기능

## 7. 데이터 신뢰성 강화 (필수)

고객 신뢰를 위해 “추정”과 “실측”을 분리해 표기해야 합니다.

원칙:

1. 생성형 문구 기반 개선치(`+35%`)는 `예측` 라벨을 부착
2. Answer Capture/Attribution 기반 값만 `실측` 라벨 사용
3. 지표 카드에 항상 `측정 기간`, `표본 수`, `마지막 업데이트` 노출

기술 작업:

1. `analysis.ghostlink_impact` 표시에 `predicted/measured` 타입 추가
2. 백엔드 응답 스키마에 `evidence_type` 필드 도입
3. UI 라벨 색상으로 구분

## 8. 8주 실행 로드맵

1~2주차 (기반 연결):

1. 온보딩 상태 모델 + API 구현
2. 대시보드 `시작하기` 레일 구현
3. `traffic_visibility_score` UI 노출

3~4주차 (증명 MVP):

1. 프루프 센터 페이지 생성
2. Answer Capture/Attribution 집계 API 통합
3. 전후 비교 카드 MVP

5~6주차 (자동화):

1. 액션 적용 후 자동 평가 잡 구현
2. Bandit reward 자동 반영
3. 예측/실측 분리 라벨 적용

7~8주차 (상용화):

1. Executive Brief 생성
2. 공유 링크/내보내기
3. 전환 실험(Free->Paid) 롤아웃

## 9. 실험 설계 (전환 개선)

A/B 실험 1:

1. A군: 기존 대시보드
2. B군: `시작하기` + `증명` CTA

성공 기준:

1. 7일 내 첫 증명 실행률 +25%
2. 14일 내 재방문율 +15%

A/B 실험 2:

1. A군: 기존 리포트
2. B군: 증명 카드 우선 리포트

성공 기준:

1. Action 승인율 +20%
2. Paid 전환율 +10%

## 10. 즉시 실행 백로그 (엔지니어링 티켓화 가능)

P0:

1. 대시보드에 `시작하기` 컴포넌트 추가
2. `traffic_visibility_score` 카드 렌더링
3. `ghostlink_impact` 라벨링(`predicted`)

P1:

1. 프루프 센터 라우트/템플릿/집계 API
2. Answer Capture 실행 위저드
3. Attribution snapshot 시각화

P2:

1. 자동 평가 배치
2. Executive Brief 생성
3. 공유/내보내기 기능

## 11. 기대 효과

제품 관점:

1. “어떻게 써야 하는지” 혼란 감소
2. “효율이 좋은지 모르겠다” 불신 감소
3. 추천-실행-증명 루프 완성

비즈니스 관점:

1. Free 사용자 활성화 상승
2. Paid 전환율 상승
3. Enterprise 세일즈에서 증거 기반 설득 가능

## 12. 결론

GhostLink의 핵심 과제는 기능 추가가 아니라 `가치 증명 UX의 제품화`입니다.  
이미 구현된 엔진(Answer Capture, Attribution, Auto-Optimize)을 고객 여정의 앞단에 재배치하면, 단기간에 체감 품질과 전환을 동시에 개선할 수 있습니다.
