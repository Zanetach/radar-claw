from __future__ import annotations

import importlib.metadata
import os
import shutil
import urllib.error
import urllib.request
from typing import Any

from ..platform_mcp_gateway import platform_backend_mcp_status
from .cli_tools import cli_health, resolve_cli
from .platforms import feedgrab_url_provider_catalog


def _installed_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _http_probe(url: str) -> dict[str, Any]:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json,text/event-stream"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            return {"reachable": response.status < 500, "message": f"HTTP {response.status}"}
    except urllib.error.HTTPError as exc:
        return {"reachable": exc.code < 500, "message": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"reachable": False, "message": str(exc)}


def provider_catalog() -> list[dict[str, Any]]:
    """Return Radar's Beeclaw-facing provider catalog."""
    x_providers = [
        {
            "platform": "x",
            "provider": "beeclaw:x",
            "priority": 110,
            "capabilities": ["account_posts", "post_detail", "keyword_search", "metrics", "media_metadata", "media_download", "auto_backend_selection"],
            "requires": [],
            "backends": [
                "x_mcp",
                "x_api",
                "twitterapi_io",
                "x_rss",
                "twitter-cli",
                "cloud_browser_session",
                "headless_browser_session",
                "local_browser_session",
            ],
        },
        {
            "platform": "x",
            "provider": "beeclaw:x_mcp",
            "priority": 100,
            "capabilities": ["account_posts", "post_detail", "keyword_search", "metrics", "media_metadata", "media_download"],
            "requires": ["PLATFORM_MCP_GATEWAY_URL or X_MCP_SERVER_URL", "X MCP"],
        },
        {
            "platform": "x",
            "provider": "beeclaw:x_api",
            "priority": 90,
            "capabilities": ["account_posts", "post_detail", "keyword_search", "metrics", "media_metadata"],
            "requires": ["X_BEARER_TOKEN"],
        },
        {
            "platform": "x",
            "provider": "beeclaw:x_twitterapi_io",
            "priority": 80,
            "capabilities": ["account_posts", "post_detail", "metrics", "read_only_third_party_api"],
            "requires": ["TWITTERAPI_IO_KEY"],
        },
        {
            "platform": "x",
            "provider": "beeclaw:x_rss",
            "priority": 50,
            "capabilities": ["account_posts", "text", "image_metadata"],
            "requires": [],
        },
        {
            "platform": "x",
            "provider": "beeclaw:browser_session",
            "priority": 20,
            "capabilities": ["account_posts", "visible_media", "cloud_browser", "headless_browser", "local_browser"],
            "requires": ["BEECLAW_X_BROWSER_ENDPOINT or BEECLAW_X_BROWSER_CMD or local WebBridge login session"],
        },
    ]
    return x_providers + feedgrab_url_provider_catalog()


def _cli_backend_health(command: str) -> dict[str, Any]:
    return cli_health(command)


def _x_browser_session_health() -> dict[str, Any]:
    mode = (
        os.getenv("BEECLAW_X_BROWSER_SESSION_MODE")
        or os.getenv("X_BROWSER_SESSION_MODE")
        or os.getenv("BEECLAW_BROWSER_SESSION_MODE")
        or os.getenv("BROWSER_SESSION_MODE")
        or "auto"
    ).strip().lower()
    endpoint = os.getenv("BEECLAW_X_BROWSER_ENDPOINT") or os.getenv("X_BROWSER_ENDPOINT")
    command = os.getenv("BEECLAW_X_BROWSER_CMD") or os.getenv("X_BROWSER_CMD")
    api_key_configured = bool(os.getenv("BEECLAW_X_BROWSER_API_KEY") or os.getenv("X_BROWSER_API_KEY"))
    webbridge_url = os.getenv("WEBBRIDGE_URL", "http://127.0.0.1:10086")
    webbridge_probe = _http_probe(f"{webbridge_url.rstrip('/')}/status")
    return {
        "installed": bool(endpoint or command or webbridge_probe.get("reachable")),
        "type": "x_browser_session_router",
        "mode": mode,
        "cloud": {
            "configured": bool(endpoint),
            "endpointConfigured": bool(endpoint),
            "apiKeyConfigured": api_key_configured,
        },
        "headless": {
            "configured": bool(command or endpoint),
            "cmdConfigured": bool(command),
            "endpointConfigured": bool(endpoint),
            "headless": os.getenv("BEECLAW_X_BROWSER_HEADLESS", os.getenv("AGENT_BROWSER_HEADLESS", "true")).lower() != "false",
        },
        "local": {
            "configured": bool(webbridge_probe.get("reachable")),
            "webbridgeUrlConfigured": bool(os.getenv("WEBBRIDGE_URL")),
            "reachable": bool(webbridge_probe.get("reachable")),
            "message": webbridge_probe.get("message"),
        },
        "secretStatus": {
            "BEECLAW_X_BROWSER_API_KEY": api_key_configured,
            "X_BROWSER_API_KEY": bool(os.getenv("X_BROWSER_API_KEY")),
            "BEECLAW_X_BROWSER_COOKIES_PATH": bool(os.getenv("BEECLAW_X_BROWSER_COOKIES_PATH")),
            "BEECLAW_X_BROWSER_STORAGE_STATE": bool(os.getenv("BEECLAW_X_BROWSER_STORAGE_STATE")),
        },
        "secretValuesExposed": False,
    }


def feedgrab_health() -> dict[str, Any]:
    """Inspect Beeclaw and its upstream backends without exposing secrets."""
    feedgrab_version = _installed_version("feedgrab")
    mcp_version = _installed_version("mcp")
    xmcp_url = os.getenv("X_MCP_SERVER_URL") or os.getenv("XMCP_SERVER_URL") or "http://127.0.0.1:8000/mcp"
    xmcp_probe = _http_probe(xmcp_url)
    xhs_mcp_url = os.getenv("XHS_MCP_SERVER_URL") or os.getenv("XIAOHONGSHU_MCP_SERVER_URL") or "http://127.0.0.1:18060/mcp"
    xhs_mcp_probe = _http_probe(xhs_mcp_url)
    twitter_cli_path = resolve_cli("twitter-cli") or shutil.which("twitter")
    twitterapi_io_key_configured = bool(os.getenv("TWITTERAPI_IO_KEY"))
    backend_health = {
        "twitterapi_io": {
            "installed": twitterapi_io_key_configured,
            "configured": twitterapi_io_key_configured,
            "type": "third_party_rest_api",
            "baseUrl": os.getenv("TWITTERAPI_IO_BASE_URL", "https://api.twitterapi.io"),
            "readOnly": os.getenv("TWITTERAPI_IO_READ_ONLY", "true").lower() != "false",
            "secretValuesExposed": False,
        },
        "twitter-cli": {
            "installed": bool(twitter_cli_path),
            "path": twitter_cli_path,
        },
        "yt-dlp": _cli_backend_health("yt-dlp"),
        "xhs-cli": _cli_backend_health("xhs-cli"),
        "rdt-cli": _cli_backend_health("rdt-cli"),
        "gh": _cli_backend_health("gh"),
        "Jina Reader": {
            "installed": True,
            "type": "http_reader",
            "url": os.getenv("JINA_READER_URL", "https://r.jina.ai/http://example.com"),
        },
        "agent-browser": {
            **_cli_backend_health("agent-browser"),
            "type": "headless_or_cloud_browser",
            "endpointConfigured": bool(os.getenv("AGENT_BROWSER_ENDPOINT") or os.getenv("BEECLAW_AGENT_BROWSER_ENDPOINT")),
            "cmdConfigured": bool(os.getenv("BEECLAW_AGENT_BROWSER_CMD") or os.getenv("AGENT_BROWSER_CMD")),
            "headless": os.getenv("AGENT_BROWSER_HEADLESS", os.getenv("BEECLAW_AGENT_BROWSER_HEADLESS", "true")).lower() != "false",
            "secretValuesExposed": False,
        },
        "x_browser_session": _x_browser_session_health(),
        "rss_parser": {
            "installed": True,
            "type": "builtin",
        },
        "universal_reader": {
            "installed": feedgrab_version is not None,
            "type": "feedgrab_backend",
        },
    }
    return {
        "beeclaw": {
            "ready": feedgrab_version is not None,
            "providerNamespace": "beeclaw",
            "backend": "feedgrab",
        },
        "feedgrab_backend": {
            "installed": feedgrab_version is not None,
            "version": feedgrab_version,
            "pinnedSource": "https://github.com/iBigQiang/feedgrab.git@8cc6753edef4f1afee488c21e82f786b7f09175f",
        },
        "mcp": {
            "installed": mcp_version is not None,
            "version": mcp_version,
        },
        "xmcp": {
            "url": xmcp_url,
            **xmcp_probe,
        },
        "xhs_mcp": {
            "url": xhs_mcp_url,
            **xhs_mcp_probe,
        },
        "platform_mcp_gateway": platform_backend_mcp_status("*"),
        "twitter_cli": backend_health["twitter-cli"],
        "backend_health": backend_health,
        "providers": provider_catalog(),
    }
