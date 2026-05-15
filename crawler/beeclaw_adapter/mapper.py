from __future__ import annotations

from hashlib import sha256
from typing import Any

from crawler.models import ContentItem
from .platforms import normalize_feedgrab_platform


def _value(content: Any, key: str, default: Any = None) -> Any:
    if isinstance(content, dict):
        return content.get(key, default)
    return getattr(content, key, default)


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _stable_id(url: str, title: str, text: str) -> str:
    seed = url or title or text
    return sha256(seed.encode("utf-8")).hexdigest()[:20]


def _metric(extra: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = extra.get(key)
        if value in (None, ""):
            continue
        try:
            return int(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def _asset_from_value(value: Any, media_type: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"type": media_type, "url": value, "thumbnail_url": value if media_type == "image" else None}
    if not isinstance(value, dict):
        return None
    url = value.get("url") or value.get("media_url") or value.get("download_url") or value.get("thumbnail_url") or value.get("preview_image_url")
    if not url:
        return None
    asset = {
        "type": value.get("type") or media_type,
        "url": url,
    }
    for key in ("download_url", "thumbnail_url", "preview_image_url", "alt_text", "width", "height"):
        if value.get(key):
            target_key = "thumbnail_url" if key == "preview_image_url" else key
            asset[target_key] = value[key]
    return asset


def _media_assets(extra: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for value in extra.get("images") or []:
        asset = _asset_from_value(value, "image")
        if asset:
            assets.append(asset)
    for value in extra.get("videos") or []:
        asset = _asset_from_value(value, "video")
        if asset:
            assets.append(asset)
    for value in extra.get("media") or extra.get("media_assets") or []:
        asset = _asset_from_value(value, "media")
        if asset:
            assets.append(asset)
    seen = set()
    deduped = []
    for asset in assets:
        key = asset.get("download_url") or asset.get("url") or asset.get("thumbnail_url")
        if key and key not in seen:
            seen.add(key)
            deduped.append({k: v for k, v in asset.items() if v is not None})
    return deduped


def unified_content_to_item(content: Any) -> ContentItem:
    """Convert upstream feedgrab UnifiedContent or dict to Radar ContentItem."""
    if hasattr(content, "to_dict"):
        data = content.to_dict()
    elif isinstance(content, dict):
        data = dict(content)
    else:
        data = {
            "source_type": _enum_value(_value(content, "source_type")),
            "source_name": _value(content, "source_name"),
            "title": _value(content, "title"),
            "content": _value(content, "content"),
            "url": _value(content, "url"),
            "id": _value(content, "id"),
            "extra": _value(content, "extra", {}),
        }
    extra = data.get("extra") or {}
    provider_backend = data.get("provider_backend") or extra.get("provider_backend")
    source_type = _enum_value(data.get("source_type"))
    platform = normalize_feedgrab_platform(source_type) or source_type or "web"
    title = data.get("title")
    text = data.get("content") or data.get("text") or ""
    url = data.get("url") or ""
    original_id = (
        str(extra.get("tweet_id") or extra.get("id") or data.get("id") or "").strip()
        or _stable_id(url, title or "", text)
    )
    assets = _media_assets(extra)
    media_type = data.get("media_type")
    if not media_type:
        asset_types = {str(asset.get("type") or "").lower() for asset in assets}
        media_type = "video" if "video" in asset_types else ("image" if assets else "text")
    raw_payload = {**data}
    raw_payload.setdefault("source", "beeclaw:universal_reader")
    if provider_backend:
        raw_payload["provider_backend"] = provider_backend
    for key in ("backend_attempts", "selection_reason", "metrics_complete", "media_complete"):
        if key in extra and key not in raw_payload:
            raw_payload[key] = extra[key]
    return ContentItem(
        platform=platform,
        original_content_id=original_id,
        title=title,
        text=text,
        published_at=extra.get("created_at") or extra.get("published_at") or extra.get("date") or extra.get("publish_date") or data.get("published_at") or data.get("fetched_at"),
        url=url,
        view_count=_metric(extra, "views", "view_count"),
        like_count=_metric(extra, "likes", "like_count"),
        comment_count=_metric(extra, "replies", "reply_count", "comments", "comment_count"),
        share_count=_metric(extra, "retweets", "retweet_count", "reposts", "share_count"),
        media_type=_enum_value(media_type) or "text",
        language=extra.get("lang") or extra.get("language"),
        raw_payload=raw_payload,
        media_assets=assets,
    )
