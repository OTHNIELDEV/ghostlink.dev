#!/usr/bin/env python3
"""
Process pending bridge raw events with retry/backoff policy.

Examples:
    python3 scripts/process_bridge_raw_events.py
    python3 scripts/process_bridge_raw_events.py --site-id 3
    python3 scripts/process_bridge_raw_events.py --site-id 3 --limit 500 --rounds 2
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlmodel import and_, or_, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.engine import get_session
from app.models.analytics import BridgeEventRaw
from app.routers.bridge import BRIDGE_RAW_WORKER_BATCH_SIZE, process_bridge_raw_queue_background


async def _list_pending_site_ids(site_id: int | None) -> list[int]:
    if site_id is not None:
        return [site_id]

    now_utc = datetime.utcnow()
    async for session in get_session():
        rows = (
            await session.exec(
                select(BridgeEventRaw.site_id)
                .where(
                    and_(
                        BridgeEventRaw.normalized == False,  # noqa: E712
                        BridgeEventRaw.dropped_reason.is_(None),
                        or_(
                            BridgeEventRaw.next_retry_at.is_(None),
                            BridgeEventRaw.next_retry_at <= now_utc,
                        ),
                    )
                )
                .distinct()
                .order_by(BridgeEventRaw.site_id.asc())
            )
        ).all()
        return [int(row) for row in rows if row is not None]
    return []


async def _run(site_id: int | None, limit: int, rounds: int) -> dict:
    summary = {
        "site_id": site_id,
        "limit": limit,
        "rounds": rounds,
        "processed_total": 0,
        "normalized_total": 0,
        "dropped_total": 0,
        "retried_total": 0,
        "runs": [],
    }

    for idx in range(rounds):
        site_ids = await _list_pending_site_ids(site_id)
        if not site_ids:
            summary["runs"].append(
                {
                    "round": idx + 1,
                    "site_ids": [],
                    "processed": 0,
                    "normalized": 0,
                    "dropped": 0,
                    "retried": 0,
                }
            )
            continue

        round_processed = 0
        round_normalized = 0
        round_dropped = 0
        round_retried = 0

        for target_site_id in site_ids:
            result = await process_bridge_raw_queue_background(target_site_id, limit=limit)
            round_processed += int(result.get("processed", 0))
            round_normalized += int(result.get("normalized", 0))
            round_dropped += int(result.get("dropped", 0))
            round_retried += int(result.get("retried", 0))

        summary["processed_total"] += round_processed
        summary["normalized_total"] += round_normalized
        summary["dropped_total"] += round_dropped
        summary["retried_total"] += round_retried
        summary["runs"].append(
            {
                "round": idx + 1,
                "site_ids": site_ids,
                "processed": round_processed,
                "normalized": round_normalized,
                "dropped": round_dropped,
                "retried": round_retried,
            }
        )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Process bridge raw event queue and retries.")
    parser.add_argument("--site-id", type=int, default=None, help="Process only one site id")
    parser.add_argument(
        "--limit",
        type=int,
        default=BRIDGE_RAW_WORKER_BATCH_SIZE,
        help="Max pending rows to process per site for each round",
    )
    parser.add_argument("--rounds", type=int, default=1, help="Number of worker rounds to run")
    args = parser.parse_args()

    summary = asyncio.run(
        _run(
            site_id=args.site_id,
            limit=max(1, args.limit),
            rounds=max(1, args.rounds),
        )
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
