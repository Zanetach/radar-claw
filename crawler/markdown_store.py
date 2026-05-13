from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ContentItem


def safe_path_part(value: str | None) -> str:
    text = (value or "unknown").strip()
    text = re.sub(r"[\\/:*?\"<>|#]+", "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip(".- ") or "unknown"


def content_uid(platform: str, original_content_id: str) -> str:
    return f"{platform}:{original_content_id}"


def published_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return value[:10]


def yaml_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def render_content_markdown(
    *,
    account: dict[str, Any],
    item: ContentItem,
    markdown_file_token: str | None = None,
    organize_status: str = "pending",
    review_status: str = "pending",
    publish_status: str = "pending",
    target_app: str | None = None,
) -> str:
    uid = content_uid(item.platform, item.original_content_id)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    title = item.title or item.text or item.original_content_id
    frontmatter = {
        "id": uid,
        "platform": item.platform,
        "account": account.get("account_name"),
        "category": account.get("category"),
        "source_url": item.url,
        "published_at": item.published_at,
        "markdown_file_token": markdown_file_token,
        "crawl_status": "success",
        "organize_status": organize_status,
        "review_status": review_status,
        "publish_status": publish_status,
        "target_app": target_app or "",
        "media_count": len(item.media_assets),
        "updated_at": now,
    }
    yaml = "\n".join(f"{key}: {yaml_scalar(value)}" for key, value in frontmatter.items())
    metrics = [
        f"- 阅读: {item.view_count if item.view_count is not None else 'N/A'}",
        f"- 点赞: {item.like_count if item.like_count is not None else 'N/A'}",
        f"- 评论: {item.comment_count if item.comment_count is not None else 'N/A'}",
        f"- 转发: {item.share_count if item.share_count is not None else 'N/A'}",
    ]
    media_lines = []
    for index, asset in enumerate(item.media_assets, start=1):
        media_url = asset.get("url") or asset.get("thumbnail_url") or ""
        if not media_url:
            continue
        media_type = asset.get("type") or asset.get("media_type") or "media"
        local_path = asset.get("local_path")
        local_text = f" 本地: {local_path}" if local_path else ""
        media_lines.append(f"{index}. [{media_type}]({media_url}){local_text}")
    media_section = "\n".join(media_lines) if media_lines else "无。"
    return f"""---
{yaml}
---

# {title}

## 来源

- 平台: {item.platform}
- 账号: {account.get("account_name") or ""}
- 分类: {account.get("category") or ""}
- 原文: {item.url or ""}
- 发布时间: {item.published_at or ""}

## 指标

{chr(10).join(metrics)}

## 原始内容

{item.text or item.title or ""}

## 媒体资源

{media_section}

## 整理摘要

待整理。

## 风险提示

待评估。

## 发布建议

待生成。
"""


def markdown_relative_path(account: dict[str, Any], item: ContentItem, *, status_folder: str = "01_待整理") -> Path:
    filename = f"{published_date(item.published_at)}-{safe_path_part(item.original_content_id)}.md"
    return Path(status_folder) / safe_path_part(account.get("category")) / item.platform / safe_path_part(account.get("account_name")) / filename


def update_frontmatter(markdown: str, updates: dict[str, Any]) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    if end < 0:
        return markdown
    frontmatter_text = markdown[4:end]
    body = markdown[end + 5 :]
    data: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    for key, value in updates.items():
        data[key] = yaml_scalar(value)
    new_frontmatter = "\n".join(f"{key}: {value}" for key, value in data.items())
    return f"---\n{new_frontmatter}\n---\n{body}"
