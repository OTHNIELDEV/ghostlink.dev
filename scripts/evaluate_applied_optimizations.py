#!/usr/bin/env python3
"""
Evaluate applied optimization actions using baseline/post proof snapshots.

Run all organizations:
    python3 scripts/evaluate_applied_optimizations.py

Run a specific organization:
    python3 scripts/evaluate_applied_optimizations.py --org-id 1

Dry run (no reward writes):
    python3 scripts/evaluate_applied_optimizations.py --dry-run
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlmodel import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.engine import get_session
from app.models.organization import Organization
from app.services.optimization_service import optimization_service


async def _list_target_org_ids(org_id: int | None) -> list[int]:
    async for session in get_session():
        if org_id is not None:
            row = await session.get(Organization, org_id)
            return [org_id] if row else []
        rows = (await session.exec(select(Organization.id).order_by(Organization.id.asc()))).all()
        return [int(row) for row in rows if row is not None]
    return []


async def _run(org_id: int | None, dry_run: bool) -> dict:
    target_org_ids = await _list_target_org_ids(org_id)
    summary = {
        "dry_run": dry_run,
        "target_org_count": len(target_org_ids),
        "organizations": [],
        "evaluated_total": 0,
    }
    if not target_org_ids:
        return summary

    async for session in get_session():
        for target_org_id in target_org_ids:
            evaluated_count = 0
            if not dry_run:
                evaluated_count = await optimization_service.evaluate_applied_actions(
                    session=session,
                    org_id=target_org_id,
                )
            summary["organizations"].append(
                {
                    "org_id": target_org_id,
                    "evaluated_count": evaluated_count,
                }
            )
            summary["evaluated_total"] += evaluated_count
        break
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate applied optimization actions with baseline/post proof deltas."
    )
    parser.add_argument("--org-id", type=int, default=None, help="Evaluate only one organization")
    parser.add_argument("--dry-run", action="store_true", help="List targets without recording rewards")
    args = parser.parse_args()

    summary = asyncio.run(_run(org_id=args.org_id, dry_run=args.dry_run))
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
