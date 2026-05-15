from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from hashlib import sha256
from typing import Any

from .platforms import infer_feedgrab_platform_from_url, normalize_feedgrab_platform


class FeedgrabUnavailable(RuntimeError):
    """Raised when feedgrab is not installed or cannot read content."""


async def _read_url_async(url: str) -> Any:
    try:
        from feedgrab.reader import UniversalReader
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise FeedgrabUnavailable(
            "feedgrab is not installed. Install requirements or pip install 'feedgrab[mcp]'."
        ) from exc

    reader = UniversalReader()
    return await reader.read(url)


def _command_json(args: list[str], *, timeout: int = 60) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise FeedgrabUnavailable(f"command not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FeedgrabUnavailable(f"command timed out: {' '.join(args)}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise FeedgrabUnavailable(message or f"command failed: {' '.join(args)}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FeedgrabUnavailable(f"command returned non-json output: {' '.join(args)}") from exc
    if not isinstance(payload, dict):
        raise FeedgrabUnavailable(f"command returned unsupported json output: {' '.join(args)}")
    return payload


def _cli_args(env_names: tuple[str, ...], default_prefix: list[str], url: str) -> tuple[list[str], bool]:
    for name in env_names:
        raw = os.getenv(name)
        if raw:
            return shlex.split(raw.format(url=url)), False
    return [*default_prefix, url], True


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _list_value(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    return [value]


def _attempt(backend: str, status: str, error: str | None = None) -> dict[str, Any]:
    item = {"backend": backend, "status": status}
    if error:
        item["error"] = error
    return item


def _content_extra(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        extra = content.get("extra")
        if isinstance(extra, dict):
            return extra
        content["extra"] = {}
        return content["extra"]
    return {}


def _attach_backend_metadata(content: Any, *, provider_backend: str, backend_attempts: list[dict[str, Any]]) -> Any:
    if not isinstance(content, dict):
        if hasattr(content, "to_dict"):
            content = content.to_dict()
        else:
            content = {
                "source_type": getattr(content, "source_type", "web"),
                "source_name": getattr(content, "source_name", "UniversalReader"),
                "title": getattr(content, "title", None),
                "content": getattr(content, "content", None),
                "url": getattr(content, "url", None),
                "id": getattr(content, "id", None),
                "extra": getattr(content, "extra", {}) or {},
            }
    extra = _content_extra(content)
    extra.setdefault("provider_backend", provider_backend)
    extra.setdefault("backend_attempts", backend_attempts)
    return content


def _http_text(url: str, *, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "Radar-Beeclaw/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


def _jina_reader_endpoint(url: str) -> str:
    base = os.getenv("JINA_READER_BASE_URL", "https://r.jina.ai").rstrip("/")
    return f"{base}/{url}"


def _markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if value.startswith("#"):
            return value.lstrip("#").strip() or fallback
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value[:80]
    return fallback


def _read_with_jina(url: str) -> dict[str, Any]:
    text = _http_text(_jina_reader_endpoint(url))
    return {
        "source_type": "web",
        "source_name": "Jina Reader",
        "title": _markdown_title(text, url),
        "content": text,
        "url": url,
        "id": sha256(url.encode("utf-8")).hexdigest()[:20],
        "extra": {
            "provider_backend": "Jina Reader",
            "backend_attempts": [_attempt("Jina Reader", "success")],
        },
    }


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _xml_children(node: ET.Element, name: str) -> list[ET.Element]:
    name = name.lower()
    return [child for child in list(node) if _xml_local_name(child.tag) == name]


def _xml_first_child(node: ET.Element, *names: str) -> ET.Element | None:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if _xml_local_name(child.tag) in wanted:
            return child
    return None


def _xml_text(node: ET.Element | None, *names: str) -> str:
    if node is None:
        return ""
    target = node if not names else _xml_first_child(node, *names)
    if target is None or target.text is None:
        return ""
    text = unescape(target.text).strip()
    return re.sub(r"<[^>]+>", "", text).strip()


def _xml_link(node: ET.Element, *, atom: bool) -> str:
    if atom:
        for child in _xml_children(node, "link"):
            rel = child.attrib.get("rel", "alternate")
            href = child.attrib.get("href")
            if href and rel in {"alternate", "self", ""}:
                return href.strip()
        return ""
    return _xml_text(node, "link")


def _xml_media(node: ET.Element) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for child in list(node):
        local = _xml_local_name(child.tag)
        if local not in {"enclosure", "content", "thumbnail"}:
            continue
        url = child.attrib.get("url")
        if not url:
            continue
        media_type = child.attrib.get("type") or child.attrib.get("medium")
        asset_type = "video" if media_type and "video" in media_type else "image" if media_type and "image" in media_type else "media"
        assets.append({"type": asset_type, "url": url, "mime_type": media_type})
    return assets


def _rss_item_payload(item: ET.Element, *, atom: bool) -> dict[str, Any]:
    title = _xml_text(item, "title")
    link = _xml_link(item, atom=atom)
    published_at = _xml_text(item, "published", "updated") if atom else _xml_text(item, "pubDate", "date")
    summary = _xml_text(item, "summary", "content") if atom else _xml_text(item, "description", "content")
    item_id = _xml_text(item, "id") if atom else _xml_text(item, "guid", "id")
    item_id = item_id or link or sha256(f"{title}:{published_at}".encode("utf-8")).hexdigest()[:20]
    media_assets = _xml_media(item)
    return {
        "id": item_id,
        "title": title or link or item_id,
        "url": link,
        "published_at": published_at,
        "summary": summary,
        "media_assets": media_assets,
    }


def _read_with_rss_parser(url: str) -> dict[str, Any]:
    xml_text = _http_text(url)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedgrabUnavailable(f"rss_parser invalid xml: {exc}") from exc

    root_name = _xml_local_name(root.tag)
    atom = root_name == "feed"
    if root_name == "rss":
        channel = _xml_first_child(root, "channel")
        items = _xml_children(channel, "item") if channel is not None else []
        feed_title = _xml_text(channel, "title") or url
        feed_link = _xml_text(channel, "link") or url
        feed_format = "rss"
    elif atom:
        channel = root
        items = _xml_children(root, "entry")
        feed_title = _xml_text(root, "title") or url
        feed_link = _xml_link(root, atom=True) or url
        feed_format = "atom"
    elif root_name == "rdf":
        channel = _xml_first_child(root, "channel")
        items = _xml_children(root, "item")
        feed_title = _xml_text(channel, "title") or url
        feed_link = _xml_text(channel, "link") or url
        feed_format = "rdf"
    else:
        raise FeedgrabUnavailable(f"rss_parser unsupported feed root: {root_name}")

    entries = [_rss_item_payload(item, atom=atom) for item in items]
    content_lines: list[str] = []
    for entry in entries[:50]:
        content_lines.append(f"- {entry['title']}")
        if entry.get("url"):
            content_lines.append(f"  {entry['url']}")
        if entry.get("summary"):
            content_lines.append(f"  {entry['summary']}")
    media_assets = [asset for entry in entries for asset in entry.get("media_assets", [])]
    images = [asset["url"] for asset in media_assets if asset.get("type") == "image"]
    videos = [asset["url"] for asset in media_assets if asset.get("type") == "video"]
    return {
        "source_type": "rss",
        "source_name": "rss_parser",
        "title": feed_title,
        "content": "\n".join(content_lines),
        "url": url,
        "id": sha256(url.encode("utf-8")).hexdigest()[:20],
        "extra": {
            "provider_backend": "rss_parser",
            "backend_attempts": [_attempt("rss_parser", "success")],
            "format": feed_format,
            "feed_url": url,
            "feed_link": feed_link,
            "item_count": len(entries),
            "items": entries,
            "images": images,
            "videos": videos,
        },
    }


def _read_with_ytdlp(url: str) -> dict[str, Any]:
    if not shutil.which("yt-dlp"):
        raise FeedgrabUnavailable("yt-dlp is not installed")
    payload = _command_json(["yt-dlp", "--dump-json", "--skip-download", url], timeout=120)
    thumbnails = payload.get("thumbnails") or []
    images = [item.get("url") for item in thumbnails if isinstance(item, dict) and item.get("url")]
    raw_summary = {
        key: payload.get(key)
        for key in ("id", "extractor", "webpage_url", "original_url", "upload_date", "timestamp")
        if payload.get(key) is not None
    }
    return {
        "source_type": "youtube",
        "source_name": "yt-dlp",
        "title": payload.get("title") or url,
        "content": payload.get("description") or payload.get("title") or "",
        "url": payload.get("webpage_url") or payload.get("original_url") or url,
        "id": str(payload.get("id") or sha256(url.encode("utf-8")).hexdigest()[:20]),
        "extra": {
            "provider_backend": "yt-dlp",
            "backend_attempts": [_attempt("yt-dlp", "success")],
            "views": payload.get("view_count"),
            "likes": payload.get("like_count"),
            "comments": payload.get("comment_count"),
            "duration": payload.get("duration"),
            "channel": payload.get("channel") or payload.get("uploader"),
            "published_at": payload.get("upload_date") or payload.get("timestamp"),
            "images": images,
            "raw": raw_summary,
        },
    }


def _github_repo_slug(url: str) -> str | None:
    match = re.search(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)", url)
    if not match:
        return None
    repo = match.group("repo").removesuffix(".git")
    return f"{match.group('owner')}/{repo}"


def _read_with_gh(url: str) -> dict[str, Any]:
    if not shutil.which("gh"):
        raise FeedgrabUnavailable("gh is not installed")
    repo = _github_repo_slug(url)
    if not repo:
        raise FeedgrabUnavailable("github url does not contain owner/repo")
    payload = _command_json(
        [
            "gh",
            "repo",
            "view",
            repo,
            "--json",
            "nameWithOwner,description,url,stargazerCount,forkCount,updatedAt,primaryLanguage",
        ],
        timeout=60,
    )
    language = payload.get("primaryLanguage")
    if isinstance(language, dict):
        language = language.get("name")
    name = payload.get("nameWithOwner") or repo
    return {
        "source_type": "github",
        "source_name": "gh",
        "title": name,
        "content": payload.get("description") or "",
        "url": payload.get("url") or url,
        "id": name,
        "extra": {
            "provider_backend": "gh",
            "backend_attempts": [_attempt("gh", "success")],
            "stars": payload.get("stargazerCount"),
            "forks": payload.get("forkCount"),
            "updated_at": payload.get("updatedAt"),
            "language": language,
            "raw": payload,
        },
    }


def _read_with_xhs_cli(url: str) -> dict[str, Any]:
    args, uses_default = _cli_args(("BEECLAW_XHS_CLI_CMD", "XHS_CLI_CMD"), ["xhs-cli", "--json"], url)
    if uses_default and not shutil.which("xhs-cli"):
        raise FeedgrabUnavailable("xhs-cli is not installed")
    payload = _command_json(args, timeout=90)
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    note_id = str(_first(payload, "note_id", "id", "aweme_id") or sha256(url.encode("utf-8")).hexdigest()[:20])
    content = _first(payload, "desc", "content", "text", "body") or ""
    source_url = _first(payload, "url", "source_url", "share_url") or url
    images = _list_value(_first(payload, "images", "image_urls") or extra.get("images"))
    videos = _list_value(_first(payload, "videos", "video_urls") or extra.get("videos"))
    return {
        "source_type": "xhs",
        "source_name": "xhs-cli",
        "title": _first(payload, "title", "note_title") or content[:80] or source_url,
        "content": content,
        "url": source_url,
        "id": note_id,
        "extra": {
            "provider_backend": "xhs-cli",
            "backend_attempts": [_attempt("xhs-cli", "success")],
            "likes": _first(payload, "likes", "like_count", "liked_count") or extra.get("likes"),
            "comments": _first(payload, "comments", "comment_count") or extra.get("comments"),
            "collects": _first(payload, "collects", "collect_count", "favorites") or extra.get("collects"),
            "author": _first(payload, "author", "nickname", "user") or extra.get("author"),
            "published_at": _first(payload, "published_at", "created_at", "time", "date") or extra.get("published_at"),
            "images": images,
            "videos": videos,
            "raw": {
                key: payload.get(key)
                for key in ("note_id", "id", "url", "source_url", "share_url")
                if payload.get(key) is not None
            },
        },
    }


def _read_with_rdt_cli(url: str) -> dict[str, Any]:
    args, uses_default = _cli_args(("BEECLAW_RDT_CLI_CMD", "RDT_CLI_CMD"), ["rdt-cli", "--json"], url)
    if uses_default and not shutil.which("rdt-cli"):
        raise FeedgrabUnavailable("rdt-cli is not installed")
    payload = _command_json(args, timeout=90)
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    permalink = _first(payload, "permalink")
    source_url = _first(payload, "url", "source_url")
    if permalink and isinstance(permalink, str) and permalink.startswith("/"):
        source_url = f"https://www.reddit.com{permalink}"
    source_url = source_url or url
    content = _first(payload, "selftext", "body", "content", "text") or ""
    images = _list_value(_first(payload, "images", "image_urls") or extra.get("images"))
    videos = _list_value(_first(payload, "videos", "video_urls") or extra.get("videos"))
    return {
        "source_type": "reddit",
        "source_name": "rdt-cli",
        "title": _first(payload, "title", "name") or source_url,
        "content": content,
        "url": source_url,
        "id": str(_first(payload, "id", "name") or sha256(source_url.encode("utf-8")).hexdigest()[:20]),
        "extra": {
            "provider_backend": "rdt-cli",
            "backend_attempts": [_attempt("rdt-cli", "success")],
            "likes": _first(payload, "score", "ups", "upvotes", "likes") or extra.get("likes"),
            "comments": _first(payload, "num_comments", "comments", "comment_count") or extra.get("comments"),
            "subreddit": _first(payload, "subreddit") or extra.get("subreddit"),
            "upvote_ratio": _first(payload, "upvote_ratio") or extra.get("upvote_ratio"),
            "published_at": _first(payload, "created_utc", "created_at", "date") or extra.get("published_at"),
            "images": images,
            "videos": videos,
            "raw": {
                key: payload.get(key)
                for key in ("id", "name", "permalink", "url", "subreddit")
                if payload.get(key) is not None
            },
        },
    }


def _read_url_with_backend(url: str, *, platform: str | None, backend_hint: str | None) -> Any:
    backend = (backend_hint or "").strip().lower()
    if backend in {"universal_reader", "feedgrab:universal_reader", "beeclaw:universal_reader"}:
        raise FeedgrabUnavailable("explicit universal_reader fallback")

    if platform == "youtube" and backend in {"", "auto", "yt-dlp", "ytdlp"}:
        return _read_with_ytdlp(url)
    if platform == "github" and backend in {"", "auto", "gh", "github_cli"}:
        return _read_with_gh(url)
    if platform == "xhs" and backend in {"", "auto", "xhs-cli", "xhs_cli"}:
        return _read_with_xhs_cli(url)
    if platform == "reddit" and backend in {"", "auto", "rdt-cli", "rdt_cli", "reddit_cli"}:
        return _read_with_rdt_cli(url)
    if platform == "rss" and backend in {"", "auto", "rss", "rss_parser", "rss-parser"}:
        return _read_with_rss_parser(url)
    if platform in {"", "web", None} and backend in {"", "auto", "jina", "jina reader", "jina_reader"}:
        return _read_with_jina(url)
    raise FeedgrabUnavailable(f"no specialized backend for platform={platform or 'web'}")


def _specialized_backend_name(platform: str | None, backend_hint: str | None) -> str | None:
    backend = (backend_hint or "").strip().lower()
    if platform == "youtube" and backend in {"", "auto", "yt-dlp", "ytdlp"}:
        return "yt-dlp"
    if platform == "github" and backend in {"", "auto", "gh", "github_cli"}:
        return "gh"
    if platform == "xhs" and backend in {"", "auto", "xhs-cli", "xhs_cli"}:
        return "xhs-cli"
    if platform == "reddit" and backend in {"", "auto", "rdt-cli", "rdt_cli", "reddit_cli"}:
        return "rdt-cli"
    if platform == "rss" and backend in {"", "auto", "rss", "rss_parser", "rss-parser"}:
        return "rss_parser"
    if platform in {"", "web", None} and backend in {"", "auto", "jina", "jina reader", "jina_reader"}:
        return "Jina Reader"
    return None


def read_url(url: str, platform: str | None = None, backend_hint: str | None = None) -> Any:
    """Read one URL through Beeclaw backends, falling back to upstream feedgrab."""
    platform_name = normalize_feedgrab_platform(platform) or infer_feedgrab_platform_from_url(url) or "web"
    backend_attempts: list[dict[str, Any]] = []
    try:
        return _read_url_with_backend(url, platform=platform_name, backend_hint=backend_hint)
    except FeedgrabUnavailable as exc:
        backend_name = _specialized_backend_name(platform_name, backend_hint)
        if backend_name:
            backend_attempts.append(_attempt(backend_name, "failed", str(exc)))
    except Exception as exc:
        backend_name = _specialized_backend_name(platform_name, backend_hint)
        if backend_name:
            backend_attempts.append(_attempt(backend_name, "failed", str(exc)))

    try:
        content = asyncio.run(_read_url_async(url))
        if backend_attempts:
            backend_attempts.append(_attempt("beeclaw:universal_reader", "success"))
            return _attach_backend_metadata(
                content,
                provider_backend="beeclaw:universal_reader",
                backend_attempts=backend_attempts,
            )
        return content
    except FeedgrabUnavailable:
        raise
    except Exception as exc:
        raise FeedgrabUnavailable(str(exc)) from exc
