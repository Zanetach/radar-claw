from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .feishu_store import LocalFeishuStore


def run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def write_agent_report(
    store: LocalFeishuStore,
    *,
    agent_name: str,
    run_type: str,
    status: str,
    started_at: str,
    total_count: int,
    success_count: int,
    failure_count: int,
    category_stats: dict[str, int] | None = None,
    top_items: list[dict[str, Any]] | None = None,
    failed_items: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rid = run_id(agent_name.replace("content_", ""))
    report = {
        "agent_name": agent_name,
        "run_id": rid,
        "run_type": run_type,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "category_stats": category_stats or {},
        "top_items": top_items or [],
        "failed_items": failed_items or [],
        "next_actions": next_actions or [],
    }
    location = store.write_run_report(agent_name, rid, report)
    full_report = {**report, **location}
    store.upsert_record(
        "agent_runs",
        rid,
        {
            "agent_name": agent_name,
            "run_type": run_type,
            "status": status,
            "total_count": total_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "report_path": location["report_path"],
            "report_url": location["report_url"],
            "started_at": started_at,
            "finished_at": finished_at,
            "summary_json": report,
        },
    )
    return full_report
