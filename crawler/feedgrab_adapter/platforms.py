from __future__ import annotations

from urllib.parse import urlparse


FEEDGRAB_URL_PLATFORM_SPECS: list[dict] = [
    {
        "platform": "xhs",
        "provider": "feedgrab:xhs",
        "priority": 78,
        "capabilities": ["url_read", "keyword_search", "user_notes", "media_metadata", "media_download"],
        "requires": [],
        "domains": ["xiaohongshu.com", "xhslink.com"],
        "aliases": ["xhs", "xiaohongshu", "小红书", "红书"],
    },
    {
        "platform": "wechat",
        "provider": "feedgrab:wechat",
        "priority": 72,
        "capabilities": ["url_read", "article_read", "metadata", "media_metadata"],
        "requires": [],
        "domains": ["mp.weixin.qq.com", "weixin.qq.com"],
        "aliases": ["wechat", "weixin", "mpweixin", "微信公众号", "公众号", "微信"],
    },
    {
        "platform": "youtube",
        "provider": "feedgrab:youtube",
        "priority": 80,
        "capabilities": ["url_read", "search", "transcript", "media_metadata"],
        "requires": [],
        "domains": ["youtube.com", "youtu.be"],
        "aliases": ["youtube", "yt", "油管"],
    },
    {
        "platform": "bilibili",
        "provider": "feedgrab:bilibili",
        "priority": 70,
        "capabilities": ["url_read", "video_metadata", "media_metadata"],
        "requires": [],
        "domains": ["bilibili.com", "b23.tv"],
        "aliases": ["bilibili", "b站", "哔哩哔哩"],
    },
    {
        "platform": "douyin",
        "provider": "feedgrab:douyin",
        "priority": 70,
        "capabilities": ["url_read", "video_metadata", "media_metadata"],
        "requires": [],
        "domains": ["douyin.com", "iesdouyin.com"],
        "aliases": ["douyin", "抖音"],
    },
    {
        "platform": "weibo",
        "provider": "feedgrab:weibo",
        "priority": 70,
        "capabilities": ["url_read", "post_metadata", "media_metadata"],
        "requires": [],
        "domains": ["weibo.com", "weibo.cn"],
        "aliases": ["weibo", "微博"],
    },
    {
        "platform": "zhihu",
        "provider": "feedgrab:zhihu",
        "priority": 70,
        "capabilities": ["url_read", "answer_read", "article_read", "metadata"],
        "requires": [],
        "domains": ["zhihu.com"],
        "aliases": ["zhihu", "知乎"],
    },
    {
        "platform": "github",
        "provider": "feedgrab:github",
        "priority": 70,
        "capabilities": ["url_read", "repo_read", "release_read", "metadata"],
        "requires": [],
        "domains": ["github.com", "gist.github.com"],
        "aliases": ["github", "gh"],
    },
    {
        "platform": "feishu",
        "provider": "feedgrab:feishu",
        "priority": 65,
        "capabilities": ["url_read", "document_read", "metadata"],
        "requires": ["public URL or authorized session for private docs"],
        "domains": ["feishu.cn", "larksuite.com"],
        "aliases": ["feishu", "lark", "飞书"],
    },
    {
        "platform": "kdocs",
        "provider": "feedgrab:kdocs",
        "priority": 65,
        "capabilities": ["url_read", "document_read", "metadata"],
        "requires": ["public URL or authorized session for private docs"],
        "domains": ["kdocs.cn", "kdocs.com"],
        "aliases": ["kdocs", "kingsoft", "金山文档"],
    },
    {
        "platform": "youdao",
        "provider": "feedgrab:youdao",
        "priority": 65,
        "capabilities": ["url_read", "note_read", "metadata"],
        "requires": ["public URL or authorized session for private notes"],
        "domains": ["note.youdao.com", "youdao.com"],
        "aliases": ["youdao", "有道", "有道云笔记"],
    },
    {
        "platform": "rss",
        "provider": "feedgrab:rss",
        "priority": 68,
        "capabilities": ["feed_read", "entries", "metadata"],
        "requires": [],
        "domains": [],
        "aliases": ["rss", "atom", "feed", "订阅源"],
    },
    {
        "platform": "telegram",
        "provider": "feedgrab:telegram",
        "priority": 66,
        "capabilities": ["url_read", "channel_post_read", "media_metadata"],
        "requires": ["public channel URL"],
        "domains": ["t.me", "telegram.me", "telegram.org"],
        "aliases": ["telegram", "tg", "电报"],
    },
    {
        "platform": "reddit",
        "provider": "feedgrab:reddit",
        "priority": 66,
        "capabilities": ["url_read", "post_read", "comment_metadata"],
        "requires": [],
        "domains": ["reddit.com", "redd.it"],
        "aliases": ["reddit"],
    },
    {
        "platform": "hackernews",
        "provider": "feedgrab:hackernews",
        "priority": 66,
        "capabilities": ["url_read", "item_read", "comment_metadata"],
        "requires": [],
        "domains": ["news.ycombinator.com"],
        "aliases": ["hackernews", "hacker news", "hn"],
    },
    {
        "platform": "medium",
        "provider": "feedgrab:medium",
        "priority": 66,
        "capabilities": ["url_read", "article_read", "metadata"],
        "requires": [],
        "domains": ["medium.com"],
        "aliases": ["medium"],
    },
    {
        "platform": "linuxdo",
        "provider": "feedgrab:linuxdo",
        "priority": 64,
        "capabilities": ["url_read", "topic_read", "metadata"],
        "requires": [],
        "domains": ["linux.do"],
        "aliases": ["linuxdo", "linux.do"],
    },
    {
        "platform": "idcflare",
        "provider": "feedgrab:idcflare",
        "priority": 64,
        "capabilities": ["url_read", "article_read", "metadata"],
        "requires": [],
        "domains": ["idcflare.com"],
        "aliases": ["idcflare"],
    },
    {
        "platform": "xiaoyuzhou",
        "provider": "feedgrab:xiaoyuzhou",
        "priority": 64,
        "capabilities": ["url_read", "episode_read", "audio_metadata"],
        "requires": [],
        "domains": ["xiaoyuzhoufm.com", "xiaoyuzhou.com"],
        "aliases": ["xiaoyuzhou", "小宇宙"],
    },
    {
        "platform": "ximalaya",
        "provider": "feedgrab:ximalaya",
        "priority": 64,
        "capabilities": ["url_read", "episode_read", "audio_metadata"],
        "requires": [],
        "domains": ["ximalaya.com", "xima.tv"],
        "aliases": ["ximalaya", "喜马拉雅"],
    },
    {
        "platform": "web",
        "provider": "feedgrab:universal_reader",
        "priority": 60,
        "capabilities": ["url_read", "markdown", "metadata"],
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
