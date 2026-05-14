from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


PLATFORM_X = "x"
PLATFORM_YOUTUBE = "youtube"
PLATFORM_LINKEDIN = "linkedin"
PLATFORM_INSTAGRAM = "instagram"
PLATFORM_XHS = "xhs"
PLATFORM_WECHAT = "wechat"
PLATFORM_BILIBILI = "bilibili"
PLATFORM_DOUYIN = "douyin"
PLATFORM_WEIBO = "weibo"
PLATFORM_ZHIHU = "zhihu"
PLATFORM_GITHUB = "github"
PLATFORM_FEISHU = "feishu"
PLATFORM_KDOCS = "kdocs"
PLATFORM_YOUDAO = "youdao"
PLATFORM_RSS = "rss"
PLATFORM_TELEGRAM = "telegram"
PLATFORM_REDDIT = "reddit"
PLATFORM_HACKERNEWS = "hackernews"
PLATFORM_MEDIUM = "medium"
PLATFORM_LINUXDO = "linuxdo"
PLATFORM_IDCFLARE = "idcflare"
PLATFORM_XIAOYUZHOU = "xiaoyuzhou"
PLATFORM_XIMALAYA = "ximalaya"
PLATFORM_WEB = "web"

SUPPORTED_PLATFORMS = {
    PLATFORM_X,
    PLATFORM_YOUTUBE,
    PLATFORM_LINKEDIN,
    PLATFORM_INSTAGRAM,
    PLATFORM_XHS,
    PLATFORM_WECHAT,
    PLATFORM_BILIBILI,
    PLATFORM_DOUYIN,
    PLATFORM_WEIBO,
    PLATFORM_ZHIHU,
    PLATFORM_GITHUB,
    PLATFORM_FEISHU,
    PLATFORM_KDOCS,
    PLATFORM_YOUDAO,
    PLATFORM_RSS,
    PLATFORM_TELEGRAM,
    PLATFORM_REDDIT,
    PLATFORM_HACKERNEWS,
    PLATFORM_MEDIUM,
    PLATFORM_LINUXDO,
    PLATFORM_IDCFLARE,
    PLATFORM_XIAOYUZHOU,
    PLATFORM_XIMALAYA,
    PLATFORM_WEB,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SourceAccount:
    category: str
    platform: str
    account_name: str
    original_account: str
    official_identity: str
    radar_name: str
    radar_persona: str
    threshold_views: int | None
    threshold_engagement_rate: float | None
    average_views: int | None
    raw_average_views: str
    raw_threshold: str
    source_row_number: int
    data_quality_issue: str | None = None
    enabled: bool = True
    fetch_interval_minutes: int = 720


@dataclass(frozen=True)
class ContentItem:
    platform: str
    original_content_id: str
    title: str | None
    text: str | None
    published_at: str | None
    url: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None
    media_type: str | None
    language: str | None
    raw_payload: dict[str, Any]
    media_assets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FetchResult:
    account_id: int
    platform: str
    items: list[ContentItem]
    next_cursor: str | None = None
    last_seen_original_id: str | None = None
