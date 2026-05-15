from __future__ import annotations

from urllib.parse import urlparse


BEECLAW_PROVIDER_PREFIX = "beeclaw:"
BEEGRAB_PROVIDER_PREFIX = "beegrab:"
FEEDGRAB_BACKEND_PREFIX = "feedgrab:"
X_PUBLIC_PROVIDER = "beeclaw:x"
X_PROVIDER_ALIASES = {
    "xmcp",
    "beeclaw:x_mcp",
    "beegrab:x_mcp",
    "feedgrab:x_mcp",
    "beeclaw:x_api",
    "beegrab:x_api",
    "feedgrab:x_api",
    "beeclaw:x_twitterapi_io",
    "beegrab:x_twitterapi_io",
    "feedgrab:x_twitterapi_io",
    "twitterapi_io",
    "beeclaw:x_rss",
    "beegrab:x_rss",
    "feedgrab:x_rss",
    "xgo_rss",
    "x-rss",
}
X_BACKEND_ALIASES = {
    "xmcp": "x_mcp",
    "beeclaw:x_mcp": "x_mcp",
    "beegrab:x_mcp": "x_mcp",
    "feedgrab:x_mcp": "x_mcp",
    "beeclaw:x_api": "x_api",
    "beegrab:x_api": "x_api",
    "feedgrab:x_api": "x_api",
    "beeclaw:x_twitterapi_io": "twitterapi_io",
    "beegrab:x_twitterapi_io": "twitterapi_io",
    "feedgrab:x_twitterapi_io": "twitterapi_io",
    "twitterapi_io": "twitterapi_io",
    "beeclaw:x_rss": "x_rss",
    "beegrab:x_rss": "x_rss",
    "feedgrab:x_rss": "x_rss",
    "xgo_rss": "x_rss",
    "x-rss": "x_rss",
    "chrome-session": "browser_session",
    "browser-session": "browser_session",
    "x_browser_session": "browser_session",
    "cloud_browser_session": "cloud_browser_session",
    "headless_browser_session": "headless_browser_session",
    "local_browser_session": "browser_session",
}


def beeclaw_provider_name(provider: str | None) -> str | None:
    """Return the public Radar provider name for a backend provider id."""
    if not provider:
        return provider
    value = str(provider).strip()
    if value in X_PROVIDER_ALIASES:
        return X_PUBLIC_PROVIDER
    if value == "beegrab":
        return "beeclaw"
    if value == "feedgrab":
        return "beeclaw"
    if value.startswith(BEEGRAB_PROVIDER_PREFIX):
        return f"{BEECLAW_PROVIDER_PREFIX}{value[len(BEEGRAB_PROVIDER_PREFIX):]}"
    if value.startswith(FEEDGRAB_BACKEND_PREFIX):
        return f"{BEECLAW_PROVIDER_PREFIX}{value[len(FEEDGRAB_BACKEND_PREFIX):]}"
    return value


def normalize_public_provider_mode(provider: str | None) -> str | None:
    """Normalize current and legacy provider modes without collapsing X submodes."""
    if not provider:
        return provider
    value = str(provider).strip()
    if value == "beegrab" or value == "feedgrab":
        return "beeclaw"
    if value.startswith(BEEGRAB_PROVIDER_PREFIX):
        return f"{BEECLAW_PROVIDER_PREFIX}{value[len(BEEGRAB_PROVIDER_PREFIX):]}"
    if value.startswith(FEEDGRAB_BACKEND_PREFIX):
        return f"{BEECLAW_PROVIDER_PREFIX}{value[len(FEEDGRAB_BACKEND_PREFIX):]}"
    return value


def feedgrab_backend_name(provider: str | None) -> str | None:
    """Return the upstream feedgrab backend id for a public Beeclaw provider."""
    if not provider:
        return provider
    value = str(provider).strip()
    if value == "beeclaw":
        return "feedgrab"
    if value == "beegrab":
        return "feedgrab"
    if value.startswith(BEECLAW_PROVIDER_PREFIX):
        return f"{FEEDGRAB_BACKEND_PREFIX}{value[len(BEECLAW_PROVIDER_PREFIX):]}"
    if value.startswith(BEEGRAB_PROVIDER_PREFIX):
        return f"{FEEDGRAB_BACKEND_PREFIX}{value[len(BEEGRAB_PROVIDER_PREFIX):]}"
    return value


def beeclaw_execution_backend_name(provider: str | None) -> str | None:
    """Return the public execution backend id exposed to AI employees."""
    if not provider:
        return provider
    value = str(provider).strip()
    return X_BACKEND_ALIASES.get(value, beeclaw_provider_name(value))


# Legacy compatibility aliases. New code should import the Beeclaw names.
beegrab_provider_name = beeclaw_provider_name
beegrab_execution_backend_name = beeclaw_execution_backend_name


def public_raw_payload(raw_payload: dict | None) -> dict:
    """Normalize raw payload provider fields while preserving the real backend."""
    payload = dict(raw_payload or {})
    source = payload.get("source")
    public_source = beeclaw_provider_name(source)
    if public_source != source:
        payload["source"] = public_source
        if source:
            payload.setdefault("provider_backend", source)
    return payload


FEEDGRAB_URL_PLATFORM_SPECS: list[dict] = [
    {
        "platform": "xhs",
        "provider": "beeclaw:xhs",
        "priority": 78,
        "capabilities": ["url_read", "keyword_search", "user_notes", "media_metadata", "media_download"],
        "backends": ["xiaohongshu-mcp", "xhs-cli", "universal_reader"],
        "requires": [],
        "domains": ["xiaohongshu.com", "xhslink.com"],
        "aliases": ["xhs", "xiaohongshu", "小红书", "红书"],
    },
    {
        "platform": "wechat",
        "provider": "beeclaw:wechat",
        "priority": 72,
        "capabilities": ["url_read", "article_read", "metadata", "media_metadata"],
        "requires": [],
        "domains": ["mp.weixin.qq.com", "weixin.qq.com"],
        "aliases": ["wechat", "weixin", "mpweixin", "微信公众号", "公众号", "微信"],
    },
    {
        "platform": "youtube",
        "provider": "beeclaw:youtube",
        "priority": 80,
        "capabilities": ["url_read", "keyword_search", "video_search", "transcript", "media_metadata"],
        "backends": ["yt-dlp", "youtube_api", "rss"],
        "requires": [],
        "domains": ["youtube.com", "youtu.be"],
        "aliases": ["youtube", "yt", "油管"],
    },
    {
        "platform": "bilibili",
        "provider": "beeclaw:bilibili",
        "priority": 70,
        "capabilities": ["url_read", "video_metadata", "media_metadata"],
        "requires": [],
        "domains": ["bilibili.com", "b23.tv"],
        "aliases": ["bilibili", "b站", "哔哩哔哩"],
    },
    {
        "platform": "douyin",
        "provider": "beeclaw:douyin",
        "priority": 70,
        "capabilities": ["url_read", "video_metadata", "media_metadata"],
        "requires": [],
        "domains": ["douyin.com", "iesdouyin.com"],
        "aliases": ["douyin", "抖音"],
    },
    {
        "platform": "weibo",
        "provider": "beeclaw:weibo",
        "priority": 70,
        "capabilities": ["url_read", "post_metadata", "media_metadata"],
        "requires": [],
        "domains": ["weibo.com", "weibo.cn"],
        "aliases": ["weibo", "微博"],
    },
    {
        "platform": "zhihu",
        "provider": "beeclaw:zhihu",
        "priority": 70,
        "capabilities": ["url_read", "answer_read", "article_read", "metadata"],
        "requires": [],
        "domains": ["zhihu.com"],
        "aliases": ["zhihu", "知乎"],
    },
    {
        "platform": "github",
        "provider": "beeclaw:github",
        "priority": 70,
        "capabilities": ["url_read", "repo_read", "release_read", "metadata"],
        "backends": ["gh", "github_api", "universal_reader"],
        "requires": [],
        "domains": ["github.com", "gist.github.com"],
        "aliases": ["github", "gh"],
    },
    {
        "platform": "feishu",
        "provider": "beeclaw:feishu",
        "priority": 65,
        "capabilities": ["url_read", "document_read", "metadata"],
        "requires": ["public URL or authorized session for private docs"],
        "domains": ["feishu.cn", "larksuite.com"],
        "aliases": ["feishu", "lark", "飞书"],
    },
    {
        "platform": "kdocs",
        "provider": "beeclaw:kdocs",
        "priority": 65,
        "capabilities": ["url_read", "document_read", "metadata"],
        "requires": ["public URL or authorized session for private docs"],
        "domains": ["kdocs.cn", "kdocs.com"],
        "aliases": ["kdocs", "kingsoft", "金山文档"],
    },
    {
        "platform": "youdao",
        "provider": "beeclaw:youdao",
        "priority": 65,
        "capabilities": ["url_read", "note_read", "metadata"],
        "requires": ["public URL or authorized session for private notes"],
        "domains": ["note.youdao.com", "youdao.com"],
        "aliases": ["youdao", "有道", "有道云笔记"],
    },
    {
        "platform": "rss",
        "provider": "beeclaw:rss",
        "priority": 68,
        "capabilities": ["feed_read", "entries", "metadata"],
        "backends": ["rss_parser", "universal_reader"],
        "requires": [],
        "domains": [],
        "aliases": ["rss", "atom", "feed", "订阅源"],
    },
    {
        "platform": "telegram",
        "provider": "beeclaw:telegram",
        "priority": 66,
        "capabilities": ["url_read", "channel_post_read", "media_metadata"],
        "requires": ["public channel URL"],
        "domains": ["t.me", "telegram.me", "telegram.org"],
        "aliases": ["telegram", "tg", "电报"],
    },
    {
        "platform": "reddit",
        "provider": "beeclaw:reddit",
        "priority": 66,
        "capabilities": ["url_read", "keyword_search", "post_read", "comment_metadata"],
        "backends": ["reddit_public_search", "rdt-cli", "reddit_api", "universal_reader"],
        "requires": [],
        "domains": ["reddit.com", "redd.it"],
        "aliases": ["reddit"],
    },
    {
        "platform": "hackernews",
        "provider": "beeclaw:hackernews",
        "priority": 66,
        "capabilities": ["url_read", "item_read", "comment_metadata"],
        "requires": [],
        "domains": ["news.ycombinator.com"],
        "aliases": ["hackernews", "hacker news", "hn"],
    },
    {
        "platform": "medium",
        "provider": "beeclaw:medium",
        "priority": 66,
        "capabilities": ["url_read", "article_read", "metadata"],
        "requires": [],
        "domains": ["medium.com"],
        "aliases": ["medium"],
    },
    {
        "platform": "linuxdo",
        "provider": "beeclaw:linuxdo",
        "priority": 64,
        "capabilities": ["url_read", "topic_read", "metadata"],
        "requires": [],
        "domains": ["linux.do"],
        "aliases": ["linuxdo", "linux.do"],
    },
    {
        "platform": "idcflare",
        "provider": "beeclaw:idcflare",
        "priority": 64,
        "capabilities": ["url_read", "article_read", "metadata"],
        "requires": [],
        "domains": ["idcflare.com"],
        "aliases": ["idcflare"],
    },
    {
        "platform": "xiaoyuzhou",
        "provider": "beeclaw:xiaoyuzhou",
        "priority": 64,
        "capabilities": ["url_read", "episode_read", "audio_metadata"],
        "requires": [],
        "domains": ["xiaoyuzhoufm.com", "xiaoyuzhou.com"],
        "aliases": ["xiaoyuzhou", "小宇宙"],
    },
    {
        "platform": "ximalaya",
        "provider": "beeclaw:ximalaya",
        "priority": 64,
        "capabilities": ["url_read", "episode_read", "audio_metadata"],
        "requires": [],
        "domains": ["ximalaya.com", "xima.tv"],
        "aliases": ["ximalaya", "喜马拉雅"],
    },
    {
        "platform": "web",
        "provider": "beeclaw:web",
        "priority": 60,
        "capabilities": ["url_read", "markdown", "metadata"],
        "backends": ["Jina Reader", "agent-browser", "universal_reader"],
        "requires": [],
        "domains": [],
        "aliases": ["web", "url", "网页", "通用网页", "通用 web url"],
    },
]


SOURCE_PLATFORM_ALIASES = {
    "facebook": "facebook",
    "fb": "facebook",
    "instagram": "instagram",
    "ins": "instagram",
    "linkedin": "linkedin",
    "twitter": "x",
    "x": "x",
    "twitter_user_tweets": "x",
    "twitter_list_tweets": "x",
    "twitter_bookmarks": "x",
    "mpweixin": "wechat",
    "mpweixin_account": "wechat",
    "mpweixin_album": "wechat",
    "wechat_search": "wechat",
    "xhs_search": "xhs",
    "xhs_user_notes": "xhs",
    "xiaohongshu": "xhs",
    "youtube_search": "youtube",
    "feishu_wiki": "feishu",
    "browser": "web",
    "jina": "web",
    "article": "web",
    "url": "web",
}
for spec in FEEDGRAB_URL_PLATFORM_SPECS:
    platform = spec["platform"]
    SOURCE_PLATFORM_ALIASES[platform] = platform
    for alias in spec.get("aliases", []):
        SOURCE_PLATFORM_ALIASES[str(alias).lower()] = platform


def normalize_feedgrab_platform(value: str | None) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower().replace("-", "_")
    return SOURCE_PLATFORM_ALIASES.get(key)


def infer_feedgrab_platform_from_text(text: str) -> str | None:
    lower = text.lower()
    for spec in FEEDGRAB_URL_PLATFORM_SPECS:
        for alias in spec.get("aliases", []):
            raw = str(alias)
            if (raw.isascii() and raw.lower() in lower) or (not raw.isascii() and raw in text):
                return spec["platform"]
    return None


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _looks_like_feed_url(parsed) -> bool:
    path = (parsed.path or "").lower()
    if path.endswith((".rss", ".xml", ".atom")):
        return True
    parts = {part for part in path.split("/") if part}
    return bool(parts.intersection({"rss", "feed", "feeds", "atom"}))


def infer_feedgrab_platform_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for spec in FEEDGRAB_URL_PLATFORM_SPECS:
        for domain in spec.get("domains", []):
            if _host_matches(host, domain):
                return spec["platform"]
    if _looks_like_feed_url(parsed):
        return "rss"
    return "web"


def feedgrab_url_provider_catalog() -> list[dict]:
    items = []
    for spec in FEEDGRAB_URL_PLATFORM_SPECS:
        items.append(
            {
                "platform": spec["platform"],
                "provider": spec["provider"],
                "priority": spec["priority"],
                "capabilities": list(spec["capabilities"]),
                "backends": list(spec.get("backends", ["universal_reader"])),
                "requires": list(spec["requires"]),
            }
        )
    return items


def feedgrab_provider_for_platform(platform: str | None) -> str | None:
    normalized = normalize_feedgrab_platform(platform) or platform
    if not normalized:
        return None
    for spec in FEEDGRAB_URL_PLATFORM_SPECS:
        if spec["platform"] == normalized:
            return spec["provider"]
    return None
