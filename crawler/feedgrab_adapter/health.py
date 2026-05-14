from __future__ import annotations

import importlib.metadata
import os
import urllib.error
import urllib.request
from typing import Any

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
    """Return Radar's feedgrab-facing provider catalog."""
    x_providers = [
        {
            "platform": "x",
            "provider": "feedgrab:x_mcp",
            "priority": 100,
            "capabilities": ["account_posts", "post_detail", "keyword_search", "metrics", "media_metadata", "media_download"],
            "requires": ["X_MCP_SERVER_URL", "XMCP server"],
        },
        {
            "platform": "x",
            "provider": "feedgrab:x_api",
            "priority": 90,
            "capabilities": ["account_posts", "post_detail", "keyword_search", "metrics", "media_metadata"],
            "requires": ["X_BEARER_TOKEN"],
        },
        {
            "platform": "x",
            "provider": "feedgrab:x_rss",
            "priority": 50,
            "capabilities": ["account_posts", "text", "image_metadata"],
            "requires": [],
        },
        {
            "platform": "x",
            "provider": "feedgrab:browser_session",
            "priority": 20,
            "capabilities": ["account_posts", "visible_media"],
            "requires": ["Chrome login session"],
        },
    ]
    return x_providers + feedgrab_url_provider_catalog()


def feedgrab_health() -> dict[str, Any]:
    """Inspect local feedgrab and X MCP readiness without exposing secrets."""
    feedgrab_version = _installed_version("feedgrab")
    mcp_version = _installed_version("mcp")
    xmcp_url = os.getenv("X_MCP_SERVER_URL") or os.getenv("XMCP_SERVER_URL") or "http://127.0.0.1:8000/mcp"
    xmcp_probe = _http_probe(xmcp_url)
    return {
        "feedgrab": {
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
        "providers": provider_catalog(),
    }
