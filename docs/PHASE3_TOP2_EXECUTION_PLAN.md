# Phase 3 핵심 2개 실행 계획 (Answer Capture + AI Attribution)

업데이트: 2026-02-07

## 1) 우선순위 결정
- 우선순위 1: **Answer Capture Lab**
  - 이유: 제품 가치를 가장 직접적으로 증명 가능(답변 점유율/인용률)
- 우선순위 2: **AI 트래픽 품질 기여도(Attribution)**
  - 이유: 매출/전환 관점 ROI 근거를 제공해 유료 전환 설득력을 강화

## 2) 범위 (v1)

### 2.1 Answer Capture Lab v1
- 질문 세트 생성/관리
- 질문 항목 생성/관리
- 실행(run) 결과 수집(외부 평가 결과 ingest)
- 지표 계산:
  - 브랜드 언급률(Brand Mention Rate)
  - 인용률(Citation Rate)
  - 평균 품질 점수(Average Quality Score)

### 2.2 AI Attribution v1
- 세션 이벤트 수집
- 기간별 스냅샷 계산:
  - 전체 전환수(Conversions Total)
  - AI 보조 전환수(AI Assisted Conversions)
  - AI 기여 전환율(AI Assist Rate)
- 스냅샷 저장/조회

## 3) 데이터 모델 (구현됨)

### 3.1 Answer Capture 테이블
- `AnswerCaptureQuerySet`
  - `org_id`, `name`, `description`, `default_brand_terms_json`, `is_active`
- `AnswerCaptureQueryItem`
  - `query_set_id`, `prompt_text`, `expected_brand_terms_json`, `priority`, `is_active`
- `AnswerCaptureRun`
  - `org_id`, `query_set_id`, `status`, `provider`, `model`, `summary_json`
- `AnswerCaptureResult`
  - `run_id`, `query_item_id`, `answer_text`, `cited_urls_json`
  - `has_brand_mention`, `has_site_citation`, `quality_score`

### 3.2 Attribution 테이블
- `AttributionEvent`
  - `org_id`, `site_id`, `session_key`, `source_type`, `source_bot_name`
  - `utm_*`, `event_name`, `event_value`, `event_timestamp`, `metadata_json`
- `AttributionSnapshot`
  - `org_id`, `period_start`, `period_end`
  - `conversions_total`, `ai_assisted_conversions`, `ai_assist_rate_pct`, `metadata_json`

## 4) API 계약 (구현됨)

기본 prefix: `/api/v1`

### 4.1 Answer Capture API
- `GET /answer-capture/query-sets?org_id=<id>`
- `POST /answer-capture/query-sets?org_id=<id>` (owner/admin)
- `GET /answer-capture/query-sets/{query_set_id}/queries?org_id=<id>`
- `POST /answer-capture/query-sets/{query_set_id}/queries?org_id=<id>` (owner/admin)
- `POST /answer-capture/runs?org_id=<id>`
- `GET /answer-capture/runs?org_id=<id>&query_set_id=<optional>`
- `GET /answer-capture/runs/{run_id}?org_id=<id>`

### 4.2 Attribution API
- `POST /attribution/events?org_id=<id>`
- `GET /attribution/snapshot?org_id=<id>&period_days=30`
- `POST /attribution/snapshot?org_id=<id>&period_days=30` (owner/admin, 저장)
- `GET /attribution/snapshots?org_id=<id>`

## 5) RBAC 규칙
- 조직 멤버:
  - query-set/list, run 생성/조회, attribution event 기록, snapshot 조회
- Owner/Admin:
  - query-set 생성, query-item 생성, attribution snapshot 저장

## 6) 감사 로그 이벤트 (구현됨)
- `answer_capture.query_set_created`
- `answer_capture.query_item_created`
- `answer_capture.run_created`
- `attribution.event_recorded`
- `attribution.snapshot_saved`

## 7) 인수 기준 (v1)
- 질문 세트 1개 + 질문 1개를 생성하고 run 결과를 수집하면 summary 지표가 반환된다.
- attribution event 1개 이상 기록 후 snapshot 조회 시 conversion 집계가 계산된다.
- 동일 org 내 권한 없는 사용자의 owner/admin 전용 작업은 403이 반환된다.

## 8) 다음 빌드 단계 (v1.1~v1.3)
- v1.1: 자동 LLM 평가 실행 worker (provider별 adapter)
- v1.2: 대시보드 카드(ACR/Citation/AI Assist Rate) UI 연결
- v1.3: 실험 정책 엔진(밴딧)과 run 결과 피드백 루프 연결

## 9) 미결정 항목
- Conversion 표준 이벤트 세트 확정 (`trial_started`, `purchase_completed` 등)
- ACR 계산 시 브랜드 동의어/오탈자 허용 정책
- Citation 판단 시 도메인 매칭 규칙(subdomain 포함 여부)
