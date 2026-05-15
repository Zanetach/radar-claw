from __future__ import annotations

import argparse
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import connect, init_db
from .models import utc_now_iso
from .web import RadarAdminHandler


DEFAULT_DB = Path("data/radar_sources.sqlite3")


def _handler(db_path: Path) -> RadarAdminHandler:
    handler = object.__new__(RadarAdminHandler)
    handler.db_path = db_path
    return handler


def delayed_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=max(0, seconds))).isoformat()


def claim_next_queued_run(conn: sqlite3.Connection, *, lock_id: str | None = None) -> dict[str, Any] | None:
    now = utc_now_iso()
    lock_id = lock_id or f"worker-{uuid.uuid4().hex[:8]}"
    row = conn.execute(
        """
        SELECT *
        FROM crawl_runs
        WHERE status = 'queued'
          AND source_type != 'batch'
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at ASC, started_at ASC
        LIMIT 1
        """,
        (now,),
    ).fetchone()
    if row is None:
        return None
    cursor = conn.execute(
        """
        UPDATE crawl_runs
        SET status = 'running',
            attempt_count = attempt_count + 1,
            locked_at = ?,
            locked_by = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'queued'
        """,
        (now, lock_id, row["id"]),
    )
    conn.commit()
    if cursor.rowcount != 1:
        return None
    claimed = conn.execute("SELECT * FROM crawl_runs WHERE id = ?", (row["id"],)).fetchone()
    return dict(claimed or row)


def refresh_parent_run(conn: sqlite3.Connection, parent_run_id: str | None) -> None:
    if not parent_run_id:
        return
    children = conn.execute(
        """
        SELECT *
        FROM crawl_runs
        WHERE parent_run_id = ?
        ORDER BY COALESCE(batch_index, 0), created_at
        """,
        (parent_run_id,),
    ).fetchall()
    if not children:
        return
    statuses = [row["status"] for row in children]
    terminal = {"success", "partial_success", "failed", "cancelled"}
    saved = sum(int(row["saved_count"] or 0) for row in children)
    child_failures = sum(int(row["failure_count"] or 0) for row in children)
    cancelled_failures = sum(1 for row in children if row["status"] == "cancelled" and not int(row["failure_count"] or 0))
    failures = child_failures + cancelled_failures
    successes = sum(1 for row in children if row["status"] in {"success", "partial_success"})
    media_downloaded = sum(int(row["media_downloaded"] or 0) for row in children)
    media_failed = sum(int(row["media_failed"] or 0) for row in children)
    all_terminal = all(status in terminal for status in statuses)
    if all(status == "cancelled" for status in statuses):
        parent_status = "cancelled"
    elif all_terminal and failures and saved:
        parent_status = "partial_success"
    elif all_terminal and failures and not saved:
        parent_status = "failed"
    elif all_terminal:
        parent_status = "success"
    elif any(status in {"running", "success", "partial_success", "failed"} for status in statuses):
        parent_status = "running"
    else:
        parent_status = "queued"
    now = None
    if parent_status in {"success", "partial_success", "failed", "cancelled"}:
        from .models import utc_now_iso

        now = utc_now_iso()
    report = {
        "accounts": len(children),
        "successes": successes,
        "saved": saved,
        "failures": failures,
        "media": {"downloaded": media_downloaded, "failed": media_failed},
        "feishuWritten": 0,
        "details": [
            {
                "run_id": row["id"],
                "status": row["status"],
                "input": row["input_label"],
                "saved": int(row["saved_count"] or 0),
                "failures": int(row["failure_count"] or 0),
            }
            for row in children
        ],
    }
    conn.execute(
        """
        UPDATE crawl_runs
        SET status = ?, total_accounts = ?, success_count = ?, failure_count = ?,
            saved_count = ?, media_downloaded = ?, media_failed = ?,
            feishu_written = 0, report_json = ?, finished_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            parent_status,
            len(children),
            successes,
            failures,
            saved,
            media_downloaded,
            media_failed,
            json.dumps(report, ensure_ascii=False, sort_keys=True),
            now,
            parent_run_id,
        ),
    )
    conn.commit()


def requeue_failed_run_if_needed(
    conn: sqlite3.Connection,
    run: dict[str, Any],
    *,
    retry_delay_seconds: int = 60,
) -> bool:
    if run.get("status") != "failed":
        return False
    row = conn.execute("SELECT * FROM crawl_runs WHERE id = ?", (run["id"],)).fetchone()
    if row is None:
        return False
    attempt_count = int(row["attempt_count"] or 0)
    max_attempts = int(row["max_attempts"] or 1)
    if attempt_count >= max_attempts:
        return False
    report = json.loads(row["report_json"] or "{}")
    details = report.get("details") if isinstance(report.get("details"), list) else []
    details.append(
        {
            "message": "任务失败，已按 maxAttempts 自动回队列重试。",
            "attempt": attempt_count,
            "maxAttempts": max_attempts,
            "nextAttemptAt": delayed_iso(retry_delay_seconds),
        }
    )
    report["details"] = details[-80:]
    next_attempt_at = delayed_iso(retry_delay_seconds)
    last_error = None
    for detail in reversed(details):
        if isinstance(detail, dict) and detail.get("error"):
            last_error = detail.get("message") or detail.get("error")
            break
    conn.execute(
        """
        UPDATE crawl_runs
        SET status = 'queued',
            next_attempt_at = ?,
            locked_at = NULL,
            locked_by = NULL,
            last_error = ?,
            report_json = ?,
            finished_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (next_attempt_at, last_error, json.dumps(report, ensure_ascii=False, sort_keys=True), run["id"]),
    )
    conn.commit()
    return True


def process_next_queued_run(
    db_path: Path = DEFAULT_DB,
    *,
    retry_delay_seconds: int = 60,
    lock_id: str | None = None,
) -> dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)
    row = claim_next_queued_run(conn, lock_id=lock_id)
    if row is None:
        return {"processed": 0, "message": "no_queued_runs"}
    params = json.loads(row.get("params_json") or "{}")
    handler = _handler(db_path)
    run = handler.api_run_crawl(params, run_id=row["id"])
    conn = connect(db_path)
    init_db(conn)
    requeued = requeue_failed_run_if_needed(conn, run, retry_delay_seconds=retry_delay_seconds)
    refresh_parent_run(conn, row.get("parent_run_id"))
    if requeued:
        run = _handler(db_path).api_run_detail(row["id"])
    return {"processed": 1, "run": run, "requeued": requeued}


def process_queued_runs(
    db_path: Path = DEFAULT_DB,
    *,
    limit: int = 1,
    retry_delay_seconds: int = 60,
    lock_id: str | None = None,
) -> dict[str, Any]:
    processed = []
    for _ in range(max(0, limit)):
        result = process_next_queued_run(db_path, retry_delay_seconds=retry_delay_seconds, lock_id=lock_id)
        if not result.get("processed"):
            break
        processed.append(result["run"])
    return {"processed": len(processed), "runs": processed}


def run_worker_loop(
    db_path: Path = DEFAULT_DB,
    *,
    limit: int = 0,
    poll_interval_seconds: float = 5.0,
    idle_limit: int = 0,
    retry_delay_seconds: int = 60,
    lock_id: str | None = None,
) -> dict[str, Any]:
    processed: list[dict[str, Any]] = []
    idle_count = 0
    while True:
        if limit and len(processed) >= limit:
            break
        result = process_next_queued_run(db_path, retry_delay_seconds=retry_delay_seconds, lock_id=lock_id)
        if result.get("processed"):
            processed.append(result["run"])
            idle_count = 0
            continue
        idle_count += 1
        if idle_limit and idle_count >= idle_limit:
            break
        time.sleep(max(0.0, poll_interval_seconds))
    return {"processed": len(processed), "idle": idle_count, "runs": processed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued Radar collection tasks.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--daemon", action="store_true", help="Poll continuously until stopped or --limit is reached.")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--idle-limit", type=int, default=1)
    parser.add_argument("--retry-delay", type=int, default=60)
    args = parser.parse_args()
    if args.daemon:
        result = run_worker_loop(
            args.db,
            limit=max(0, args.limit),
            poll_interval_seconds=args.poll_interval,
            idle_limit=max(0, args.idle_limit),
            retry_delay_seconds=args.retry_delay,
        )
    else:
        result = process_queued_runs(args.db, limit=args.limit, retry_delay_seconds=args.retry_delay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
