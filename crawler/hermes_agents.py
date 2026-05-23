from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .account_enrichment import SEED_IDENTIFIERS
from .feishu_store import LocalFeishuStore
from .hermes_reports import write_agent_report
from .import_accounts import load_accounts_from_excel
from .markdown_store import content_uid, markdown_relative_path, render_content_markdown, update_frontmatter
from .providers import ProviderError, build_provider


DEFAULT_WORKSPACE = Path("feishu_workspace")
DEFAULT_EXCEL = Path("accounts.xlsx")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def source_account_to_record(index: int, account: Any) -> dict[str, Any]:
    return {
        "id": index,
        "category": account.category,
        "platform": account.platform,
        "account_name": account.account_name,
        "account_handle": None,
        "account_url": None,
        "original_account": account.original_account,
        "official_identity": account.official_identity,
        "radar_name": account.radar_name,
        "radar_persona": account.radar_persona,
        "threshold_views": account.threshold_views,
        "threshold_engagement_rate": account.threshold_engagement_rate,
        "average_views": account.average_views,
        "raw_average_views": account.raw_average_views,
        "raw_threshold": account.raw_threshold,
        "source_row_number": account.source_row_number,
        "data_quality_issue": account.data_quality_issue,
        "enabled": account.enabled,
        "fetch_interval_minutes": account.fetch_interval_minutes,
    }


def enrich_account_records(store: LocalFeishuStore) -> dict[str, int]:
    rows = store.read_table("source_accounts")
    updated = 0
    skipped = 0
    seed_map = {(item.platform, item.account_name): item for item in SEED_IDENTIFIERS}
    for row in rows:
        seed = seed_map.get((row.get("platform"), row.get("account_name")))
        if seed is None:
            continue
        if row.get("account_handle") or row.get("account_url"):
            skipped += 1
            continue
        row["account_handle"] = seed.account_handle
        row["account_url"] = seed.account_url
        row["updated_at"] = now_iso()
        updated += 1
    store.write_table("source_accounts", rows)
    return {"updated": updated, "skipped": skipped, "total": len(rows)}


def cmd_init_feishu(args: argparse.Namespace) -> int:
    store = LocalFeishuStore(args.workspace)
    accounts = load_accounts_from_excel(args.excel)
    for index, account in enumerate(accounts, start=1):
        record = source_account_to_record(index, account)
        store.upsert_record("source_accounts", f"{account.platform}:{account.account_name}", record)
    enrich_result = enrich_account_records(store)
    print({"imported": len(accounts), "enriched": enrich_result, "workspace": str(args.workspace)})
    return 0


def enabled_accounts(store: LocalFeishuStore, *, platform: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [row for row in store.read_table("source_accounts") if row.get("enabled", True)]
    if platform:
        rows = [row for row in rows if row.get("platform") == platform]
    rows.sort(key=lambda row: (row.get("platform") or "", row.get("id") or 0))
    return rows[:limit] if limit else rows


def cmd_crawler(args: argparse.Namespace) -> int:
    store = LocalFeishuStore(args.workspace)
    started_at = now_iso()
    accounts = enabled_accounts(store, platform=args.platform, limit=args.limit)
    providers = {}
    success_count = 0
    failure_count = 0
    category_counter: Counter[str] = Counter()
    top_items: list[dict[str, Any]] = []
    failed_items: list[dict[str, Any]] = []

    for account in accounts:
        platform = account["platform"]
        provider_key = (platform, args.mode)
        try:
            if provider_key not in providers:
                providers[provider_key] = build_provider(platform, mode=args.mode)
            result = providers[provider_key].fetch(account, max_results=args.max_results)
            for item in result.items:
                uid = content_uid(item.platform, item.original_content_id)
                existing = store.query_records("content_index", unique_key=uid)
                existing_record = existing[0] if existing else {}
                relative_path = Path(existing_record["markdown_path"]) if existing_record.get("markdown_path") else markdown_relative_path(account, item)
                if existing_record.get("markdown_path"):
                    try:
                        markdown = update_frontmatter(
                            store.read_markdown(existing_record["markdown_path"]),
                            {
                                "crawl_status": "success",
                                "updated_at": now_iso(),
                            },
                        )
                    except FileNotFoundError:
                        markdown = render_content_markdown(account=account, item=item, markdown_file_token=str(relative_path))
                else:
                    markdown = render_content_markdown(account=account, item=item, markdown_file_token=str(relative_path))
                location = store.write_markdown(relative_path, markdown)
                record = {
                    "content_id": uid,
                    "platform": item.platform,
                    "original_content_id": item.original_content_id,
                    "title": item.title or item.text or item.original_content_id,
                    "category": account.get("category"),
                    "account": account.get("account_name"),
                    "source_url": item.url,
                    "published_at": item.published_at,
                    "crawl_status": "success",
                    "organize_status": existing_record.get("organize_status", "pending"),
                    "review_status": existing_record.get("review_status", "pending"),
                    "publish_status": existing_record.get("publish_status", "pending"),
                    "target_app": existing_record.get("target_app"),
                    **location,
                }
                store.upsert_record("content_index", uid, record)
                success_count += 1
                category_counter[account.get("category") or "未分类"] += 1
                if len(top_items) < 5:
                    top_items.append(
                        {
                            "title": record["title"],
                            "platform": item.platform,
                            "account": account.get("account_name"),
                            "url": item.url,
                        }
                    )
            print(f"{platform}:{account['account_name']} saved={len(result.items)}")
        except ProviderError as exc:
            failure_count += 1
            failed = {
                "platform": platform,
                "account": account.get("account_name"),
                "error_type": exc.error_type,
                "error_message": str(exc),
            }
            failed_items.append(failed)
            store.upsert_record("failures", f"{platform}:{account.get('account_name')}:{started_at}", failed)
            print(f"{platform}:{account['account_name']} failed={exc.error_type}")

    report = write_agent_report(
        store,
        agent_name="content_crawler",
        run_type="crawl",
        status="success" if failure_count == 0 else "partial_success",
        started_at=started_at,
        total_count=len(accounts),
        success_count=success_count,
        failure_count=failure_count,
        category_stats=dict(category_counter),
        top_items=top_items,
        failed_items=failed_items[:10],
        next_actions=[
            "Hermes 读取本报告后由绑定的飞书智能体机器人发送通知。",
            "YouTube RSS 内容缺少播放量指标，默认进入 metrics_pending。",
        ],
    )
    print(report)
    return 0 if failure_count == 0 or args.allow_failures else 1


def cmd_organizer(args: argparse.Namespace) -> int:
    store = LocalFeishuStore(args.workspace)
    started_at = now_iso()
    pending = store.query_records("content_index", organize_status="pending")[: args.limit]
    success_count = 0
    failed_items: list[dict[str, Any]] = []
    category_counter: Counter[str] = Counter()
    for record in pending:
        try:
            markdown = store.read_markdown(record["markdown_path"])
            organized = markdown.replace("待整理。", f"摘要：{record.get('title') or ''}\n\n建议按「{record.get('category') or '未分类'}」方向整理。")
            organized = organized.replace("待评估。", "需人工确认来源事实、时效性和版权风险。")
            organized = organized.replace("待生成。", "适合进入飞书审核看板，由运营确认后发布。")
            organized = update_frontmatter(
                organized,
                {
                    "organize_status": "organized",
                    "review_status": "pending",
                    "updated_at": now_iso(),
                },
            )
            location = store.move_markdown(record["markdown_path"], "02_待审核")
            organized = update_frontmatter(
                organized,
                {
                    "markdown_file_token": location["markdown_file_token"],
                    "updated_at": now_iso(),
                },
            )
            store.update_markdown(location["markdown_path"], organized)
            store.upsert_record(
                "content_index",
                record["unique_key"],
                {
                    **record,
                    **location,
                    "organize_status": "organized",
                    "review_status": "pending",
                },
            )
            success_count += 1
            category_counter[record.get("category") or "未分类"] += 1
        except Exception as exc:
            failed_items.append({"content_id": record.get("content_id"), "error": type(exc).__name__, "message": str(exc)})

    report = write_agent_report(
        store,
        agent_name="content_organizer",
        run_type="organize",
        status="success" if not failed_items else "partial_success",
        started_at=started_at,
        total_count=len(pending),
        success_count=success_count,
        failure_count=len(failed_items),
        category_stats=dict(category_counter),
        failed_items=failed_items,
        next_actions=["Hermes 可将本批整理结果通知到飞书审核群。"],
    )
    print(report)
    return 0 if not failed_items or args.allow_failures else 1


def cmd_publisher(args: argparse.Namespace) -> int:
    store = LocalFeishuStore(args.workspace)
    started_at = now_iso()
    candidates = [
        row
        for row in store.read_table("content_index")
        if row.get("review_status") == "approved" and row.get("publish_status") == "pending"
    ][: args.limit]
    success_count = 0
    failed_items: list[dict[str, Any]] = []
    top_items: list[dict[str, Any]] = []
    for record in candidates:
        try:
            markdown = store.read_markdown(record["markdown_path"])
            published_url = f"dry-run://{args.target_app}/{record['content_id']}"
            markdown = update_frontmatter(
                markdown,
                {
                    "publish_status": "published" if not args.dry_run else "pending",
                    "target_app": args.target_app,
                    "updated_at": now_iso(),
                },
            )
            target_folder = "03_待发布" if args.dry_run else "04_已发布"
            location = store.move_markdown(record["markdown_path"], target_folder)
            markdown = update_frontmatter(
                markdown,
                {
                    "markdown_file_token": location["markdown_file_token"],
                    "updated_at": now_iso(),
                },
            )
            store.update_markdown(location["markdown_path"], markdown)
            store.upsert_record(
                "content_index",
                record["unique_key"],
                {
                    **record,
                    **location,
                    "target_app": args.target_app,
                    "publish_status": "pending" if args.dry_run else "published",
                    "published_url": published_url if not args.dry_run else "",
                    "publish_error": "",
                },
            )
            store.upsert_record(
                "publish_records",
                f"{record['content_id']}:{args.target_app}",
                {
                    "content_id": record["content_id"],
                    "target_app": args.target_app,
                    "status": "dry_run" if args.dry_run else "published",
                    "published_url": published_url,
                },
            )
            success_count += 1
            if len(top_items) < 5:
                top_items.append({"title": record.get("title"), "target_app": args.target_app, "url": published_url})
        except Exception as exc:
            failed_items.append({"content_id": record.get("content_id"), "error": type(exc).__name__, "message": str(exc)})

    report = write_agent_report(
        store,
        agent_name="content_publisher",
        run_type="publish_dry_run" if args.dry_run else "publish",
        status="success" if not failed_items else "partial_success",
        started_at=started_at,
        total_count=len(candidates),
        success_count=success_count,
        failure_count=len(failed_items),
        top_items=top_items,
        failed_items=failed_items,
        next_actions=["真实内部 APP 接口确定后，将 dry-run payload 替换为 HTTP API 调用。"],
    )
    print(report)
    return 0 if not failed_items or args.allow_failures else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Radar agents using Feishu Drive Markdown + Bitable index")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-feishu", help="initialize local Feishu-like workspace from Excel")
    init_parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL)
    init_parser.set_defaults(func=cmd_init_feishu)

    crawler_parser = subparsers.add_parser("crawler", help="run content crawler agent")
    crawler_parser.add_argument("--platform", choices=["x", "youtube", "linkedin", "instagram"])
    crawler_parser.add_argument(
        "--mode",
        choices=["auto", "no-token", "api", "browser-session", "chrome-session", "xmcp", "x-rss"],
        default="no-token",
    )
    crawler_parser.add_argument("--limit", type=int)
    crawler_parser.add_argument("--max-results", type=int, default=5)
    crawler_parser.add_argument("--allow-failures", action="store_true")
    crawler_parser.set_defaults(func=cmd_crawler)

    organizer_parser = subparsers.add_parser("organizer", help="run content organizer agent")
    organizer_parser.add_argument("--limit", type=int, default=50)
    organizer_parser.add_argument("--allow-failures", action="store_true")
    organizer_parser.set_defaults(func=cmd_organizer)

    publisher_parser = subparsers.add_parser("publisher", help="run content publisher agent")
    publisher_parser.add_argument("--target-app", default="radar_app")
    publisher_parser.add_argument("--limit", type=int, default=20)
    publisher_parser.add_argument("--dry-run", action="store_true", default=True)
    publisher_parser.add_argument("--allow-failures", action="store_true")
    publisher_parser.set_defaults(func=cmd_publisher)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
