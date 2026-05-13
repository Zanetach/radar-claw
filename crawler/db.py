from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import ContentItem, FetchResult, SourceAccount, utc_now_iso


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    platform TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_handle TEXT,
    account_url TEXT,
    original_account TEXT NOT NULL,
    official_identity TEXT,
    radar_name TEXT,
    radar_persona TEXT,
    threshold_views INTEGER,
    threshold_engagement_rate REAL,
    average_views INTEGER,
    raw_average_views TEXT,
    raw_threshold TEXT,
    source_row_number INTEGER,
    data_quality_issue TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    fetch_interval_minutes INTEGER NOT NULL DEFAULT 720,
    last_seen_original_id TEXT,
    pagination_cursor TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform, account_name)
);

CREATE TABLE IF NOT EXISTS source_contents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_account_id INTEGER NOT NULL REFERENCES source_accounts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    provider TEXT,
    original_content_id TEXT NOT NULL,
    title TEXT,
    text TEXT,
    published_at TEXT,
    channel_published_at TEXT,
    url TEXT,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    share_count INTEGER,
    media_type TEXT,
    language TEXT,
    media_assets_json TEXT NOT NULL DEFAULT '[]',
    engagement_rate REAL,
    qualification_status TEXT NOT NULL,
    crawl_status TEXT NOT NULL DEFAULT 'success',
    organize_status TEXT NOT NULL DEFAULT 'pending',
    review_status TEXT NOT NULL DEFAULT 'raw',
    publish_status TEXT NOT NULL DEFAULT 'not_ready',
    organized_title TEXT,
    organized_summary TEXT,
    organized_markdown TEXT,
    original_text TEXT,
    translated_text_zh TEXT,
    translation_status TEXT NOT NULL DEFAULT 'pending',
    translation_provider TEXT,
    ocr_text_original TEXT,
    ocr_text_zh TEXT,
    quality_score REAL,
    quality_reason TEXT,
    content_category TEXT,
    organize_notes TEXT,
    target_channel TEXT,
    published_url TEXT,
    publish_error TEXT,
    fetched_at TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform, original_content_id)
);

CREATE TABLE IF NOT EXISTS crawl_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_account_id INTEGER REFERENCES source_accounts(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    status_code INTEGER,
    occurred_at TEXT NOT NULL,
    raw_context_json TEXT
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL DEFAULT 'crawler',
    source_type TEXT NOT NULL,
    platform TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    input_label TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    total_accounts INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    saved_count INTEGER NOT NULL DEFAULT 0,
    media_downloaded INTEGER NOT NULL DEFAULT 0,
    media_failed INTEGER NOT NULL DEFAULT 0,
    feishu_written INTEGER NOT NULL DEFAULT 0,
    report_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crawl_run_contents (
    run_id TEXT NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    content_id INTEGER NOT NULL REFERENCES source_contents(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, content_id)
);

CREATE TABLE IF NOT EXISTS crawl_strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    platform TEXT NOT NULL DEFAULT 'x',
    mode TEXT NOT NULL DEFAULT 'xmcp',
    date_range TEXT NOT NULL DEFAULT '7d',
    category TEXT,
    max_results INTEGER NOT NULL DEFAULT 20,
    min_views INTEGER,
    language TEXT NOT NULL DEFAULT 'all',
    include_original INTEGER NOT NULL DEFAULT 1,
    include_quotes INTEGER NOT NULL DEFAULT 1,
    include_replies INTEGER NOT NULL DEFAULT 0,
    include_retweets INTEGER NOT NULL DEFAULT 0,
    download_images INTEGER NOT NULL DEFAULT 1,
    download_videos INTEGER NOT NULL DEFAULT 1,
    media_only INTEGER NOT NULL DEFAULT 0,
    translate_after_crawl INTEGER NOT NULL DEFAULT 0,
    ocr_images INTEGER NOT NULL DEFAULT 0,
    dedupe_policy TEXT NOT NULL DEFAULT 'platform_original_content_id',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    params_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publish_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES source_contents(id) ON DELETE CASCADE,
    target_channel TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    published_url TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_accounts_platform_enabled
    ON source_accounts(platform, enabled);

CREATE INDEX IF NOT EXISTS idx_source_contents_account_published
    ON source_contents(source_account_id, published_at);

CREATE INDEX IF NOT EXISTS idx_source_contents_qualification
    ON source_contents(qualification_status);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_started_at
    ON crawl_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_crawl_run_contents_content
    ON crawl_run_contents(content_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    ensure_schema_migrations(conn)
    seed_default_strategies(conn)
    conn.commit()


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    content_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(source_contents)").fetchall()
    }
    if "media_assets_json" not in content_columns:
        conn.execute("ALTER TABLE source_contents ADD COLUMN media_assets_json TEXT NOT NULL DEFAULT '[]'")
    content_additions = {
        "crawl_status": "TEXT NOT NULL DEFAULT 'success'",
        "organize_status": "TEXT NOT NULL DEFAULT 'pending'",
        "review_status": "TEXT NOT NULL DEFAULT 'raw'",
        "publish_status": "TEXT NOT NULL DEFAULT 'not_ready'",
        "organized_title": "TEXT",
        "organized_summary": "TEXT",
        "organized_markdown": "TEXT",
        "original_text": "TEXT",
        "translated_text_zh": "TEXT",
        "translation_status": "TEXT NOT NULL DEFAULT 'pending'",
        "translation_provider": "TEXT",
        "ocr_text_original": "TEXT",
        "ocr_text_zh": "TEXT",
        "quality_score": "REAL",
        "quality_reason": "TEXT",
        "content_category": "TEXT",
        "organize_notes": "TEXT",
        "target_channel": "TEXT",
        "published_url": "TEXT",
        "published_at": "TEXT",
        "channel_published_at": "TEXT",
        "provider": "TEXT",
        "publish_error": "TEXT",
    }
    for column, definition in content_additions.items():
        if column not in content_columns:
            conn.execute(f"ALTER TABLE source_contents ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_contents_workflow
        ON source_contents(organize_status, review_status, publish_status)
        """
    )
    run_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(crawl_runs)").fetchall()
    }
    if "agent_type" not in run_columns:
        conn.execute("ALTER TABLE crawl_runs ADD COLUMN agent_type TEXT NOT NULL DEFAULT 'crawler'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_run_contents (
            run_id TEXT NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
            content_id INTEGER NOT NULL REFERENCES source_contents(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (run_id, content_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_crawl_run_contents_content
        ON crawl_run_contents(content_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            platform TEXT NOT NULL DEFAULT 'x',
            mode TEXT NOT NULL DEFAULT 'xmcp',
            date_range TEXT NOT NULL DEFAULT '7d',
            category TEXT,
            max_results INTEGER NOT NULL DEFAULT 20,
            min_views INTEGER,
            language TEXT NOT NULL DEFAULT 'all',
            include_original INTEGER NOT NULL DEFAULT 1,
            include_quotes INTEGER NOT NULL DEFAULT 1,
            include_replies INTEGER NOT NULL DEFAULT 0,
            include_retweets INTEGER NOT NULL DEFAULT 0,
            download_images INTEGER NOT NULL DEFAULT 1,
            download_videos INTEGER NOT NULL DEFAULT 1,
            media_only INTEGER NOT NULL DEFAULT 0,
            translate_after_crawl INTEGER NOT NULL DEFAULT 0,
            ocr_images INTEGER NOT NULL DEFAULT 0,
            dedupe_policy TEXT NOT NULL DEFAULT 'platform_original_content_id',
            is_builtin INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            params_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


DEFAULT_STRATEGIES: tuple[dict, ...] = (
    {
        "id": "x-7d-original-media",
        "name": "X 近 7 天原创带媒体",
        "description": "生产默认：feedgrab + X MCP，最近 7 天，只保留原创与引用，下载图片和视频。",
        "platform": "x",
        "mode": "feedgrab:x_mcp",
        "date_range": "7d",
        "max_results": 20,
        "include_original": 1,
        "include_quotes": 1,
        "include_replies": 0,
        "include_retweets": 0,
        "download_images": 1,
        "download_videos": 1,
        "media_only": 0,
        "translate_after_crawl": 0,
        "ocr_images": 0,
    },
    {
        "id": "x-rss-ai-intel",
        "name": "X 免费 x-rss 情报源",
        "description": "免费兜底：xgo.ing RSS / AI 情报源，不要求 token，适合先跑通文本和图片。",
        "platform": "x",
        "mode": "x-rss",
        "date_range": "7d",
        "category": "AI情报源",
        "max_results": 20,
        "include_original": 1,
        "include_quotes": 1,
        "include_replies": 0,
        "include_retweets": 0,
        "download_images": 1,
        "download_videos": 0,
        "media_only": 0,
        "translate_after_crawl": 0,
        "ocr_images": 0,
    },
    {
        "id": "x-api-xmcp-full-metadata",
        "name": "X API/XMCP 全量元数据",
        "description": "付费/正式：优先 feedgrab X MCP/API，保留指标、引用和媒体元数据。",
        "platform": "x",
        "mode": "feedgrab:x_mcp",
        "date_range": "7d",
        "max_results": 50,
        "include_original": 1,
        "include_quotes": 1,
        "include_replies": 0,
        "include_retweets": 0,
        "download_images": 1,
        "download_videos": 1,
        "media_only": 0,
        "translate_after_crawl": 0,
        "ocr_images": 0,
    },
    {
        "id": "linkedin-browser-debug",
        "name": "LinkedIn 登录态调试",
        "description": "调试模式：使用登录态浏览器链路，仅用于已登录账号与小批量验证。",
        "platform": "linkedin",
        "mode": "chrome-session",
        "date_range": "7d",
        "max_results": 10,
        "include_original": 1,
        "include_quotes": 1,
        "include_replies": 0,
        "include_retweets": 0,
        "download_images": 1,
        "download_videos": 1,
        "media_only": 0,
        "translate_after_crawl": 0,
        "ocr_images": 0,
    },
    {
        "id": "instagram-browser-debug",
        "name": "Instagram 登录态调试",
        "description": "调试模式：使用登录态浏览器链路，仅用于已登录账号与小批量验证。",
        "platform": "instagram",
        "mode": "chrome-session",
        "date_range": "7d",
        "max_results": 10,
        "include_original": 1,
        "include_quotes": 1,
        "include_replies": 0,
        "include_retweets": 0,
        "download_images": 1,
        "download_videos": 1,
        "media_only": 0,
        "translate_after_crawl": 0,
        "ocr_images": 0,
    },
)


def seed_default_strategies(conn: sqlite3.Connection) -> None:
    for strategy in DEFAULT_STRATEGIES:
        payload = {
            "dedupePolicy": strategy.get("dedupe_policy", "platform_original_content_id"),
        }
        conn.execute(
            """
            INSERT INTO crawl_strategies (
                id, name, description, platform, mode, date_range, category,
                max_results, min_views, language, include_original, include_quotes,
                include_replies, include_retweets, download_images, download_videos,
                media_only, translate_after_crawl, ocr_images, dedupe_policy,
                is_builtin, enabled, params_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                platform = excluded.platform,
                mode = excluded.mode,
                date_range = excluded.date_range,
                category = excluded.category,
                max_results = excluded.max_results,
                min_views = excluded.min_views,
                language = excluded.language,
                include_original = excluded.include_original,
                include_quotes = excluded.include_quotes,
                include_replies = excluded.include_replies,
                include_retweets = excluded.include_retweets,
                download_images = excluded.download_images,
                download_videos = excluded.download_videos,
                media_only = excluded.media_only,
                translate_after_crawl = excluded.translate_after_crawl,
                ocr_images = excluded.ocr_images,
                dedupe_policy = excluded.dedupe_policy,
                is_builtin = 1,
                enabled = 1,
                params_json = excluded.params_json,
                updated_at = excluded.updated_at
            """,
            (
                strategy["id"],
                strategy["name"],
                strategy.get("description"),
                strategy.get("platform", "x"),
                strategy.get("mode", "xmcp"),
                strategy.get("date_range", "7d"),
                strategy.get("category"),
                strategy.get("max_results", 20),
                strategy.get("min_views"),
                strategy.get("language", "all"),
                strategy.get("include_original", 1),
                strategy.get("include_quotes", 1),
                strategy.get("include_replies", 0),
                strategy.get("include_retweets", 0),
                strategy.get("download_images", 1),
                strategy.get("download_videos", 1),
                strategy.get("media_only", 0),
                strategy.get("translate_after_crawl", 0),
                strategy.get("ocr_images", 0),
                strategy.get("dedupe_policy", "platform_original_content_id"),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )


def upsert_accounts(conn: sqlite3.Connection, accounts: Iterable[SourceAccount]) -> int:
    count = 0
    for account in accounts:
        conn.execute(
            """
            INSERT INTO source_accounts (
                category, platform, account_name, original_account, official_identity,
                radar_name, radar_persona, threshold_views, threshold_engagement_rate,
                average_views, raw_average_views, raw_threshold, source_row_number,
                data_quality_issue, enabled, fetch_interval_minutes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, account_name) DO UPDATE SET
                category = excluded.category,
                original_account = excluded.original_account,
                official_identity = excluded.official_identity,
                radar_name = excluded.radar_name,
                radar_persona = excluded.radar_persona,
                threshold_views = excluded.threshold_views,
                threshold_engagement_rate = excluded.threshold_engagement_rate,
                average_views = excluded.average_views,
                raw_average_views = excluded.raw_average_views,
                raw_threshold = excluded.raw_threshold,
                source_row_number = excluded.source_row_number,
                data_quality_issue = excluded.data_quality_issue,
                enabled = excluded.enabled,
                fetch_interval_minutes = excluded.fetch_interval_minutes,
                updated_at = excluded.updated_at
            """,
            (
                account.category,
                account.platform,
                account.account_name,
                account.original_account,
                account.official_identity,
                account.radar_name,
                account.radar_persona,
                account.threshold_views,
                account.threshold_engagement_rate,
                account.average_views,
                account.raw_average_views,
                account.raw_threshold,
                account.source_row_number,
                account.data_quality_issue,
                int(account.enabled),
                account.fetch_interval_minutes,
                utc_now_iso(),
            ),
        )
        count += 1
    conn.commit()
    return count


def engagement_rate(item: ContentItem) -> float | None:
    if item.view_count is None or item.view_count <= 0:
        return None
    interactions = (item.like_count or 0) + (item.comment_count or 0) + (item.share_count or 0)
    return interactions / item.view_count


def qualification_status(account: sqlite3.Row, item: ContentItem) -> str:
    if item.view_count is None:
        return "metrics_pending"
    threshold_views = account["threshold_views"]
    if threshold_views is None:
        return "metrics_pending"
    if item.view_count < threshold_views:
        return "below_threshold"
    threshold_engagement_rate = account["threshold_engagement_rate"]
    rate = engagement_rate(item)
    if threshold_engagement_rate is not None and rate is None:
        return "metrics_pending"
    if threshold_engagement_rate is not None and rate < threshold_engagement_rate:
        return "below_threshold"
    return "qualified"


def save_fetch_result_with_ids(conn: sqlite3.Connection, result: FetchResult) -> list[int]:
    account = conn.execute("SELECT * FROM source_accounts WHERE id = ?", (result.account_id,)).fetchone()
    if account is None:
        raise ValueError(f"source account not found: {result.account_id}")

    fetched_at = utc_now_iso()
    content_ids: list[int] = []
    for item in result.items:
        rate = engagement_rate(item)
        status = qualification_status(account, item)
        conn.execute(
            """
            INSERT INTO source_contents (
                source_account_id, platform, provider, original_content_id, title, text, original_text, published_at,
                url, view_count, like_count, comment_count, share_count, media_type,
                language, media_assets_json, engagement_rate, qualification_status, fetched_at, raw_payload_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, original_content_id) DO UPDATE SET
                source_account_id = excluded.source_account_id,
                provider = excluded.provider,
                title = excluded.title,
                text = excluded.text,
                original_text = excluded.original_text,
                published_at = excluded.published_at,
                url = excluded.url,
                view_count = excluded.view_count,
                like_count = excluded.like_count,
                comment_count = excluded.comment_count,
                share_count = excluded.share_count,
                media_type = excluded.media_type,
                language = excluded.language,
                media_assets_json = excluded.media_assets_json,
                engagement_rate = excluded.engagement_rate,
                qualification_status = excluded.qualification_status,
                fetched_at = excluded.fetched_at,
                raw_payload_json = excluded.raw_payload_json,
                updated_at = excluded.updated_at
            """,
            (
                result.account_id,
                item.platform,
                item.raw_payload.get("source") if isinstance(item.raw_payload, dict) else None,
                item.original_content_id,
                item.title,
                item.text,
                item.text,
                item.published_at,
                item.url,
                item.view_count,
                item.like_count,
                item.comment_count,
                item.share_count,
                item.media_type,
                item.language,
                json.dumps(item.media_assets, ensure_ascii=False, sort_keys=True),
                rate,
                status,
                fetched_at,
                json.dumps(item.raw_payload, ensure_ascii=False, sort_keys=True),
                fetched_at,
            ),
        )
        row = conn.execute(
            "SELECT id FROM source_contents WHERE platform = ? AND original_content_id = ?",
            (item.platform, item.original_content_id),
        ).fetchone()
        if row is not None:
            content_ids.append(int(row["id"]))

    conn.execute(
        """
        UPDATE source_accounts
        SET last_seen_original_id = COALESCE(?, last_seen_original_id),
            pagination_cursor = COALESCE(?, pagination_cursor),
            last_success_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (result.last_seen_original_id, result.next_cursor, fetched_at, fetched_at, result.account_id),
    )
    conn.commit()
    return content_ids


def save_fetch_result(conn: sqlite3.Connection, result: FetchResult) -> int:
    return len(save_fetch_result_with_ids(conn, result))


def link_run_contents(conn: sqlite3.Connection, run_id: str | None, content_ids: Iterable[int]) -> None:
    if not run_id:
        return
    rows = [(run_id, int(content_id)) for content_id in content_ids]
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR IGNORE INTO crawl_run_contents (run_id, content_id)
        VALUES (?, ?)
        """,
        rows,
    )
    conn.commit()


def log_failure(
    conn: sqlite3.Connection,
    *,
    source_account_id: int | None,
    platform: str,
    error_type: str,
    error_message: str,
    status_code: int | None = None,
    raw_context: dict | None = None,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO crawl_failures (
            source_account_id, platform, error_type, error_message, status_code,
            occurred_at, raw_context_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_account_id,
            platform,
            error_type,
            error_message,
            status_code,
            now,
            json.dumps(raw_context or {}, ensure_ascii=False, sort_keys=True),
        ),
    )
    if source_account_id is not None:
        conn.execute(
            "UPDATE source_accounts SET last_failure_at = ?, updated_at = ? WHERE id = ?",
            (now, now, source_account_id),
        )
    conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [row_to_dict(row) for row in rows if row is not None]
