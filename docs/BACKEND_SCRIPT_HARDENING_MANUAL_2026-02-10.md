# GhostLink 백엔드 스크립트 고도화 매뉴얼

작성일: 2026-02-10  
대상: Backend / Platform / DevOps

## 0) 결론

백엔드 스크립트 고도화는 **가능**합니다.  
현재 저장소 기준으로는 아래 3개 스크립트를 우선 고도화하면 효과가 큽니다.

1. `scripts/evaluate_applied_optimizations.py`
2. `scripts/init_test_data.py`
3. `scripts/smoke_billing_security.py`

---

## 1) 고도화 목표

고도화 목적은 “실행된다” 수준이 아니라 “운영에서 신뢰 가능하다” 수준으로 끌어올리는 것입니다.

1. 안전성: 잘못된 실행으로 운영 데이터가 손상되지 않음
2. 신뢰성: 실패 시 재시도/복구가 가능하고 결과 일관성 유지
3. 관측성: 누가/언제/무엇을/얼마나 처리했는지 추적 가능
4. 운영성: CI/스케줄러/배치에서 자동 실행 가능
5. 확장성: 대상 조직/사이트 증가 시에도 성능 저하를 통제 가능

---

## 2) 공통 설계 원칙

### 2.1 CLI 표준 옵션 통일

모든 스크립트에 공통적으로 아래 옵션을 제공합니다.

1. `--dry-run`: 쓰기 작업 없이 대상/영향만 계산
2. `--org-id <id>` 또는 `--org-ids <id1,id2>`
3. `--limit <n>`: 처리 건수 상한
4. `--fail-fast`: 첫 실패 시 즉시 종료
5. `--json-output <path>`: 실행 요약 JSON 파일 저장
6. `--verbose`: 상세 로그 출력
7. `--timeout-sec <n>`: 작업 타임아웃

### 2.2 종료 코드 표준화

1. `0`: 전체 성공
2. `1`: 치명적 실패(전체 실패)
3. `2`: 부분 실패(일부 성공, 일부 실패)
4. `3`: 검증 실패(입력값/환경 문제)

### 2.3 실행 요약(JSON) 표준 스키마

```json
{
  "script": "evaluate_applied_optimizations",
  "run_id": "20260210T143001Z-8f1c",
  "started_at": "2026-02-10T14:30:01Z",
  "ended_at": "2026-02-10T14:30:09Z",
  "duration_ms": 8123,
  "dry_run": false,
  "targets_total": 12,
  "processed_total": 12,
  "succeeded_total": 11,
  "failed_total": 1,
  "warnings": [],
  "errors": [
    {"target": "org:31", "reason": "DB timeout"}
  ]
}
```

### 2.4 멱등성(idempotency)과 잠금

1. 같은 입력으로 재실행해도 결과가 중복 반영되지 않게 설계
2. 배치 스크립트는 실행 잠금(락) 적용
3. 락 키 예시: `script:<name>:<scope>:<yyyy-mm-dd-hh>`
4. 락 획득 실패 시 중복 실행으로 판단하고 종료 코드 `2` 또는 `3` 반환

### 2.5 트랜잭션 경계

1. 전체 일괄 커밋보다 “대상 단위 커밋” 권장
2. 한 대상 실패가 전체 롤백으로 번지지 않게 분리
3. 실패 대상은 요약 리포트에 수집하고 다음 대상으로 진행

### 2.6 로그 규약

1. `print` 대신 구조화 로그(JSON line) 우선
2. 필수 필드: `run_id`, `script`, `target`, `event`, `status`, `elapsed_ms`
3. 운영 로그와 개발 로그를 분리(`INFO`/`DEBUG`)

---

## 3) 스크립트별 고도화 방법

## 3.1 `evaluate_applied_optimizations.py`

현재 역할: 적용된 최적화 액션의 baseline/post proof 델타를 평가  
핵심 연동: `app.services.optimization_service.evaluate_applied_actions`

고도화 항목:

1. `dry-run` 시 단순 대상 나열이 아니라 “예상 평가 건수”까지 계산
2. `--limit`, `--org-ids`, `--fail-fast`, `--json-output` 옵션 추가
3. 조직 단위 실패 격리(한 org 실패해도 나머지 진행)
4. 실행별 `run_id` 생성 및 감사 로그 연계
5. 부분 실패 시 종료코드 `2` 반환
6. 장기적으로 락(중복 실행 방지) 추가

수용 기준(DoD):

1. 같은 org를 연속 실행해도 보상이 중복 증가하지 않음
2. 100개 org 배치에서 일부 실패 시 나머지 org 처리 지속
3. 실행 결과 JSON 파일로 성공/실패 대상 확인 가능

## 3.2 `init_test_data.py`

현재 역할: 테스트 사용자/조직/사이트/구독 생성

고도화 항목:

1. 하드코딩 값 제거:
   `--email`, `--password`, `--org-slug`, `--site-url`
2. `--profile` 도입:
   `minimal`, `proof-ready`, `billing-ready`
3. `--cleanup` 모드 추가:
   prefix 기반 테스트 데이터 정리
4. CI 호환 출력:
   이모지 로그 대신 일반 텍스트 + JSON summary
5. UTC 시간 처리 통일:
   `datetime.utcnow()` 대신 timezone-aware UTC 사용

수용 기준(DoD):

1. 동일 파라미터로 재실행 시 중복 데이터 폭증 없음
2. `--cleanup`으로 생성 데이터 재정리 가능
3. CI에서 결과 파싱 가능(JSON summary)

## 3.3 `smoke_billing_security.py`

현재 역할: 결제/라우팅/권한 관련 스모크 검증

고도화 항목:

1. 테스트 케이스를 함수 단위로 분리(가독성/재사용성)
2. `--json-output`, `--junit-output` 옵션 추가
3. 실패 케이스에 상세 진단 포함(요청 경로/응답 코드/기대값)
4. `--keep-test-data` 옵션으로 디버깅 시 데이터 유지
5. CI 게이트 기준 추가:
   필수 케이스 실패 시 배포 차단

수용 기준(DoD):

1. 실패한 케이스를 파일 한 개로 즉시 식별 가능
2. CI에서 JUnit 아티팩트로 리포트 시각화 가능
3. 정리(cleanup) 실패 시에도 원인 출력 후 종료 코드 명확

---

## 4) 표준 스크립트 템플릿 (권장)

```python
#!/usr/bin/env python3
import argparse
import json
import time
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-output", type=str, default=None)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    started = time.time()
    summary = {
        "started_at": utc_now_iso(),
        "dry_run": args.dry_run,
        "processed_total": 0,
        "succeeded_total": 0,
        "failed_total": 0,
        "errors": [],
    }

    # TODO: 대상 조회 -> 대상 단위 처리 -> 예외 격리

    ended = time.time()
    summary["ended_at"] = utc_now_iso()
    summary["duration_ms"] = int((ended - started) * 1000)

    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as f:
            f.write(payload)
    print(payload)

    if summary["failed_total"] == 0:
        return 0
    return 2 if summary["succeeded_total"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## 5) 운영 자동화 방법

### 5.1 1단계: 수동 실행 안정화

1. 모든 스크립트에 공통 옵션/종료코드/JSON 요약 적용
2. dry-run과 실실행 결과 차이를 검증
3. 실패 격리/재실행 시나리오 점검

### 5.2 2단계: CI 통합

1. PR 파이프라인:
   `smoke_billing_security.py` 필수 실행
2. 야간 배치:
   `evaluate_applied_optimizations.py --json-output ...`
3. 아티팩트 업로드:
   JSON/JUnit 보고서 저장

### 5.3 3단계: 스케줄러/운영 연계

1. 운영 스케줄러(cron or workflow)에서 정시 실행
2. 실행 실패율 임계치 초과 시 알림(Slack/이메일)
3. 중복 실행 방지를 위한 락 도입

---

## 6) 보안/거버넌스 체크리스트

1. 운영 환경에서 `--dry-run` 기본값 정책 검토
2. 관리자 권한이 필요한 작업은 실행 계정 제한
3. 민감정보(키/토큰/비밀번호)는 로그 마스킹
4. 스크립트 실행 이력(run_id, 사용자, 시각) 보관
5. 데이터 변경 스크립트는 사전 백업 절차 포함

---

## 7) 우선순위 제안 (이번 저장소 기준)

P0 (즉시):

1. `evaluate_applied_optimizations.py`에 JSON 요약, 부분 실패 코드, 옵션 확장
2. `smoke_billing_security.py`에 JSON/JUnit 출력
3. `init_test_data.py` 파라미터화 + cleanup 모드

P1 (다음):

1. 실행 락 도입
2. 스크립트 공통 유틸 모듈(`scripts/_common.py`) 분리
3. timezone-aware UTC 전환

P2 (확장):

1. Script run 메타데이터 DB 저장
2. 운영 대시보드에서 스크립트 실행 성공률 시각화
3. 자동 복구(retry with backoff) 정책 고도화

---

## 8) 바로 개발 시작용 작업 목록

1. `scripts/_common.py` 생성:
   run_id, summary, exit code, json output 유틸 추가
2. 3개 스크립트에서 공통 유틸 사용하도록 리팩터링
3. 실패 격리 로직 통일(`try/except per target`)
4. 테스트 추가:
   옵션 파싱, 종료코드, 요약 JSON 구조
5. CI 파이프라인에 스크립트 실행 단계 추가

---

## 9) 브릿지 Raw 이벤트 재처리 워커 운영 매뉴얼 (신규)

적용 코드 기준:

1. 큐 워커: `app/routers/bridge.py`
2. DB 컬럼 보정: `app/db/engine.py`
3. 수동 재처리 스크립트: `scripts/process_bridge_raw_events.py`

### 9.1 목적

브릿지 수집 경로를 아래처럼 분리해 안정성을 높입니다.

1. 인제스트 경로: Raw 이벤트만 저장
2. 워커 경로: Raw -> 정규화(`BridgeEvent`) 처리
3. 실패 정책: 재시도(backoff) 후 한계 초과 시 `retry_exhausted` 드롭

### 9.2 처리 상태 필드

`bridgeeventraw`(모델: `BridgeEventRaw`)는 아래 필드로 재처리 상태를 관리합니다.

1. `retry_count`: 누적 재시도 횟수
2. `next_retry_at`: 다음 재시도 가능 시각(UTC)
3. `last_error`: 마지막 오류 메시지
4. `normalized`: 정규화 완료 여부
5. `dropped_reason`: 드롭 사유(`duplicate_event_id`, `invalid_payload_json`, `retry_exhausted`)

### 9.3 재시도 정책(기본)

현재 기본 정책:

1. 최대 재시도: 3회
2. 백오프: 15s, 30s, 60s(상한 300s)
3. 최대치 도달 시:
   `normalized=true`, `dropped_reason="retry_exhausted"`

### 9.4 운영 명령어

전체 pending 사이트 처리:

```bash
python3 scripts/process_bridge_raw_events.py
```

특정 사이트만 처리:

```bash
python3 scripts/process_bridge_raw_events.py --site-id 3
```

라운드/처리량 지정:

```bash
python3 scripts/process_bridge_raw_events.py --site-id 3 --limit 500 --rounds 2
```

### 9.5 운영 점검 포인트

1. `retried_total`가 지속 증가하고 `normalized_total`이 늘지 않으면 payload 스키마/파싱 코드 점검
2. `dropped_total` 증가 시 `dropped_reason` 분포를 우선 확인
3. 같은 `event_id`가 반복 드롭되면 클라이언트 이벤트 ID 생성 로직 중복 여부 점검
4. 토큰 만료/오리진 실패가 많은 경우 `/bridge/{script_id}/token` 흐름과 CORS/Referer 정책 점검

### 9.6 배포 체크리스트

1. 앱 시작 시 `init_db()`에서 `bridgeeventraw` 신규 컬럼 자동 보정 확인
2. 브릿지 배치 이벤트 API(`/api/bridge/{script_id}/events`) 정상 수신 확인
3. 통합 가이드 KPI에서 7일 raw 총량/드롭/수집성공률 변동 확인
4. 필요 시 스케줄러(cron/workflow)에서 `scripts/process_bridge_raw_events.py` 주기 실행

### 9.7 자동 실행(워크플로) 설정

레포에 기본 워크플로가 추가되어 있습니다.

1. 파일: `.github/workflows/bridge-raw-worker.yml`
2. 스케줄: 30분 주기(`*/30 * * * *`)
3. 수동 실행: `workflow_dispatch`에서 `site_id`, `limit`, `rounds`, 게이트 임계치 입력 가능
4. 출력: `bridge-worker-summary.json` 아티팩트 업로드

운영 권장:

1. 실제 운영 DB에 접근 가능한 self-hosted runner로 전환
2. schedule 간격은 트래픽 기준으로 5~30분 범위에서 조정
3. `dropped_total` 또는 `retried_total` 급증 시 알림 연계

### 9.8 운영 시크릿/변수 구성

필수 GitHub Secrets:

1. `GHOSTLINK_DATABASE_URL`: 운영 DB 연결 문자열
2. `GHOSTLINK_SECRET_KEY`: 앱 서명/토큰 검증에 사용하는 시크릿

선택 GitHub Secrets:

1. `BRIDGE_WORKER_ALERT_WEBHOOK`: 실패 시 알림 전송용 webhook URL

선택 GitHub Variables(기본값 튜닝):

1. `BRIDGE_WORKER_DEFAULT_LIMIT` (기본 250)
2. `BRIDGE_WORKER_DEFAULT_ROUNDS` (기본 1)
3. `BRIDGE_WORKER_MAX_DROPPED_TOTAL` (기본 50)
4. `BRIDGE_WORKER_MAX_RETRY_RATIO_PCT` (기본 20)

### 9.9 품질 게이트 기준

워크플로는 실행 후 아래 조건을 검사합니다.

1. `dropped_total > max_dropped_total` 이면 실패
2. `retried_total / processed_total * 100 > max_retry_ratio_pct` 이면 실패

기준 초과 시:

1. Job 실패 처리
2. `bridge-worker-summary.json` 아티팩트 업로드 유지
3. `BRIDGE_WORKER_ALERT_WEBHOOK` 설정 시 실패 알림 전송
