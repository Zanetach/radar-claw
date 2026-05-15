from __future__ import annotations

import json
import os
import asyncio
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Protocol

from .models import (
    ContentItem,
    FetchResult,
    PLATFORM_BILIBILI,
    PLATFORM_DOUYIN,
    PLATFORM_FEISHU,
    PLATFORM_GITHUB,
    PLATFORM_HACKERNEWS,
    PLATFORM_IDCFLARE,
    PLATFORM_INSTAGRAM,
    PLATFORM_KDOCS,
    PLATFORM_LINKEDIN,
    PLATFORM_LINUXDO,
    PLATFORM_MEDIUM,
    PLATFORM_REDDIT,
    PLATFORM_RSS,
    PLATFORM_TELEGRAM,
    PLATFORM_WEB,
    PLATFORM_WECHAT,
    PLATFORM_WEIBO,
    PLATFORM_X,
    PLATFORM_XHS,
    PLATFORM_XIAOYUZHOU,
    PLATFORM_XIMALAYA,
    PLATFORM_YOUTUBE,
    PLATFORM_YOUDAO,
    PLATFORM_ZHIHU,
)
from .beeclaw_adapter import read_url, unified_content_to_item
from .beeclaw_adapter.platforms import beeclaw_provider_name, feedgrab_provider_for_platform
from .platform_mcp_gateway import PlatformMcpGatewayError, call_platform_mcp_tool, platform_gateway_enabled
from .x_intel import fetch_bestblogs_accounts, parse_xgo_metrics, strip_xgo_html


MODE_AUTO = "auto"
MODE_API = "api"
MODE_NO_TOKEN = "no-token"
MODE_XMCP = "xmcp"
MODE_FEEDGRAB_X = "beeclaw:x"
MODE_FEEDGRAB_XMCP = "beeclaw:x_mcp"
MODE_FEEDGRAB_X_TWITTERAPI_IO = "beeclaw:x_twitterapi_io"
MODE_FEEDGRAB_X_RSS = "beeclaw:x_rss"
MODE_FEEDGRAB = "beeclaw"
MODE_X_RSS = "x-rss"
MODE_BROWSER_SESSION = "browser-session"
MODE_CHROME_SESSION = "chrome-session"

SUPPORTED_PROVIDER_MODES = (
    MODE_AUTO,
    MODE_NO_TOKEN,
    MODE_API,
    MODE_XMCP,
    MODE_FEEDGRAB_X,
    MODE_FEEDGRAB_XMCP,
    MODE_FEEDGRAB_X_TWITTERAPI_IO,
    MODE_FEEDGRAB_X_RSS,
    MODE_FEEDGRAB,
    MODE_CHROME_SESSION,
    MODE_BROWSER_SESSION,
    MODE_X_RSS,
)

AUTO_RECOVERABLE_ERRORS = {
    "missing_credentials",
    "missing_dependency",
    "credits_depleted",
    "xmcp_error",
    "platform_mcp_gateway_disabled",
    "platform_mcp_gateway_unavailable",
    "platform_mcp_gateway_http_error",
    "platform_mcp_gateway_bad_response",
    "platform_mcp_gateway_auth_failed",
    "backend_mcp_error",
    "webbridge_unavailable",
    "not_logged_in",
    "captcha_required",
    "no_token_unavailable",
    "missing_x_rss_url",
    "missing_account_identifier",
    "http_error",
}

_BESTBLOGS_XGO_CACHE: dict[str, str] | None = None

X_PUBLIC_PROVIDER = "beeclaw:x"
X_BACKEND_BY_MODE = {
    MODE_FEEDGRAB_X: "auto",
    MODE_FEEDGRAB_XMCP: "x_mcp",
    MODE_XMCP: "x_mcp",
    MODE_API: "x_api",
    MODE_FEEDGRAB_X_TWITTERAPI_IO: "twitterapi_io",
    MODE_FEEDGRAB_X_RSS: "x_rss",
    MODE_NO_TOKEN: "x_rss",
    MODE_X_RSS: "x_rss",
    MODE_BROWSER_SESSION: "browser_session",
    MODE_CHROME_SESSION: "browser_session",
}


def x_backend_for_mode(mode: str) -> str:
    return X_BACKEND_BY_MODE.get(mode, mode)


def x_backend_selection_reason(backend: str) -> str:
    if backend == "x_mcp":
        return "X 自动模式优先使用官方 MCP backend，适合指标、媒体和结构化数据。"
    if backend == "x_api":
        return "X MCP 不可用，X_BEARER_TOKEN/API backend 可用，因此选择官方 API backend。"
    if backend == "twitterapi_io":
        return "X MCP/API 不可用，TWITTERAPI_IO_KEY 可用，因此选择 TwitterAPI.io 第三方只读 backend。"
    if backend == "x_rss":
        return "X MCP/API 不可用，降级到免费 RSS；指标和视频可能不完整。"
    if backend == "browser_session":
        return "官方/API/RSS backend 未能返回内容，继续使用已登录浏览器会话 backend 获取可见内容。"
    if backend == "twitter-cli":
        return "显式允许 twitter-cli 调试 backend，因此选择本地 CLI。"
    return f"选择 {backend} backend。"


def x_backend_data_completeness(backend: str) -> dict[str, bool]:
    if backend == "x_rss":
        return {"metrics_complete": False, "media_complete": False}
    if backend == "browser_session":
        return {"metrics_complete": False, "media_complete": False}
    if backend == "twitterapi_io":
        return {"metrics_complete": True, "media_complete": False}
    return {"metrics_complete": True, "media_complete": True}


def annotate_x_fetch_result(
    result: FetchResult,
    *,
    backend: str,
    backend_attempts: list[dict[str, Any]] | None = None,
    selection_reason: str | None = None,
) -> FetchResult:
    items = []
    for item in result.items:
        raw_payload = dict(item.raw_payload or {})
        previous_source = raw_payload.get("source")
        if previous_source and previous_source != X_PUBLIC_PROVIDER:
            raw_payload.setdefault("provider_source", previous_source)
        raw_payload["source"] = X_PUBLIC_PROVIDER
        raw_payload["provider_backend"] = backend
        raw_payload.update(x_backend_data_completeness(backend))
        if backend_attempts:
            raw_payload["backend_attempts"] = backend_attempts
        if selection_reason:
            raw_payload["selection_reason"] = selection_reason
        items.append(replace(item, raw_payload=raw_payload))
    return replace(result, items=items)


class ProviderError(Exception):
    def __init__(self, message: str, *, error_type: str = "provider_error", status_code: int | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


class Provider(Protocol):
    platform: str

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        ...


def normalize_provider_mode(mode: str | None) -> str:
    value = (mode or MODE_AUTO).strip().lower()
    aliases = {
        "chrome": MODE_CHROME_SESSION,
        MODE_CHROME_SESSION: MODE_CHROME_SESSION,
        "browser": MODE_BROWSER_SESSION,
        MODE_BROWSER_SESSION: MODE_BROWSER_SESSION,
        "mcp": MODE_XMCP,
        "x-mcp": MODE_XMCP,
        "x_mcp": MODE_XMCP,
        "beeclaw": MODE_FEEDGRAB,
        "beeclaw:x": MODE_FEEDGRAB_X,
        "beegrab": MODE_FEEDGRAB,
        "beegrab:x": MODE_FEEDGRAB_X,
        "beeclaw:xapi": MODE_API,
        "beeclaw:x-api": MODE_API,
        "beeclaw:x_api": MODE_API,
        "beegrab:xapi": MODE_API,
        "beegrab:x-api": MODE_API,
        "beegrab:x_api": MODE_API,
        "feedgrab:x": MODE_FEEDGRAB_X,
        "feedgrab:xapi": MODE_API,
        "feedgrab:x-api": MODE_API,
        "feedgrab:x_api": MODE_API,
        "beeclaw:xmcp": MODE_FEEDGRAB_XMCP,
        "beeclaw:x-mcp": MODE_FEEDGRAB_XMCP,
        "beeclaw:x_mcp": MODE_FEEDGRAB_XMCP,
        "beeclaw:twitterapi": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beeclaw:twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beeclaw:x-twitterapi-io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beeclaw:x_twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "twitterapi.io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beegrab:xmcp": MODE_FEEDGRAB_XMCP,
        "beegrab:x-mcp": MODE_FEEDGRAB_XMCP,
        "beegrab:x_mcp": MODE_FEEDGRAB_XMCP,
        "beegrab:twitterapi": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beegrab:twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beegrab:x-twitterapi-io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beegrab:x_twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "beeclaw:xrss": MODE_FEEDGRAB_X_RSS,
        "beeclaw:x-rss": MODE_FEEDGRAB_X_RSS,
        "beeclaw:x_rss": MODE_FEEDGRAB_X_RSS,
        "beegrab:xrss": MODE_FEEDGRAB_X_RSS,
        "beegrab:x-rss": MODE_FEEDGRAB_X_RSS,
        "beegrab:x_rss": MODE_FEEDGRAB_X_RSS,
        "feedgrab": MODE_FEEDGRAB,
        "feedgrab:twitter": MODE_FEEDGRAB_X,
        "feedgrab:xmcp": MODE_FEEDGRAB_XMCP,
        "feedgrab:x-mcp": MODE_FEEDGRAB_XMCP,
        "feedgrab:x_mcp": MODE_FEEDGRAB_XMCP,
        "feedgrab:twitterapi": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "feedgrab:twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "feedgrab:x-twitterapi-io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "feedgrab:x_twitterapi_io": MODE_FEEDGRAB_X_TWITTERAPI_IO,
        "feedgrab:xrss": MODE_FEEDGRAB_X_RSS,
        "feedgrab:x-rss": MODE_FEEDGRAB_X_RSS,
        "feedgrab:x_rss": MODE_FEEDGRAB_X_RSS,
        "rss": MODE_X_RSS,
    }
    return aliases.get(value, value)


def normalize_x_handle(value: str) -> str:
    handle = (value or "").strip()
    match = re.search(r"(?:x\.com|twitter\.com)/([^/?#]+)", handle)
    if match:
        handle = match.group(1)
    return handle.strip().lstrip("@").split("/")[0]


def resolve_bestblogs_xgo_url(handle: str) -> str | None:
    global _BESTBLOGS_XGO_CACHE
    normalized = normalize_x_handle(handle).lower()
    if not normalized:
        return None
    if _BESTBLOGS_XGO_CACHE is None:
        _BESTBLOGS_XGO_CACHE = {
            account.handle.lower(): account.rss_url
            for account in fetch_bestblogs_accounts()
            if account.handle and account.rss_url
        }
    return _BESTBLOGS_XGO_CACHE.get(normalized)


def http_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ProviderError(detail or exc.reason, error_type="http_error", status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc.reason), error_type="network_error") from exc


def http_post_json(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ProviderError(detail or exc.reason, error_type="webbridge_http_error", status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc.reason), error_type="webbridge_unavailable") from exc


def http_text(url: str, *, params: dict[str, Any] | None = None) -> str:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "RadarCrawler/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ProviderError(detail or exc.reason, error_type="http_error", status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc.reason), error_type="network_error") from exc


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ProviderError(f"missing environment variable: {name}", error_type="missing_credentials")
    return value


def mcp_payload_from_result(result: Any) -> dict[str, Any]:
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if is_error:
            raise ProviderError(json.dumps(structured, ensure_ascii=False), error_type="xmcp_error")
        return structured
    if isinstance(result, dict):
        if result.get("isError") or result.get("is_error"):
            raise ProviderError(json.dumps(result, ensure_ascii=False), error_type="xmcp_error")
        return result
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            if is_error:
                lowered = text.lower()
                if "creditsdepleted" in lowered or "payment required" in lowered or "http error 402" in lowered:
                    raise ProviderError(text, error_type="credits_depleted", status_code=402)
                raise ProviderError(text, error_type="xmcp_error")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return {"result": result}


def unwrap_mcp_exception(exc: BaseException) -> BaseException:
    nested = getattr(exc, "exceptions", None)
    if nested:
        return unwrap_mcp_exception(nested[0])
    return exc


async def _mcp_call_tool_async(server_url: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        import httpx
    except ImportError as exc:
        raise ProviderError(
            "XMCP mode requires the Python MCP SDK. Install with: python3 -m pip install mcp",
            error_type="missing_dependency",
        ) from exc

    def local_httpx_client_factory(headers=None, timeout=None, auth=None):
        kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "trust_env": False,
            "timeout": timeout or httpx.Timeout(30, read=30),
        }
        if headers is not None:
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    parsed = urllib.parse.urlparse(server_url)
    client_factory = local_httpx_client_factory if parsed.hostname in {"127.0.0.1", "localhost", "::1"} else None
    client_kwargs = {
        "timeout": 30,
        "sse_read_timeout": 30,
    }
    if client_factory is not None:
        client_kwargs["httpx_client_factory"] = client_factory
    async with streamablehttp_client(server_url, **client_kwargs) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return mcp_payload_from_result(result)


def mcp_call_tool(server_url: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return asyncio.run(_mcp_call_tool_async(server_url, tool_name, arguments))
    except ProviderError:
        raise
    except Exception as exc:
        root = unwrap_mcp_exception(exc)
        if isinstance(root, ProviderError):
            raise root
        text = str(root)
        lowered = text.lower()
        if "creditsdepleted" in lowered or "payment required" in lowered or "http error 402" in lowered:
            raise ProviderError(text, error_type="credits_depleted", status_code=402) from exc
        raise ProviderError(text or str(exc), error_type="xmcp_error") from exc


def backend_mcp_call_tool(
    *,
    integration: str,
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    trace_id: str | None = None,
) -> dict[str, Any]:
    if platform_gateway_enabled():
        try:
            return call_platform_mcp_tool(
                integration=integration,
                tool=tool_name,
                arguments=arguments,
                trace_id=trace_id,
            )
        except PlatformMcpGatewayError as exc:
            raise ProviderError(str(exc), error_type=exc.error_type, status_code=exc.status_code) from exc
    return mcp_call_tool(server_url, tool_name, arguments)


def int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def x_username_from_status_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"x.com", "twitter.com"} and not host.endswith(".x.com") and not host.endswith(".twitter.com"):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[1] == "status":
        return parts[0].lstrip("@")
    return None


def iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def youtube_channel_id(account: dict[str, Any]) -> str | None:
    handle = account.get("account_handle")
    if handle:
        handle_text = str(handle).strip()
        if handle_text.startswith("UC"):
            return handle_text
        if handle_text.startswith("@"):
            return resolve_youtube_handle_to_channel_id(handle_text)
    account_url = account.get("account_url") or ""
    match = re_search_youtube_channel(account_url)
    if match:
        return match
    url_path = urllib.parse.urlparse(account_url or "").path
    parts = [part for part in url_path.split("/") if part]
    if parts and parts[0].startswith("@"):
        return resolve_youtube_handle_to_channel_id(parts[0])
    return None


def re_search_youtube_channel(value: str) -> str | None:
    match = urllib.parse.urlparse(value or "")
    path = match.path or ""
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "channel":
        return parts[1]
    return None


def resolve_youtube_handle_to_channel_id(handle: str) -> str | None:
    url = f"https://www.youtube.com/{urllib.parse.quote(handle.strip())}"
    html = http_text(url)
    markers = [
        r'"channelId":"',
        r'"externalId":"',
        r'<meta itemprop="channelId" content="',
    ]
    for marker in markers:
        start = html.find(marker)
        if start >= 0:
            start += len(marker)
            end = html.find('"', start)
            if end > start:
                value = html[start:end]
                if value.startswith("UC"):
                    return value
    return None


def stable_content_id(prefix: str, value: str) -> str:
    return f"{prefix}-{sha256(value.encode('utf-8')).hexdigest()[:20]}"


def compact_media_asset(asset: dict[str, Any]) -> dict[str, Any] | None:
    url = asset.get("url") or asset.get("media_url") or asset.get("download_url") or asset.get("thumbnail_url") or asset.get("preview_image_url")
    if not url:
        return None
    clean = {
        "type": asset.get("type") or asset.get("media_type") or asset.get("kind") or "media",
        "url": asset.get("url") or asset.get("media_url") or asset.get("download_url") or asset.get("preview_image_url") or asset.get("thumbnail_url"),
    }
    if asset.get("download_url"):
        clean["download_url"] = asset.get("download_url")
    if asset.get("thumbnail_url") or asset.get("preview_image_url"):
        clean["thumbnail_url"] = asset.get("thumbnail_url") or asset.get("preview_image_url")
    if asset.get("alt_text"):
        clean["alt_text"] = asset.get("alt_text")
    if asset.get("width"):
        clean["width"] = asset.get("width")
    if asset.get("height"):
        clean["height"] = asset.get("height")
    return clean


def best_x_video_variant(media: dict[str, Any]) -> str | None:
    variants = media.get("variants") or []
    candidates = []
    for variant in variants:
        url = variant.get("url")
        if not url:
            continue
        content_type = str(variant.get("content_type") or "")
        if "mp4" not in content_type and ".mp4" not in url:
            continue
        candidates.append((int_or_none(variant.get("bit_rate")) or 0, url))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def media_assets_from_x_payload(tweet: dict[str, Any], media_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    assets = []
    for key in tweet.get("attachments", {}).get("media_keys", []) or []:
        media = media_by_key.get(key)
        if not media:
            continue
        asset = compact_media_asset(
            {
                "type": media.get("type"),
                "url": media.get("url") or media.get("preview_image_url"),
                "download_url": media.get("url") or best_x_video_variant(media),
                "thumbnail_url": media.get("preview_image_url") or media.get("url"),
                "alt_text": media.get("alt_text"),
                "width": media.get("width"),
                "height": media.get("height"),
            }
        )
        if asset:
            assets.append(asset)
    return assets


def media_type_from_assets(default: str, assets: list[dict[str, Any]]) -> str:
    if not assets:
        return default
    asset_types = {str(asset.get("type") or "").lower() for asset in assets}
    if "video" in asset_types or "animated_gif" in asset_types:
        return "video"
    if "photo" in asset_types or "image" in asset_types:
        return "image"
    return default


def webbridge_status(base_url: str | None = None) -> dict[str, Any]:
    url = f"{base_url or os.getenv('WEBBRIDGE_URL', 'http://127.0.0.1:10086')}/status"
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
            payload.setdefault("reachable", True)
            return payload
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


class NoTokenUnsupportedProvider:
    def __init__(self, platform: str) -> None:
        self.platform = platform

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        raise ProviderError(
            f"{self.platform} has no stable official no-token metadata feed; use --mode api with credentials or manual import",
            error_type="no_token_unavailable",
        )


class XRssProvider:
    platform = PLATFORM_X
    source_name = X_PUBLIC_PROVIDER
    backend_name: str | None = "x_rss"

    def account_handle(self, account: dict[str, Any]) -> str:
        return normalize_x_handle(
            account.get("account_handle")
            or account.get("account_url")
            or account.get("account_name")
            or ""
        )

    def rss_urls_for_account(self, account: dict[str, Any]) -> list[str]:
        rss_url = (account.get("account_url") or "").strip()
        if "xgo.ing/rss" in rss_url:
            return [rss_url]
        handle = self.account_handle(account)
        if not handle:
            raise ProviderError(
                "X RSS mode requires an X handle, X profile URL, or xgo.ing RSS URL.",
                error_type="missing_account_identifier",
            )
        return [f"https://api.xgo.ing/rss/user/{urllib.parse.quote(handle)}"]

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        handle = self.account_handle(account)
        rss_urls = self.rss_urls_for_account(account)
        last_error: ProviderError | None = None
        xml_text = ""
        rss_url = rss_urls[0]
        for candidate in rss_urls:
            try:
                rss_url = candidate
                xml_text = http_text(candidate)
                break
            except ProviderError as exc:
                last_error = exc
                if exc.error_type != "http_error" or exc.status_code != 404:
                    raise
                bestblogs_url = resolve_bestblogs_xgo_url(handle)
                if bestblogs_url and bestblogs_url not in rss_urls:
                    rss_urls.append(bestblogs_url)
        else:
            if last_error:
                raise last_error
            raise ProviderError("unable to resolve X RSS URL", error_type="missing_x_rss_url")
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            raise ProviderError("invalid xgo RSS feed", error_type="invalid_feed")

        handle = handle or (account.get("account_handle") or account.get("account_name") or "").strip().lstrip("@")
        items = []
        for entry in channel.findall("item")[:max_results]:
            link = entry.findtext("link") or ""
            guid = entry.findtext("guid") or ""
            id_match = None
            for candidate in (guid, link):
                id_match = id_match or re.search(r"/status/([0-9]+)", candidate)
                id_match = id_match or re.search(r"^([0-9]{8,})$", candidate.strip())
            original_id = id_match.group(1) if id_match else stable_content_id("x-rss", link or guid or entry.findtext("title") or "")
            description = entry.findtext("description") or ""
            metrics = parse_xgo_metrics(description)
            text = strip_xgo_html(description) or entry.findtext("title")
            text = re.sub(r"Your browser does not support the video tag\.", "", text, flags=re.IGNORECASE)
            text = re.sub(r"🔗\s*View on Twitter", "", text, flags=re.IGNORECASE).strip()
            media_assets = []
            for url in sorted(set(re.findall(r"https://pbs\.twimg\.com/[^\"'&<>\s]+", description))):
                media_assets.append({"type": "image", "url": unescape_url(url), "thumbnail_url": unescape_url(url)})
            for url in sorted(set(re.findall(r"https://video\.twimg\.com/[^\"'&<>\s]+", description))):
                media_assets.append({"type": "video", "url": unescape_url(url), "download_url": unescape_url(url)})
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=str(original_id),
                    title=entry.findtext("title"),
                    text=text,
                    published_at=entry.findtext("pubDate") or entry.findtext("{http://purl.org/dc/elements/1.1/}date"),
                    url=link or (f"https://x.com/{handle}/status/{original_id}" if handle else None),
                    view_count=metrics.get("view_count"),
                    like_count=metrics.get("like_count"),
                    comment_count=metrics.get("comment_count"),
                    share_count=metrics.get("share_count"),
                    media_type=media_type_from_assets("post", media_assets),
                    language=None,
                    raw_payload={
                        "source": self.source_name,
                        **({"provider_backend": self.backend_name} if self.backend_name else {}),
                        "rss_backend": "xgo_rss",
                        "rss_url": rss_url,
                        "guid": guid,
                        "raw_description": description,
                    },
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            last_seen_original_id=items[0].original_content_id if items else None,
        )


class BeeclawXRssProvider(XRssProvider):
    source_name = X_PUBLIC_PROVIDER
    backend_name = "x_rss"


def unescape_url(value: str) -> str:
    return urllib.parse.unquote(value.replace("&amp;", "&"))


class WebBridgeClient:
    def __init__(self, *, session: str = "radar-x", base_url: str | None = None) -> None:
        self.session = session
        self.base_url = (base_url or os.getenv("WEBBRIDGE_URL") or "http://127.0.0.1:10086").rstrip("/")

    def command(self, action: str, args: dict[str, Any] | None = None, *, timeout_seconds: int = 90) -> Any:
        payload = {
            "action": action,
            "session": self.session,
            "args": args or {},
        }
        result = http_post_json(f"{self.base_url}/command", payload=payload, timeout_seconds=timeout_seconds)
        if not result.get("ok"):
            error = result.get("error") or {}
            raise ProviderError(
                error.get("message") or "webbridge command failed",
                error_type=error.get("code") or "webbridge_command_failed",
            )
        return result.get("data")

    def navigate(self, url: str) -> None:
        self.command("navigate", {"url": url, "newTab": True})

    def evaluate_json(self, code: str) -> Any:
        raw = self.command("evaluate", {"code": code})
        if isinstance(raw, dict) and raw.get("type") == "string":
            return json.loads(raw.get("value") or "null")
        if isinstance(raw, str):
            return json.loads(raw)
        return raw


class XBrowserSessionProvider:
    platform = PLATFORM_X
    source_name = X_PUBLIC_PROVIDER
    backend_name = "browser_session"

    extract_js = r"""
(async () => {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const parseMetric = value => {
    if (!value) return null;
    const text = String(value).replace(/,/g, '').trim();
    const match = text.match(/([0-9]+(?:\.[0-9]+)?)\s*([KMB万亿])?/i);
    if (!match) return null;
    const number = Number(match[1]);
    const unit = (match[2] || '').toLowerCase();
    if (unit === 'k') return Math.round(number * 1000);
    if (unit === 'm') return Math.round(number * 1000000);
    if (unit === 'b') return Math.round(number * 1000000000);
    if (unit === '万') return Math.round(number * 10000);
    if (unit === '亿') return Math.round(number * 100000000);
    return Math.round(number);
  };
  const getMetric = (article, testId) => {
    const element = article.querySelector(`[data-testid="${testId}"]`);
    return parseMetric(element?.getAttribute('aria-label') || element?.innerText || '');
  };
  const mediaFromArticle = article => {
    const assets = [];
    const seen = new Set();
    for (const img of Array.from(article.querySelectorAll('img[src]'))) {
      const src = img.src;
      if (!src || seen.has(src)) continue;
      if (!/pbs\.twimg\.com|video_thumb|ext_tw_video_thumb/.test(src)) continue;
      seen.add(src);
      assets.push({
        type: /video_thumb|ext_tw_video_thumb/.test(src) ? 'video' : 'image',
        url: src,
        thumbnail_url: src,
        alt_text: img.alt || null,
        width: img.naturalWidth || null,
        height: img.naturalHeight || null
      });
    }
    for (const video of Array.from(article.querySelectorAll('video'))) {
      const src = video.currentSrc || video.src || video.poster;
      if (!src || seen.has(src)) continue;
      seen.add(src);
      assets.push({ type: 'video', url: src, thumbnail_url: video.poster || src });
    }
    return assets;
  };
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    if (document.querySelector('article[data-testid="tweet"]')) break;
    if (location.pathname.includes('/login') || document.querySelector('input[name="text"]')) break;
    await sleep(250);
  }
  if (!document.querySelector('article[data-testid="tweet"]')) {
    window.scrollTo(0, 800);
    await sleep(1200);
  }
  const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
  const items = [];
  const seen = new Set();
  for (const article of articles) {
    const link = Array.from(article.querySelectorAll('a[href]'))
      .map(a => a.href)
      .find(href => /\/status\/[0-9]+/.test(href));
    if (!link || seen.has(link)) continue;
    seen.add(link);
    const idMatch = link.match(/\/status\/([0-9]+)/);
    const text = article.querySelector('[data-testid="tweetText"]')?.innerText || article.innerText || '';
    const publishedAt = article.querySelector('time')?.getAttribute('datetime') || null;
    items.push({
      id: idMatch ? idMatch[1] : link,
      text,
      published_at: publishedAt,
      url: link,
      reply_count: getMetric(article, 'reply'),
      retweet_count: getMetric(article, 'retweet'),
      like_count: getMetric(article, 'like'),
      view_count: getMetric(article, 'app-text-transition-container'),
      media_assets: mediaFromArticle(article),
      raw_text: article.innerText || ''
    });
  }
  const bodyText = document.body?.innerText || '';
  return JSON.stringify({
    url: location.href,
    loginRequired: location.pathname.includes('/login') || /Sign in to X|登录 X|Log in/.test(bodyText),
    captchaRequired: /captcha|验证码|unusual activity/i.test(bodyText),
    items
  });
})()
"""

    def __init__(self) -> None:
        self.client = WebBridgeClient(session=os.getenv("WEBBRIDGE_SESSION", "radar-x"))

    def configured_session_mode(self) -> str:
        value = (
            os.getenv("BEECLAW_X_BROWSER_SESSION_MODE")
            or os.getenv("X_BROWSER_SESSION_MODE")
            or os.getenv("BEECLAW_BROWSER_SESSION_MODE")
            or os.getenv("BROWSER_SESSION_MODE")
            or "auto"
        )
        return value.strip().lower().replace("-", "_")

    def cloud_endpoint(self) -> str | None:
        return (
            os.getenv("BEECLAW_X_BROWSER_ENDPOINT")
            or os.getenv("X_BROWSER_ENDPOINT")
            or os.getenv("BEECLAW_AGENT_BROWSER_ENDPOINT")
            or os.getenv("AGENT_BROWSER_ENDPOINT")
        )

    def headless_command(self) -> str | None:
        return (
            os.getenv("BEECLAW_X_BROWSER_CMD")
            or os.getenv("X_BROWSER_CMD")
            or os.getenv("BEECLAW_X_BROWSER_EXEC")
            or os.getenv("X_BROWSER_EXEC")
        )

    def browser_timeout(self) -> int:
        return int(
            os.getenv(
                "BEECLAW_X_BROWSER_TIMEOUT",
                os.getenv("X_BROWSER_TIMEOUT", os.getenv("BEECLAW_AGENT_BROWSER_TIMEOUT", os.getenv("AGENT_BROWSER_TIMEOUT", "120"))),
            )
        )

    def browser_request_payload(self, *, handle: str, max_results: int, mode: str) -> dict[str, Any]:
        url = f"https://x.com/{urllib.parse.quote(handle)}"
        payload = {
            "platform": "x",
            "task": "profile_posts",
            "handle": handle,
            "url": url,
            "maxResults": max_results,
            "includeMetrics": True,
            "includeMedia": True,
            "mode": mode,
            "headless": os.getenv("BEECLAW_X_BROWSER_HEADLESS", os.getenv("AGENT_BROWSER_HEADLESS", "true")).lower() != "false",
            "provider": os.getenv("BEECLAW_X_BROWSER_PROVIDER") or os.getenv("AGENT_BROWSER_PROVIDER"),
            "profileDir": os.getenv("BEECLAW_X_BROWSER_PROFILE_DIR") or os.getenv("AGENT_BROWSER_PROFILE_DIR"),
            "cookiesPath": os.getenv("BEECLAW_X_BROWSER_COOKIES_PATH") or os.getenv("AGENT_BROWSER_COOKIES_PATH"),
            "storageState": os.getenv("BEECLAW_X_BROWSER_STORAGE_STATE") or os.getenv("AGENT_BROWSER_STORAGE_STATE"),
            "cdpUrl": os.getenv("BEECLAW_X_BROWSER_CDP_URL") or os.getenv("AGENT_BROWSER_CDP_URL"),
        }
        return {key: value for key, value in payload.items() if value not in (None, "")}

    def fetch_via_cloud_browser(self, *, handle: str, max_results: int, endpoint: str, mode: str) -> tuple[dict[str, Any], str]:
        headers = {"Accept": "application/json"}
        token = (
            os.getenv("BEECLAW_X_BROWSER_API_KEY")
            or os.getenv("X_BROWSER_API_KEY")
            or os.getenv("BEECLAW_AGENT_BROWSER_API_KEY")
            or os.getenv("AGENT_BROWSER_API_KEY")
        )
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = http_post_json(
            endpoint,
            payload=self.browser_request_payload(handle=handle, max_results=max_results, mode=mode),
            headers=headers,
            timeout_seconds=self.browser_timeout(),
        )
        return payload, "cloud_browser_session"

    def fetch_via_headless_command(self, *, handle: str, max_results: int, command_template: str) -> tuple[dict[str, Any], str]:
        url = f"https://x.com/{urllib.parse.quote(handle)}"
        args = shlex.split(command_template.format(handle=handle, max_results=max_results, url=url))
        completed = subprocess.run(args, capture_output=True, text=True, timeout=self.browser_timeout())
        if completed.returncode != 0:
            raise ProviderError(
                (completed.stderr or completed.stdout or "headless browser command failed").strip(),
                error_type="headless_browser_failed",
            )
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderError("headless browser command returned invalid JSON", error_type="headless_browser_bad_response") from exc
        if not isinstance(payload, dict):
            raise ProviderError("headless browser command returned unsupported JSON", error_type="headless_browser_bad_response")
        return payload, "headless_browser_session"

    def fetch_via_local_webbridge(self, *, handle: str) -> tuple[dict[str, Any], str]:
        status = webbridge_status(self.client.base_url)
        if not status.get("reachable"):
            raise ProviderError(
                f"kimi-webbridge unavailable: {status.get('error')}",
                error_type="webbridge_unavailable",
            )
        self.client.navigate(f"https://x.com/{urllib.parse.quote(handle)}")
        return self.client.evaluate_json(self.extract_js), "browser_session"

    def fetch_browser_payload(self, *, handle: str, max_results: int) -> tuple[dict[str, Any], str]:
        mode = self.configured_session_mode()
        endpoint = self.cloud_endpoint()
        command = self.headless_command()
        if mode in {"cloud", "cloud_browser", "cloud_browser_session"}:
            if not endpoint:
                raise ProviderError("cloud browser session requires BEECLAW_X_BROWSER_ENDPOINT", error_type="missing_browser_endpoint")
            return self.fetch_via_cloud_browser(handle=handle, max_results=max_results, endpoint=endpoint, mode="cloud")
        if mode in {"headless", "headless_browser", "headless_browser_session"}:
            if command:
                return self.fetch_via_headless_command(handle=handle, max_results=max_results, command_template=command)
            if endpoint:
                return self.fetch_via_cloud_browser(handle=handle, max_results=max_results, endpoint=endpoint, mode="headless")
            raise ProviderError("headless browser session requires BEECLAW_X_BROWSER_CMD or BEECLAW_X_BROWSER_ENDPOINT", error_type="missing_browser_backend")
        if mode in {"local", "local_browser", "webbridge", "browser_session"}:
            return self.fetch_via_local_webbridge(handle=handle)
        if endpoint:
            return self.fetch_via_cloud_browser(handle=handle, max_results=max_results, endpoint=endpoint, mode="cloud")
        if command:
            return self.fetch_via_headless_command(handle=handle, max_results=max_results, command_template=command)
        return self.fetch_via_local_webbridge(handle=handle)

    def normalize_browser_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        items = payload.get("items") or payload.get("tweets") or data.get("items") or data.get("tweets") or []
        return [item for item in items if isinstance(item, dict)]

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        handle = (account.get("account_handle") or account["account_name"]).strip().lstrip("@").replace(" ", "")
        if not handle:
            raise ProviderError("X browser mode requires account_handle or account_name", error_type="missing_account_identifier")
        payload, backend_name = self.fetch_browser_payload(handle=handle, max_results=max_results)
        if payload.get("captchaRequired"):
            raise ProviderError("X requires CAPTCHA or manual verification in Chrome", error_type="captcha_required")
        if payload.get("loginRequired"):
            raise ProviderError("not logged in to X in browser session", error_type="not_logged_in")

        items = []
        for raw in self.normalize_browser_items(payload)[:max_results]:
            original_id = str(raw.get("id") or stable_content_id("x-browser", raw.get("url") or raw.get("text") or ""))
            media_assets = [asset for asset in (raw.get("media_assets") or []) if asset.get("url")]
            author_username = x_username_from_status_url(raw.get("url"))
            requested_handle = handle.lower()
            browser_repost = (
                bool(author_username and author_username.lower() != requested_handle)
                or bool(re.search(r"(^|\n).{1,80}\sreposted(\n|$)", raw.get("raw_text") or "", flags=re.IGNORECASE))
            )
            referenced_tweets = [{"type": "retweeted", "id": original_id}] if browser_repost else []
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=original_id,
                    title=None,
                    text=raw.get("text"),
                    published_at=raw.get("published_at"),
                    url=raw.get("url"),
                    view_count=int_or_none(raw.get("view_count")),
                    like_count=int_or_none(raw.get("like_count")),
                    comment_count=int_or_none(raw.get("reply_count")),
                    share_count=int_or_none(raw.get("retweet_count")),
                    media_type=media_type_from_assets("post", media_assets),
                    language=None,
                    raw_payload={
                        "source": self.source_name,
                        "provider_backend": backend_name,
                        **raw,
                        "author_username": author_username,
                        "requested_handle": handle,
                        "referenced_tweets": referenced_tweets,
                    },
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            last_seen_original_id=items[0].original_content_id if items else None,
        )


class XApiProvider:
    platform = PLATFORM_X
    base_url = "https://api.x.com/2"
    source_name = X_PUBLIC_PROVIDER
    backend_name = "x_api"

    def __init__(self) -> None:
        self.bearer_token = require_env("X_BEARER_TOKEN")

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        handle = (account.get("account_handle") or account["account_name"]).lstrip("@")
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        user = http_json(f"{self.base_url}/users/by/username/{urllib.parse.quote(handle)}", headers=headers)
        user_id = user.get("data", {}).get("id")
        if not user_id:
            raise ProviderError(f"X user not found: {handle}", error_type="account_not_found")

        params = {
            "max_results": max(5, min(max_results, 100)),
            "start_time": iso_days_ago(7),
            "tweet.fields": "created_at,public_metrics,lang,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "type,url,preview_image_url,width,height,alt_text,variants",
            "exclude": "replies",
        }
        if account.get("last_seen_original_id"):
            params["since_id"] = account["last_seen_original_id"]

        payload = http_json(f"{self.base_url}/users/{user_id}/tweets", headers=headers, params=params)
        media_by_key = {str(media.get("media_key")): media for media in payload.get("includes", {}).get("media", []) or []}
        items = []
        for tweet in payload.get("data", []) or []:
            metrics = tweet.get("public_metrics", {})
            tweet_id = str(tweet["id"])
            media_assets = media_assets_from_x_payload(tweet, media_by_key)
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=tweet_id,
                    title=None,
                    text=tweet.get("text"),
                    published_at=tweet.get("created_at"),
                    url=f"https://x.com/{handle}/status/{tweet_id}",
                    view_count=int_or_none(metrics.get("impression_count")),
                    like_count=int_or_none(metrics.get("like_count")),
                    comment_count=int_or_none(metrics.get("reply_count")),
                    share_count=int_or_none(metrics.get("retweet_count")),
                    media_type=media_type_from_assets("post", media_assets),
                    language=tweet.get("lang"),
                    raw_payload={
                        **tweet,
                        "source": self.source_name,
                        "provider_backend": self.backend_name,
                    },
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            next_cursor=payload.get("meta", {}).get("next_token"),
            last_seen_original_id=items[0].original_content_id if items else None,
        )


def media_assets_from_twitterapi_io_tweet(tweet: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort media extraction from TwitterAPI.io tweet payloads.

    TwitterAPI.io has evolved response shapes across endpoints. Keep this
    defensive and only emit assets with explicit URLs.
    """
    raw_media: list[Any] = []
    extended = tweet.get("extendedEntities") or tweet.get("extended_entities") or {}
    entities = tweet.get("entities") or {}
    for value in (
        extended.get("media") if isinstance(extended, dict) else None,
        entities.get("media") if isinstance(entities, dict) else None,
        tweet.get("media"),
        tweet.get("medias"),
        tweet.get("photos"),
        tweet.get("videos"),
    ):
        if isinstance(value, list):
            raw_media.extend(value)
    for key in ("mediaUrls", "media_urls", "imageUrls", "image_urls", "videoUrls", "video_urls"):
        value = tweet.get(key)
        if isinstance(value, list):
            raw_media.extend({"url": item} for item in value if item)

    assets: list[dict[str, Any]] = []
    for media in raw_media:
        if isinstance(media, str):
            media = {"url": media}
        if not isinstance(media, dict):
            continue
        asset = compact_media_asset(
            {
                "type": media.get("type") or media.get("media_type") or media.get("mediaType"),
                "url": media.get("url") or media.get("media_url") or media.get("mediaUrl") or media.get("preview_image_url"),
                "download_url": media.get("download_url") or media.get("video_url") or media.get("videoUrl") or media.get("url"),
                "thumbnail_url": media.get("thumbnail_url") or media.get("preview_image_url") or media.get("media_url_https"),
                "alt_text": media.get("alt_text") or media.get("altText"),
                "width": media.get("width"),
                "height": media.get("height"),
            }
        )
        if asset:
            assets.append(asset)
    return assets


class TwitterApiIoProvider:
    platform = PLATFORM_X
    source_name = X_PUBLIC_PROVIDER
    backend_name = "twitterapi_io"

    def __init__(self) -> None:
        self.api_key = require_env("TWITTERAPI_IO_KEY")
        self.base_url = os.getenv("TWITTERAPI_IO_BASE_URL", "https://api.twitterapi.io").rstrip("/")

    def _last_tweets_payload(self, *, handle: str, cursor: str) -> dict[str, Any]:
        headers = {"X-API-Key": self.api_key}
        params = {
            "userName": handle,
            "includeReplies": "false",
            "cursor": cursor,
        }
        for attempt in range(2):
            try:
                return http_json(
                    f"{self.base_url}/twitter/user/last_tweets",
                    headers=headers,
                    params=params,
                )
            except ProviderError as exc:
                if exc.status_code == 429 and attempt == 0:
                    delay = float(os.getenv("TWITTERAPI_IO_RETRY_SLEEP_SECONDS", "5.5"))
                    time.sleep(delay)
                    continue
                raise
        raise ProviderError("TwitterAPI.io rate limit retry exhausted", error_type="rate_limited", status_code=429)

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        handle = normalize_x_handle(
            account.get("account_handle")
            or account.get("account_url")
            or account.get("account_name")
            or ""
        )
        if not handle:
            raise ProviderError("TwitterAPI.io mode requires an X handle or profile URL.", error_type="missing_account_identifier")
        tweets: list[dict[str, Any]] = []
        next_cursor: str | None = None
        cursor = ""
        while len(tweets) < max_results:
            payload = self._last_tweets_payload(handle=handle, cursor=cursor)
            if str(payload.get("status") or "success").lower() == "error":
                message = str(payload.get("message") or "TwitterAPI.io returned an error")
                lowered = message.lower()
                if "credit" in lowered or "payment" in lowered:
                    raise ProviderError(message, error_type="credits_depleted", status_code=402)
                raise ProviderError(message, error_type="twitterapi_io_error")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            tweets.extend(tweet for tweet in (payload.get("tweets") or data.get("tweets") or []) if isinstance(tweet, dict))
            next_cursor = payload.get("next_cursor") or data.get("next_cursor") or data.get("nextCursor")
            has_next_page = payload.get("has_next_page")
            if has_next_page is None:
                has_next_page = data.get("has_next_page") or data.get("hasNextPage")
            if not has_next_page or not next_cursor:
                break
            cursor = str(next_cursor)

        items: list[ContentItem] = []
        for tweet in tweets[:max_results]:
            tweet_id = str(tweet.get("id") or stable_content_id("twitterapi-io", tweet.get("url") or tweet.get("text") or ""))
            author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
            username = author.get("userName") or author.get("username") or handle
            media_assets = media_assets_from_twitterapi_io_tweet(tweet)
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=tweet_id,
                    title=None,
                    text=tweet.get("text"),
                    published_at=tweet.get("createdAt") or tweet.get("created_at"),
                    url=tweet.get("url") or f"https://x.com/{username}/status/{tweet_id}",
                    view_count=int_or_none(tweet.get("viewCount") or tweet.get("views")),
                    like_count=int_or_none(tweet.get("likeCount") or tweet.get("likes")),
                    comment_count=int_or_none(tweet.get("replyCount") or tweet.get("comments")),
                    share_count=int_or_none(tweet.get("retweetCount") or tweet.get("retweets")),
                    media_type=media_type_from_assets("post", media_assets),
                    language=tweet.get("lang"),
                    raw_payload={
                        **tweet,
                        "source": self.source_name,
                        "provider_backend": self.backend_name,
                        "requested_handle": handle,
                        "metrics_complete": True,
                        "media_complete": bool(media_assets),
                    },
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            next_cursor=next_cursor,
            last_seen_original_id=items[0].original_content_id if items else None,
        )


class XMcpXProvider:
    platform = PLATFORM_X
    source_name = X_PUBLIC_PROVIDER
    backend_name: str | None = "x_mcp"

    def __init__(self) -> None:
        self.server_url = os.getenv("XMCP_SERVER_URL", "http://127.0.0.1:8000/mcp")

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        handle = (account.get("account_handle") or account["account_name"]).lstrip("@")
        user = backend_mcp_call_tool(
            integration="x-mcp",
            server_url=self.server_url,
            tool_name="getUsersByUsername",
            arguments={
                "username": handle,
                "user.fields": ["id", "name", "username"],
            },
        )
        user_id = user.get("data", {}).get("id")
        if not user_id:
            raise ProviderError(f"X user not found via XMCP: {handle}", error_type="account_not_found")

        params: dict[str, Any] = {
            "id": user_id,
            "max_results": max(5, min(max_results, 100)),
            "start_time": iso_days_ago(7),
            "tweet.fields": ["created_at", "public_metrics", "lang", "attachments"],
            "expansions": ["attachments.media_keys"],
            "media.fields": ["type", "url", "preview_image_url", "width", "height", "alt_text", "variants"],
            "exclude": ["replies"],
        }
        if account.get("last_seen_original_id"):
            params["since_id"] = account["last_seen_original_id"]

        try:
            payload = backend_mcp_call_tool(
                integration="x-mcp",
                server_url=self.server_url,
                tool_name="getUsersPosts",
                arguments=params,
            )
        except ProviderError as exc:
            if exc.error_type != "xmcp_error":
                raise
            payload = backend_mcp_call_tool(
                integration="x-mcp",
                server_url=self.server_url,
                tool_name="getUsersIdPosts",
                arguments=params,
            )
        media_by_key = {str(media.get("media_key")): media for media in payload.get("includes", {}).get("media", []) or []}
        items = []
        for tweet in payload.get("data", []) or []:
            metrics = tweet.get("public_metrics", {})
            tweet_id = str(tweet["id"])
            media_assets = media_assets_from_x_payload(tweet, media_by_key)
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=tweet_id,
                    title=None,
                    text=tweet.get("text"),
                    published_at=tweet.get("created_at"),
                    url=f"https://x.com/{handle}/status/{tweet_id}",
                    view_count=int_or_none(metrics.get("impression_count")),
                    like_count=int_or_none(metrics.get("like_count")),
                    comment_count=int_or_none(metrics.get("reply_count")),
                    share_count=int_or_none(metrics.get("retweet_count")),
                    media_type=media_type_from_assets("post", media_assets),
                    language=tweet.get("lang"),
                    raw_payload={
                        **tweet,
                        "source": self.source_name,
                        **({"provider_backend": self.backend_name} if self.backend_name else {}),
                    },
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            next_cursor=payload.get("meta", {}).get("next_token"),
            last_seen_original_id=items[0].original_content_id if items else None,
        )


class FeedgrabXMcpXProvider(XMcpXProvider):
    """Radar-facing Beeclaw X MCP provider.

    Beeclaw is Radar's public provider namespace. The upstream feedgrab route is
    preserved as provider_backend for auditability.
    """

    source_name = X_PUBLIC_PROVIDER
    backend_name = "x_mcp"


class BeeclawUrlAccountProvider:
    """Generic Beeclaw account provider for platforms that expose a readable URL.

    This is the production fallback for non-X platform account rows until a
    platform has a dedicated account/search API provider. It requires
    source_accounts.account_url or a URL-like account_handle.
    """

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def account_url(self, account: dict[str, Any]) -> str:
        value = (account.get("account_url") or account.get("account_handle") or "").strip()
        if not value.startswith(("http://", "https://")):
            raise ProviderError(
                f"{self.platform} Beeclaw account mode requires account_url or URL-like account_handle.",
                error_type="missing_account_identifier",
            )
        return value

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        url = self.account_url(account)
        content = read_url(url)
        item = unified_content_to_item(content)
        provider = feedgrab_provider_for_platform(self.platform) or f"beeclaw:{self.platform}"
        item = ContentItem(
            platform=self.platform,
            original_content_id=item.original_content_id,
            title=item.title,
            text=item.text,
            published_at=item.published_at,
            url=item.url or url,
            view_count=item.view_count,
            like_count=item.like_count,
            comment_count=item.comment_count,
            share_count=item.share_count,
            media_type=item.media_type,
            language=item.language,
            raw_payload={
                **item.raw_payload,
                "source": beeclaw_provider_name(provider),
                "provider_backend": item.raw_payload.get("provider_backend") or "beeclaw:universal_reader",
                "account_url": url,
            },
            media_assets=item.media_assets,
        )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=[item],
            last_seen_original_id=item.original_content_id,
        )


class BeeclawUrlAccountProviderFactory:
    def __init__(self, platform: str) -> None:
        self.platform = platform

    def __call__(self) -> BeeclawUrlAccountProvider:
        return BeeclawUrlAccountProvider(self.platform)


def beeclaw_url_provider_factory(platform: str) -> BeeclawUrlAccountProviderFactory:
    return BeeclawUrlAccountProviderFactory(platform)


class YouTubeApiProvider:
    platform = PLATFORM_YOUTUBE
    base_url = "https://www.googleapis.com/youtube/v3"

    def __init__(self) -> None:
        self.api_key = require_env("YOUTUBE_API_KEY")

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        channel_id = youtube_channel_id(account)
        if not channel_id:
            raise ProviderError(
                "YouTube requires source_accounts.account_handle or channel URL to contain channelId",
                error_type="missing_account_identifier",
            )

        search_payload = http_json(
            f"{self.base_url}/search",
            params={
                "key": self.api_key,
                "channelId": channel_id,
                "part": "snippet",
                "order": "date",
                "type": "video",
                "publishedAfter": iso_days_ago(7),
                "maxResults": max(1, min(max_results, 50)),
            },
        )
        video_ids = [
            item.get("id", {}).get("videoId")
            for item in search_payload.get("items", []) or []
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return FetchResult(account_id=int(account["id"]), platform=self.platform, items=[])

        videos_payload = http_json(
            f"{self.base_url}/videos",
            params={
                "key": self.api_key,
                "id": ",".join(video_ids),
                "part": "snippet,statistics,contentDetails",
            },
        )
        items = []
        for video in videos_payload.get("items", []) or []:
            snippet = video.get("snippet", {})
            stats = video.get("statistics", {})
            video_id = str(video["id"])
            thumbnails = snippet.get("thumbnails") or {}
            best_thumbnail = (
                thumbnails.get("maxres")
                or thumbnails.get("standard")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )
            media_assets = [
                {
                    "type": "video",
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail_url": best_thumbnail.get("url"),
                    "width": best_thumbnail.get("width"),
                    "height": best_thumbnail.get("height"),
                }
            ]
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=video_id,
                    title=snippet.get("title"),
                    text=snippet.get("description"),
                    published_at=snippet.get("publishedAt"),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    view_count=int_or_none(stats.get("viewCount")),
                    like_count=int_or_none(stats.get("likeCount")),
                    comment_count=int_or_none(stats.get("commentCount")),
                    share_count=None,
                    media_type="video",
                    language=snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage"),
                    raw_payload=video,
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            last_seen_original_id=items[0].original_content_id if items else None,
        )


class YouTubeRssProvider:
    platform = PLATFORM_YOUTUBE
    feed_url = "https://www.youtube.com/feeds/videos.xml"

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        channel_id = youtube_channel_id(account)
        if not channel_id:
            raise ProviderError(
                "YouTube RSS requires source_accounts.account_handle or channel URL to contain channelId",
                error_type="missing_account_identifier",
            )

        xml_text = http_text(self.feed_url, params={"channel_id": channel_id})
        root = ET.fromstring(xml_text)
        namespaces = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
            "media": "http://search.yahoo.com/mrss/",
        }
        items = []
        for entry in root.findall("atom:entry", namespaces)[:max_results]:
            video_id = entry.findtext("yt:videoId", namespaces=namespaces)
            title = entry.findtext("atom:title", namespaces=namespaces)
            published_at = entry.findtext("atom:published", namespaces=namespaces)
            link = entry.find("atom:link", namespaces)
            media_group = entry.find("media:group", namespaces)
            description = None
            thumbnail_url = None
            if media_group is not None:
                description = media_group.findtext("media:description", namespaces=namespaces)
                thumbnail = media_group.find("media:thumbnail", namespaces)
                if thumbnail is not None:
                    thumbnail_url = thumbnail.attrib.get("url")
            if not video_id:
                continue
            media_assets = [
                {
                    "type": "video",
                    "url": link.attrib.get("href") if link is not None else f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail_url": thumbnail_url,
                }
            ]
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=video_id,
                    title=title,
                    text=description,
                    published_at=published_at,
                    url=link.attrib.get("href") if link is not None else f"https://www.youtube.com/watch?v={video_id}",
                    view_count=None,
                    like_count=None,
                    comment_count=None,
                    share_count=None,
                    media_type="video",
                    language=None,
                    raw_payload={"source": "youtube_rss", "video_id": video_id, "channel_id": channel_id},
                    media_assets=media_assets,
                )
            )
        return FetchResult(
            account_id=int(account["id"]),
            platform=self.platform,
            items=items,
            last_seen_original_id=items[0].original_content_id if items else None,
        )


class LinkedInApiProvider:
    platform = PLATFORM_LINKEDIN

    def __init__(self) -> None:
        self.access_token = require_env("LINKEDIN_ACCESS_TOKEN")

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        author_urn = account.get("account_handle")
        if not author_urn:
            raise ProviderError(
                "LinkedIn official API requires an authorized author URN in account_handle",
                error_type="missing_account_identifier",
            )

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": os.getenv("LINKEDIN_VERSION", "202603"),
            "X-Restli-Protocol-Version": "2.0.0",
        }
        payload = http_json(
            "https://api.linkedin.com/rest/posts",
            headers=headers,
            params={
                "q": "author",
                "author": author_urn,
                "count": max(1, min(max_results, 100)),
                "sortBy": "LAST_MODIFIED",
            },
        )
        items = []
        for post in payload.get("elements", []) or []:
            post_id = str(post.get("id"))
            commentary = post.get("commentary") or ""
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=post_id,
                    title=None,
                    text=commentary,
                    published_at=str(post.get("publishedAt")) if post.get("publishedAt") else None,
                    url=None,
                    view_count=None,
                    like_count=None,
                    comment_count=None,
                    share_count=None,
                    media_type="post",
                    language=None,
                    raw_payload=post,
                )
            )
        return FetchResult(account_id=int(account["id"]), platform=self.platform, items=items)


class InstagramApiProvider:
    platform = PLATFORM_INSTAGRAM

    def __init__(self) -> None:
        self.access_token = require_env("INSTAGRAM_ACCESS_TOKEN")

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        instagram_user_id = account.get("account_handle")
        if not instagram_user_id:
            raise ProviderError(
                "Instagram Graph API requires an authorized Business/Creator user id in account_handle",
                error_type="missing_account_identifier",
            )

        payload = http_json(
            f"https://graph.instagram.com/{instagram_user_id}/media",
            params={
                "access_token": self.access_token,
                "limit": max(1, min(max_results, 100)),
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
            },
        )
        items = []
        for media in payload.get("data", []) or []:
            media_type = media.get("media_type")
            media_assets = []
            if media.get("media_url"):
                media_assets.append(
                    {
                        "type": media_type.lower() if isinstance(media_type, str) else "media",
                        "url": media.get("media_url"),
                        "thumbnail_url": media.get("thumbnail_url") or media.get("media_url"),
                    }
                )
            items.append(
                ContentItem(
                    platform=self.platform,
                    original_content_id=str(media["id"]),
                    title=None,
                    text=media.get("caption"),
                    published_at=media.get("timestamp"),
                    url=media.get("permalink"),
                    view_count=None,
                    like_count=int_or_none(media.get("like_count")),
                    comment_count=int_or_none(media.get("comments_count")),
                    share_count=None,
                    media_type=media_type,
                    language=None,
                    raw_payload=media,
                    media_assets=media_assets,
                )
            )
        return FetchResult(account_id=int(account["id"]), platform=self.platform, items=items)


class UnsupportedProviderFactory:
    def __init__(self, platform: str) -> None:
        self.platform = platform

    def __call__(self) -> NoTokenUnsupportedProvider:
        return NoTokenUnsupportedProvider(self.platform)


def unsupported_provider_factory(platform: str) -> UnsupportedProviderFactory:
    return UnsupportedProviderFactory(platform)


BEECLAW_URL_PLATFORMS = (
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
)


def beeclaw_url_provider_map() -> dict[str, BeeclawUrlAccountProviderFactory]:
    return {platform: beeclaw_url_provider_factory(platform) for platform in BEECLAW_URL_PLATFORMS}


PROVIDER_REGISTRY = {
    MODE_API: {
        PLATFORM_X: XApiProvider,
        PLATFORM_YOUTUBE: YouTubeApiProvider,
        PLATFORM_LINKEDIN: LinkedInApiProvider,
        PLATFORM_INSTAGRAM: InstagramApiProvider,
    },
    MODE_NO_TOKEN: {
        PLATFORM_X: XRssProvider,
        PLATFORM_YOUTUBE: YouTubeRssProvider,
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_XMCP: {
        PLATFORM_X: XMcpXProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_FEEDGRAB_X: {
        PLATFORM_X: FeedgrabXMcpXProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_FEEDGRAB_XMCP: {
        PLATFORM_X: FeedgrabXMcpXProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_FEEDGRAB_X_TWITTERAPI_IO: {
        PLATFORM_X: TwitterApiIoProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_FEEDGRAB_X_RSS: {
        PLATFORM_X: BeeclawXRssProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_FEEDGRAB: {
        PLATFORM_X: FeedgrabXMcpXProvider,
        PLATFORM_YOUTUBE: YouTubeRssProvider,
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
        **beeclaw_url_provider_map(),
    },
    MODE_CHROME_SESSION: {
        PLATFORM_X: XBrowserSessionProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_BROWSER_SESSION: {
        PLATFORM_X: XBrowserSessionProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
    MODE_X_RSS: {
        PLATFORM_X: XRssProvider,
        PLATFORM_YOUTUBE: unsupported_provider_factory(PLATFORM_YOUTUBE),
        PLATFORM_LINKEDIN: unsupported_provider_factory(PLATFORM_LINKEDIN),
        PLATFORM_INSTAGRAM: unsupported_provider_factory(PLATFORM_INSTAGRAM),
    },
}

AUTO_MODE_ORDER = {
    PLATFORM_X: (MODE_FEEDGRAB_XMCP, MODE_API, MODE_FEEDGRAB_X_TWITTERAPI_IO, MODE_FEEDGRAB_X_RSS, MODE_BROWSER_SESSION),
    PLATFORM_YOUTUBE: (MODE_NO_TOKEN, MODE_API),
    PLATFORM_LINKEDIN: (MODE_API,),
    PLATFORM_INSTAGRAM: (MODE_API,),
}


def provider_mode_capabilities() -> dict[str, dict[str, bool]]:
    return {
        mode: {
            platform: not isinstance(factory, UnsupportedProviderFactory)
            for platform, factory in providers.items()
        }
        for mode, providers in PROVIDER_REGISTRY.items()
    }


class AutoProvider:
    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.mode_order = AUTO_MODE_ORDER.get(platform)
        if not self.mode_order:
            raise ProviderError(f"unsupported platform: {platform}", error_type="unsupported_platform")
        self.providers: dict[str, Provider] = {}

    def fetch(self, account: dict[str, Any], *, max_results: int) -> FetchResult:
        attempts: list[dict[str, Any]] = []
        for mode in self.mode_order:
            backend = x_backend_for_mode(mode) if self.platform == PLATFORM_X else mode
            try:
                if mode not in self.providers:
                    self.providers[mode] = build_provider(self.platform, mode=mode)
                result = self.providers[mode].fetch(account, max_results=max_results)
                if not result.items:
                    attempts.append(
                        {
                            "backend": backend,
                            "mode": mode,
                            "status": "failed",
                            "error": "empty_result",
                            "message": "backend returned no content items",
                        }
                    )
                    continue
                if self.platform == PLATFORM_X:
                    success_attempts = [
                        *attempts,
                        {"backend": backend, "mode": mode, "status": "success"},
                    ]
                    return annotate_x_fetch_result(
                        result,
                        backend=backend,
                        backend_attempts=success_attempts,
                        selection_reason=x_backend_selection_reason(backend),
                    )
                return result
            except ProviderError as exc:
                attempts.append(
                    {
                        "backend": backend,
                        "mode": mode,
                        "status": "failed",
                        "error": exc.error_type,
                        "message": str(exc),
                        **({"status_code": exc.status_code} if exc.status_code else {}),
                    }
                )
                if exc.error_type not in AUTO_RECOVERABLE_ERRORS:
                    raise
        raise ProviderError(
            json.dumps({"platform": self.platform, "attempts": attempts}, ensure_ascii=False),
            error_type="auto_provider_unavailable",
        )


def build_provider(platform: str, *, mode: str = MODE_AUTO) -> Provider:
    mode = normalize_provider_mode(mode)
    if mode == MODE_AUTO or (platform == PLATFORM_X and mode == MODE_FEEDGRAB_X):
        return AutoProvider(platform)
    providers = PROVIDER_REGISTRY.get(mode)
    if providers is None:
        raise ProviderError(f"unsupported mode: {mode}", error_type="unsupported_mode")
    try:
        return providers[platform]()
    except KeyError as exc:
        raise ProviderError(f"unsupported platform: {platform}", error_type="unsupported_platform") from exc
