from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from .db import connect, init_db, log_failure, save_fetch_result, upsert_accounts
from .account_enrichment import enrich_accounts
from .import_accounts import load_accounts_from_excel
from .providers import ProviderError, build_provider
from .x_intel import BESTBLOGS_OPML_URL, fetch_bestblogs_accounts, upsert_x_intel_accounts
from .media_downloader import DEFAULT_MEDIA_DIR, download_fetch_result_media
from .models import FetchResult


DEFAULT_DB = Path("data/radar_sources.sqlite3")
DEFAULT_EXCEL = Path("外网抓取账号0424.xlsx")


def filter_fetch_result(result: FetchResult, *, media_only: bool = False) -> FetchResult:
    items = result.items
    if media_only:
        items = [item for item in items if item.media_assets]
    return FetchResult(
        account_id=result.account_id,
        platform=result.platform,
        items=items,
        next_cursor=result.next_cursor,
        last_seen_original_id=items[0].original_content_id if items else result.last_seen_original_id,
    )


def normalize_person_identifier(platform: str, value: str) -> tuple[str | None, str | None, str]:
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        parts = [part for part in parsed.path.split("/") if part]
        handle = None
        if platform == "x" and parts:
            handle = parts[0].lstrip("@")
        elif platform == "instagram" and parts:
            handle = parts[0].lstrip("@")
        elif platform == "youtube" and parts:
            handle = parts[0] if parts[0].startswith("@") else None
        elif platform == "linkedin" and len(parts) >= 2:
            handle = "/".join(parts[:2])
        return handle, text, handle or text
    handle = text.lstrip("@")
    url = None
    if platform == "x":
        url = f"https://x.com/{handle}"
    elif platform == "instagram":
        url = f"https://www.instagram.com/{handle}/"
    elif platform == "youtube":
        url = f"https://www.youtube.com/{text if text.startswith('@') else '@' + handle}"
        handle = text if text.startswith("@") else f"@{handle}"
    elif platform == "linkedin":
        url = text if text.startswith("urn:") else f"https://www.linkedin.com/in/{handle}/"
    return handle, url, handle


def upsert_person_account(
    conn: sqlite3.Connection,
    *,
    platform: str,
    identifier: str,
    account_name: str | None,
    category: str,
) -> sqlite3.Row:
    handle, url, fallback_name = normalize_person_identifier(platform, identifier)
    name = account_name or fallback_name
    now_sql = "CURRENT_TIMESTAMP"
    conn.execute(
        f"""
        INSERT INTO source_accounts (
            category, platform, account_name, account_handle, account_url,
            original_account, official_identity, radar_name, radar_persona,
            enabled, fetch_interval_minutes, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 720, {now_sql})
        ON CONFLICT(platform, account_name) DO UPDATE SET
            account_handle = excluded.account_handle,
            account_url = excluded.account_url,
            category = excluded.category,
            enabled = 1,
            updated_at = {now_sql}
        """,
        (
            category,
            platform,
            name,
            handle,
            url,
            f"{platform}-{name}",
            name,
            name,
            "single-person-crawl",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM source_accounts WHERE platform = ? AND account_name = ?",
        (platform, name),
    ).fetchone()
    if row is None:
        raise RuntimeError("failed to create person account")
    return row


def cmd_init_db(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    print(f"initialized database: {args.db}")
    return 0


def cmd_import_accounts(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    accounts = load_accounts_from_excel(args.excel)
    count = upsert_accounts(conn, accounts)
    quality_issues = sum(1 for account in accounts if account.data_quality_issue)
    print(f"imported source accounts: {count}")
    print(f"data quality issues: {quality_issues}")
    return 0


def cmd_enrich_accounts(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    result = enrich_accounts(conn, overwrite=args.overwrite)
    print(f"enriched source accounts: {result}")
    return 0


def cmd_import_x_intel(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    accounts = fetch_bestblogs_accounts(args.opml_url)
    imported = upsert_x_intel_accounts(conn, accounts, category=args.category, limit=args.limit)
    print(f"imported x intel accounts: {imported}")
    print(f"source opml accounts: {len(accounts)}")
    return 0


def account_rows(
    conn: sqlite3.Connection,
    *,
    platform: str | None,
    category: str | None = None,
    limit: int | None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM source_accounts WHERE enabled = 1"
    params: list[object] = []
    if platform:
        sql += " AND platform = ?"
        params.append(platform)
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY platform, id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def cmd_crawl(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    rows = account_rows(conn, platform=args.platform, category=args.category, limit=args.limit)
    if not rows:
        print("no enabled source accounts found")
        return 0

    providers = {}
    total_items = 0
    total_failures = 0
    for row in rows:
        account = dict(row)
        platform = account["platform"]
        provider_key = (platform, args.mode)
        try:
            if provider_key not in providers:
                providers[provider_key] = build_provider(platform, mode=args.mode)
            result = providers[provider_key].fetch(account, max_results=args.max_results)
            result = filter_fetch_result(result, media_only=args.media_only)
            media_stats = {"downloaded": 0, "failed": 0}
            if args.download_media:
                media_stats = download_fetch_result_media(result, account=account, media_root=args.media_dir)
            saved = save_fetch_result(conn, result)
            total_items += saved
            print(
                f"{platform}:{account['account_name']} mode={args.mode} saved={saved} "
                f"media_downloaded={media_stats['downloaded']} media_failed={media_stats['failed']}"
            )
        except ProviderError as exc:
            total_failures += 1
            log_failure(
                conn,
                source_account_id=account["id"],
                platform=platform,
                error_type=exc.error_type,
                error_message=str(exc),
                status_code=exc.status_code,
                raw_context={"account_name": account["account_name"], "mode": args.mode},
            )
            print(f"{platform}:{account['account_name']} mode={args.mode} failed={exc.error_type}")
        except Exception as exc:
            total_failures += 1
            log_failure(
                conn,
                source_account_id=account["id"],
                platform=platform,
                error_type=type(exc).__name__,
                error_message=str(exc),
                raw_context={"account_name": account["account_name"], "mode": args.mode},
            )
            print(f"{platform}:{account['account_name']} mode={args.mode} failed={type(exc).__name__}")

    print(f"crawl complete accounts={len(rows)} saved={total_items} failures={total_failures}")
    return 1 if total_failures and not args.allow_failures else 0


def cmd_crawl_person(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    row = upsert_person_account(
        conn,
        platform=args.platform,
        identifier=args.identifier,
        account_name=args.account_name,
        category=args.category,
    )
    account = dict(row)
    try:
        provider = build_provider(args.platform, mode=args.mode)
        result = provider.fetch(account, max_results=args.max_results)
        result = filter_fetch_result(result, media_only=args.media_only)
        media_stats = {"downloaded": 0, "failed": 0}
        if args.download_media:
            media_stats = download_fetch_result_media(result, account=account, media_root=args.media_dir)
        saved = save_fetch_result(conn, result)
        media_count = sum(len(item.media_assets) for item in result.items)
        print(
            f"{args.platform}:{account['account_name']} mode={args.mode} "
            f"saved={saved} media_assets={media_count} "
            f"media_downloaded={media_stats['downloaded']} media_failed={media_stats['failed']}"
        )
        return 0
    except ProviderError as exc:
        log_failure(
            conn,
            source_account_id=account["id"],
            platform=args.platform,
            error_type=exc.error_type,
            error_message=str(exc),
            status_code=exc.status_code,
            raw_context={"identifier": args.identifier, "mode": args.mode, "source": "crawl-person"},
        )
        print(f"{args.platform}:{account['account_name']} mode={args.mode} failed={exc.error_type}")
        return 1


def cmd_worker(args: argparse.Namespace) -> int:
    from .worker import process_queued_runs, run_worker_loop

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
    print(f"worker processed queued runs: {result['processed']}")
    for run in result["runs"]:
        print(f"{run['id']} status={run['status']} saved={run['saved_count']} failures={run['failure_count']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Radar external source account crawler")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="create database schema")
    init_parser.set_defaults(func=cmd_init_db)

    import_parser = subparsers.add_parser("import-accounts", help="import accounts from Excel")
    import_parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL, help="source Excel path")
    import_parser.set_defaults(func=cmd_import_accounts)

    enrich_parser = subparsers.add_parser("enrich-accounts", help="fill known account handles and URLs")
    enrich_parser.add_argument("--overwrite", action="store_true", help="overwrite existing account_handle/account_url")
    enrich_parser.set_defaults(func=cmd_enrich_accounts)

    crawl_parser = subparsers.add_parser("crawl", help="crawl enabled source accounts")
    crawl_parser.add_argument("--platform", choices=["x", "youtube", "linkedin", "instagram"])
    crawl_parser.add_argument("--category", help="only crawl accounts in this category")
    crawl_parser.add_argument(
        "--mode",
        choices=[
            "auto",
            "no-token",
            "api",
            "browser-session",
            "chrome-session",
            "xmcp",
            "beeclaw",
            "beeclaw:x",
            "beeclaw:x_mcp",
            "beeclaw:x_api",
            "beeclaw:x_rss",
            "feedgrab",
            "feedgrab:x",
            "feedgrab:x_mcp",
            "feedgrab:x_api",
            "feedgrab:x_rss",
            "x-rss",
        ],
        default="auto",
        help="crawl mode: auto uses Beeclaw X backend selection (x_mcp -> x_api -> x_rss)",
    )
    crawl_parser.add_argument("--limit", type=int, help="maximum accounts to crawl")
    crawl_parser.add_argument("--max-results", type=int, default=20, help="maximum content items per account")
    crawl_parser.add_argument("--download-media", action="store_true", help="download available media assets")
    crawl_parser.add_argument("--media-only", action="store_true", help="only save posts with images or videos")
    crawl_parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR, help="media download directory")
    crawl_parser.add_argument("--allow-failures", action="store_true", help="return zero even if some accounts fail")
    crawl_parser.set_defaults(func=cmd_crawl)

    person_parser = subparsers.add_parser("crawl-person", help="crawl one person/account by handle or URL")
    person_parser.add_argument("--platform", required=True, choices=["x", "youtube", "linkedin", "instagram"])
    person_parser.add_argument("--identifier", required=True, help="handle or profile URL")
    person_parser.add_argument("--account-name", help="display name saved in source_accounts")
    person_parser.add_argument("--category", default="单人采集", help="category saved for this account")
    person_parser.add_argument(
        "--mode",
        choices=[
            "auto",
            "no-token",
            "api",
            "browser-session",
            "chrome-session",
            "xmcp",
            "beeclaw",
            "beeclaw:x",
            "beeclaw:x_mcp",
            "beeclaw:x_api",
            "beeclaw:x_rss",
            "feedgrab",
            "feedgrab:x",
            "feedgrab:x_mcp",
            "feedgrab:x_api",
            "feedgrab:x_rss",
            "x-rss",
        ],
        default="auto",
    )
    person_parser.add_argument("--max-results", type=int, default=20)
    person_parser.add_argument("--download-media", action="store_true", help="download available media assets")
    person_parser.add_argument("--media-only", action="store_true", help="only save posts with images or videos")
    person_parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR, help="media download directory")
    person_parser.set_defaults(func=cmd_crawl_person)

    worker_parser = subparsers.add_parser("worker", help="process queued collection tasks")
    worker_parser.add_argument("--limit", type=int, default=1, help="maximum queued tasks to process")
    worker_parser.add_argument("--daemon", action="store_true", help="poll continuously until stopped or --limit is reached")
    worker_parser.add_argument("--poll-interval", type=float, default=5.0, help="seconds between empty queue polls")
    worker_parser.add_argument("--idle-limit", type=int, default=1, help="stop daemon after this many empty polls; 0 means never stop")
    worker_parser.add_argument("--retry-delay", type=int, default=60, help="seconds before failed retryable tasks are requeued")
    worker_parser.set_defaults(func=cmd_worker)

    intel_parser = subparsers.add_parser("import-x-intel", help="import BestBlogs/xgo.ing X RSS accounts")
    intel_parser.add_argument("--opml-url", default=BESTBLOGS_OPML_URL)
    intel_parser.add_argument("--category", default="AI情报源")
    intel_parser.add_argument("--limit", type=int)
    intel_parser.set_defaults(func=cmd_import_x_intel)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
