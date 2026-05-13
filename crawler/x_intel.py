from __future__ import annotations

import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from typing import Iterable

from .models import utc_now_iso


BESTBLOGS_OPML_URL = "https://raw.githubusercontent.com/ginobefun/BestBlogs/main/BestBlogs_RSS_Twitters.opml"
X_INTEL_CATEGORY = "AI情报源"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "RadarCrawler/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


@dataclass(frozen=True)
class XIntelAccount:
    display_name: str
    handle: str
    rss_url: str
    language: str | None = None


def strip_xgo_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(
        r"[\U0001F4AC\U0001F504\U00002764\U0001F493\U0001F440\U0001F4CA\u2764\u2605]\uFE0F?\s*\d+",
        "",
        text,
    )
    text = re.sub(r"⚡\s*Powered by xgo\.ing", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


def parse_xgo_metrics(text: str) -> dict[str, int | None]:
    html = unescape(text or "")
    labels = {
        "comment_count": r"(?:💬|&#x1f4ac;)\s*</span>\s*<span>\s*([0-9,]+)",
        "share_count": r"(?:🔄|&#x1f504;)\s*</span>\s*<span>\s*([0-9,]+)",
        "like_count": r"(?:❤️|❤|&#x2764;)\s*</span>\s*<span>\s*([0-9,]+)",
        "view_count": r"(?:👀|&#x1f440;)\s*</span>\s*<span>\s*([0-9,]+)",
    }
    values: dict[str, int | None] = {}
    for key, pattern in labels.items():
        match = re.search(pattern, html)
        values[key] = int(match.group(1).replace(",", "")) if match else None
    return values


def parse_bestblogs_opml(opml_text: str) -> list[XIntelAccount]:
    accounts: list[XIntelAccount] = []
    for line in opml_text.splitlines():
        match = re.search(r'text="([^"]+)"[^>]*xmlUrl="([^"]+)"', line)
        if not match:
            continue
        label = unescape(match.group(1))
        rss_url = unescape(match.group(2))
        handle_match = re.search(r"\(@([^()]+)\)", label)
        handle = handle_match.group(1) if handle_match else label.split("(@")[-1].rstrip(")")
        display_name = label.split("(@", 1)[0].strip() or handle
        accounts.append(XIntelAccount(display_name=display_name, handle=handle, rss_url=rss_url))
    return accounts


def fetch_bestblogs_accounts(opml_url: str = BESTBLOGS_OPML_URL) -> list[XIntelAccount]:
    return parse_bestblogs_opml(fetch_text(opml_url))


def upsert_x_intel_accounts(
    conn: sqlite3.Connection,
    accounts: Iterable[XIntelAccount],
    *,
    category: str = X_INTEL_CATEGORY,
    limit: int | None = None,
) -> int:
    now = utc_now_iso()
    count = 0
    for account in accounts:
        if limit is not None and count >= limit:
            break
        conn.execute(
            """
            INSERT INTO source_accounts (
                category, platform, account_name, account_handle, account_url,
                original_account, official_identity, radar_name, radar_persona,
                raw_average_views, raw_threshold, source_row_number,
                enabled, fetch_interval_minutes, updated_at
            )
            VALUES (?, 'x', ?, ?, ?, ?, ?, ?, ?, '', '', ?, 1, 240, ?)
            ON CONFLICT(platform, account_name) DO UPDATE SET
                category = excluded.category,
                account_handle = excluded.account_handle,
                account_url = excluded.account_url,
                original_account = excluded.original_account,
                official_identity = excluded.official_identity,
                radar_name = excluded.radar_name,
                radar_persona = excluded.radar_persona,
                enabled = 1,
                fetch_interval_minutes = excluded.fetch_interval_minutes,
                updated_at = excluded.updated_at
            """,
            (
                category,
                account.display_name,
                account.handle,
                account.rss_url,
                f"BestBlogs/X-{account.display_name}",
                account.handle,
                f"AI情报-{account.display_name}",
                "x-intel-monitor/rss",
                count + 1,
                now,
            ),
        )
        count += 1
    conn.commit()
    return count
