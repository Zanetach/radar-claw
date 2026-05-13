from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import re
import sqlite3
import time
import uuid
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from .cli import DEFAULT_DB, DEFAULT_EXCEL, account_rows, filter_fetch_result, upsert_person_account
from .account_enrichment import enrich_accounts
from .db import (
    connect,
    init_db,
    link_run_contents,
    log_failure,
    rows_to_dicts,
    save_fetch_result,
    save_fetch_result_with_ids,
    upsert_accounts,
)
from .import_accounts import load_accounts_from_excel
from .providers import ProviderError, build_provider, provider_mode_capabilities, webbridge_status
from .feedgrab_adapter import FeedgrabUnavailable, feedgrab_health, provider_catalog, read_url, unified_content_to_item
from .x_intel import fetch_bestblogs_accounts, upsert_x_intel_accounts
from .media_downloader import DEFAULT_MEDIA_DIR, download_fetch_result_media
from .models import FetchResult, utc_now_iso


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
MEDIA_DIR = ROOT / DEFAULT_MEDIA_DIR
EDITABLE_ACCOUNT_FIELDS = {
    "account_handle",
    "account_url",
    "threshold_views",
    "threshold_engagement_rate",
    "enabled",
    "fetch_interval_minutes",
}


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, text: str, content_type: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def parse_int(value: str | None, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    return int(value)


def parse_bool(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.lower() in {"1", "true", "yes", "on"} else 0
    return 0


def safe_upload_name(name: str) -> str:
    base = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", base).strip("-") or "upload"


def hermes_status() -> dict:
    hermes_home = Path.home() / ".hermes"
    config_path = hermes_home / "config.yaml"
    skill_path = hermes_home / "skills" / "radar-data-collection" / "SKILL.md"
    legacy_skill_path = hermes_home / "skills" / "radar-content-workflow" / "SKILL.md"
    mcp_server_path = ROOT / "tools" / "radar_mcp_server.py"
    config_text = ""
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError:
        pass
    return {
        "home": str(hermes_home),
        "configPath": str(config_path),
        "installed": hermes_home.exists(),
        "radarMcpConfigured": "mcp_servers:" in config_text and "radar:" in config_text and "radar_mcp_server.py" in config_text,
        "skillInstalled": skill_path.exists() or legacy_skill_path.exists(),
        "skillPath": str(skill_path if skill_path.exists() else legacy_skill_path),
        "mcpServerFile": str(mcp_server_path),
        "mcpServerFileExists": mcp_server_path.exists(),
        "runCommand": "hermes --skills radar-data-collection",
    }


def bool_body(body: dict, key: str, default: bool = False) -> bool:
    if key not in body:
        return default
    return bool(body.get(key))


def compact_media_assets(media_assets_json: str | None) -> list[dict]:
    if not media_assets_json:
        return []
    try:
        parsed = json.loads(media_assets_json)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def safe_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def camel_bool(value: object) -> bool:
    return bool(parse_bool(value))


def strategy_to_payload(row: dict) -> dict:
    return {
        "strategyId": row["id"],
        "sourceType": "account",
        "platform": row["platform"],
        "mode": row["mode"],
        "dateRange": row["date_range"],
        "category": row.get("category") or "",
        "maxResults": row["max_results"],
        "minViews": row.get("min_views"),
        "language": row["language"],
        "includeOriginal": camel_bool(row["include_original"]),
        "includeQuotes": camel_bool(row["include_quotes"]),
        "includeReplies": camel_bool(row["include_replies"]),
        "includeRetweets": camel_bool(row["include_retweets"]),
        "downloadImages": camel_bool(row["download_images"]),
        "downloadVideos": camel_bool(row["download_videos"]),
        "downloadMedia": camel_bool(row["download_images"]) or camel_bool(row["download_videos"]),
        "mediaOnly": camel_bool(row["media_only"]),
        "translateAfterCrawl": camel_bool(row["translate_after_crawl"]),
        "ocrImages": camel_bool(row["ocr_images"]),
        "dedupePolicy": row["dedupe_policy"],
    }


def content_markdown(row: sqlite3.Row | dict, *, fallback_title: str | None = None) -> str:
    data = dict(row)
    media = compact_media_assets(data.get("media_assets_json"))
    media_lines = []
    for index, asset in enumerate(media, start=1):
        url = asset.get("local_url") or asset.get("url") or asset.get("thumbnail_url") or ""
        media_lines.append(f"{index}. {asset.get('type') or 'media'} - {url}")
    title = data.get("organized_title") or data.get("title") or fallback_title or data.get("original_content_id") or "未命名内容"
    original = data.get("original_text") or data.get("text") or ""
    translated = data.get("translated_text_zh") or "待 Hermes 内容整理 Agent 翻译。"
    ocr_original = data.get("ocr_text_original") or "待 OCR。"
    ocr_zh = data.get("ocr_text_zh") or "待 Hermes 内容整理 Agent 翻译。"
    summary = data.get("organized_summary") or ""
    quality = data.get("quality_reason") or "待 Hermes 内容整理 Agent 评估。"
    category = data.get("content_category") or data.get("category") or ""
    notes = data.get("organize_notes") or ""
    return "\n".join(
        [
            "---",
            f"id: {data.get('platform')}:{data.get('original_content_id')}",
            f"platform: {data.get('platform')}",
            f"account: {data.get('account_name') or ''}",
            f"category: {category}",
            f"source_url: {data.get('url') or ''}",
            f"translation_status: {data.get('translation_status') or 'pending'}",
            f"organize_status: {data.get('organize_status') or 'pending'}",
            f"review_status: {data.get('review_status') or 'raw'}",
            f"publish_status: {data.get('publish_status') or 'not_ready'}",
            "---",
            "",
            f"# {title}",
            "",
            "## 原文",
            original,
            "",
            "## 中文翻译",
            translated,
            "",
            "## 图片 OCR 原文",
            ocr_original,
            "",
            "## 图片 OCR 中文",
            ocr_zh,
            "",
            "## 摘要",
            summary or "待整理。",
            "",
            "## 质量建议",
            quality,
            "",
            "## 分类",
            category or "待分类。",
            "",
            "## 媒体",
            "\n".join(media_lines) if media_lines else "- 无",
            "",
            "## 整理备注",
            notes or "-",
            "",
            "## 原文链接",
            data.get("url") or "-",
        ]
    )


def writable_path(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".radar-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


URL_PATTERN = re.compile(r"https?://[^\s，。)）]+", flags=re.IGNORECASE)


def extract_urls_from_prompt(text: str) -> list[str]:
    return [match.group(0).rstrip(".,;，。；") for match in URL_PATTERN.finditer(text)]


def infer_platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "x"
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host.endswith("xiaohongshu.com") or host.endswith("xhslink.com"):
        return "xhs"
    if host.endswith("facebook.com") or host.endswith("fb.watch"):
        return "facebook"
    if url.lower().endswith((".rss", ".xml")):
        return "rss"
    return "web"


def infer_platform_from_prompt(prompt: str, lower: str, urls: list[str]) -> str:
    if any(token in prompt for token in ["小红书", "红书"]) or "xiaohongshu" in lower or "xhs" in lower:
        return "xhs"
    if "facebook" in lower or re.search(r"\bfb\b", lower):
        return "facebook"
    if "youtube" in lower or "油管" in prompt:
        return "youtube"
    if "instagram" in lower or "ins" in lower:
        return "instagram"
    if "linkedin" in lower or "领英" in prompt:
        return "linkedin"
    if urls:
        return infer_platform_from_url(urls[0])
    return "x"


def extract_keyword_query(prompt: str, platform: str) -> str:
    patterns = [
        r"关于\s*(.+?)\s*(?:的|相关|热门|内容|帖子|笔记|post|posts)",
        r"(?:关键词|主题|话题)\s*[:：]\s*(.+?)(?:[，。,;；]|$)",
        r"(?:搜索|采集|抓取|获取)\s*(.+?)(?:[，。,;；]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE)
        if not match:
            continue
        query = match.group(1).strip(" “”\"'，。；;")
        query = re.sub(
            r"^(?:小红书|facebook|twitter|推特|x\s*平台|X\s*平台|微博|公众号|上)\s*(?:上)?\s*",
            "",
            query,
        ).strip()
        if query:
            return query
    return platform


def search_feedgrab_xhs_keyword(*, keyword: str, sort: str, note_type: str, max_results: int) -> dict:
    try:
        from feedgrab.fetchers.xhs_search_notes import search_xhs_keyword
    except Exception as exc:  # pragma: no cover - depends on optional feedgrab install.
        raise FeedgrabUnavailable(f"feedgrab xhs search unavailable: {exc}") from exc
    return search_xhs_keyword(
        keyword=keyword,
        sort=sort,
        note_type=note_type,
        max_results=max_results,
        save_notes=False,
        skip_summary=True,
    )


def xhs_note_to_item(note: dict, *, query: str) -> object:
    images = note.get("images") or []
    videos = note.get("videos") or []
    note_type = note.get("note_type") or ("video" if videos else ("image" if images else "text"))
    content = {
        "source_type": "xhs",
        "source_name": note.get("author") or note.get("nickname") or "小红书",
        "title": note.get("title") or note.get("desc") or "",
        "content": note.get("content") or note.get("desc") or note.get("summary") or "",
        "url": note.get("url") or "",
        "id": note.get("id") or note.get("note_id") or note.get("url") or "",
        "media_type": "video" if note_type == "video" else ("image" if images else "text"),
        "extra": {
            "id": note.get("id") or note.get("note_id") or "",
            "author_url": note.get("author_url") or "",
            "likes": note.get("likes") or note.get("like_count") or 0,
            "collects": note.get("collects") or 0,
            "comments": note.get("comments") or note.get("comment_count") or 0,
            "share_count": note.get("share_count") or 0,
            "note_type": note_type,
            "images": images,
            "videos": videos,
            "date": note.get("date") or note.get("published_at") or "",
            "search_keyword": query,
        },
    }
    return unified_content_to_item(content)


def extract_identifier_from_prompt(text: str) -> str | None:
    patterns = [
        r"https?://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_./?=&%-]+",
        r"@[A-Za-z0-9_]{1,15}",
        r"(?:账号|账户|handle|用户)\s*[:：]?\s*([A-Za-z0-9_]{1,15})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1) if match.groups() else match.group(0)
        if value.lower() in {"x", "twitter"}:
            continue
        return value
    return None


def parse_chat_prompt(text: str) -> dict:
    prompt = text.strip()
    lower = prompt.lower()
    urls = extract_urls_from_prompt(prompt)
    identifier = extract_identifier_from_prompt(prompt)
    if identifier and identifier.startswith("@"):
        identifier = identifier[1:]
    platform = infer_platform_from_prompt(prompt, lower, urls)
    if urls and not (identifier and platform == "x"):
        source_type = "url"
    elif identifier:
        source_type = "account"
    else:
        source_type = "keyword"

    is_scheduled = any(token in prompt for token in ["定时", "每天", "每小时", "每隔", "每周", "定期"])
    date_range = "7d"
    if "24小时" in prompt or "24 小时" in prompt or "一天" in prompt:
        date_range = "24h"
    if "最近一周" in prompt or "7天" in prompt or "7 天" in prompt:
        date_range = "7d"

    mode = "auto" if platform == "x" else "feedgrab"
    if "rss" in lower or "免费" in prompt:
        mode = "feedgrab:x_rss"
    elif "api" in lower:
        mode = "api"
    elif "xmcp" in lower or "mcp" in lower or "生产" in prompt:
        mode = "feedgrab:x_mcp" if platform == "x" else "feedgrab"
    elif "chrome" in lower or "浏览器" in prompt or "browser" in lower:
        mode = "chrome-session"

    include_retweets = "转发" in prompt and not any(token in prompt for token in ["不要转发", "排除转发", "不抓转发"])
    include_replies = "回复" in prompt and not any(token in prompt for token in ["不要回复", "排除回复", "不抓回复"])
    include_quotes = "引用" in prompt or "quote" in lower
    media_only = any(token in prompt for token in ["只要图片", "只带媒体", "仅带媒体", "图片视频"])
    translate = any(token in prompt for token in ["翻译", "中文"])
    ocr = "ocr" in lower or any(token in prompt for token in ["图片文字", "图中文字"])

    max_results_match = re.search(r"(\d+)\s*(?:条|篇|个)", prompt)
    max_results = int(max_results_match.group(1)) if max_results_match else 20
    max_results = max(1, min(max_results, 100))

    task = {
        "sourceType": source_type,
        "platform": platform,
        "identifier": identifier or "",
        "mode": mode,
        "dateRange": date_range,
        "maxResults": max_results,
        "includeOriginal": True,
        "includeQuotes": include_quotes,
        "includeReplies": include_replies,
        "includeRetweets": include_retweets,
        "downloadImages": True,
        "downloadVideos": True,
        "downloadMedia": True,
        "mediaOnly": media_only,
        "translateAfterCrawl": translate,
        "ocrImages": ocr,
        "language": "all",
        "category": "Chat采集",
        "schedule": "定时任务" if is_scheduled else "",
        "prompt": prompt,
    }
    if urls:
        task["url"] = urls[0]
        task["urls"] = urls
        if source_type == "url":
            task["identifier"] = urls[0]
    if source_type == "keyword":
        task["query"] = extract_keyword_query(prompt, platform)
    return task


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_values(path: Path, updates: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value


def sync_xmcp_env(root_env: Path, xmcp_env: Path) -> None:
    values = read_env_file(root_env)
    updates = {
        "X_AUTH_MODE": "bearer",
        "X_OAUTH_CONSUMER_KEY": values.get("X_API_KEY", ""),
        "X_OAUTH_CONSUMER_SECRET": values.get("X_API_SECRET", ""),
        "X_BEARER_TOKEN": values.get("X_BEARER_TOKEN", ""),
        "X_OAUTH_CALLBACK_HOST": "127.0.0.1",
        "X_OAUTH_CALLBACK_PORT": "8976",
        "X_OAUTH_CALLBACK_PATH": "/oauth/callback",
        "X_OAUTH_CALLBACK_TIMEOUT": "300",
        "X_API_BASE_URL": "https://api.x.com",
        "X_API_TIMEOUT": "30",
        "X_API_DEBUG": "1",
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": "8000",
        "X_API_TOOL_ALLOWLIST": "getUsersByUsername,getUsersPosts,getPostsById,getPostsByIds,searchPostsRecent,getMediaByMediaKey,getMediaByMediaKeys,getUsage",
    }
    xmcp_env.parent.mkdir(parents=True, exist_ok=True)
    if not xmcp_env.exists():
        xmcp_env.write_text("# Generated from Radar system config. Do not commit.\n", encoding="utf-8")
    write_env_values(xmcp_env, updates)


class RadarAdminHandler(BaseHTTPRequestHandler):
    db_path: Path = DEFAULT_DB
    excel_path: Path = DEFAULT_EXCEL

    def log_message(self, format: str, *args: object) -> None:
        return

    def conn(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        init_db(conn)
        return conn

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def read_upload(self) -> tuple[str, bytes]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("multipart_form_required")
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        field = form["file"] if "file" in form else None
        if field is None or not getattr(field, "filename", None):
            raise ValueError("file_required")
        return safe_upload_name(field.filename), field.file.read()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_post(parsed.path, parse_qs(parsed.query))
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_patch(parsed.path)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def serve_static(self, path: str) -> None:
        if path.startswith("/data/media/"):
            self.serve_media(path)
            return
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        file_path = (WEB_DIR / relative).resolve()
        if not str(file_path).startswith(str(WEB_DIR.resolve())) or not file_path.exists() or file_path.is_dir():
            json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "text/plain"
        if content_type.startswith("text/") or file_path.suffix in {".js", ".css"}:
            text_response(self, HTTPStatus.OK, file_path.read_text(encoding="utf-8"), content_type)
            return
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_media(self, path: str) -> None:
        relative = path.lstrip("/")
        file_path = (ROOT / relative).resolve()
        if not str(file_path).startswith(str(MEDIA_DIR.resolve())) or not file_path.exists() or file_path.is_dir():
            json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        handlers = {
            "/api/summary": self.api_summary,
            "/api/accounts": self.api_accounts,
            "/api/contents": self.api_contents,
            "/api/media": self.api_media,
            "/api/organized": self.api_organized,
            "/api/publishable": self.api_publishable,
            "/api/failures": self.api_failures,
            "/api/config": self.api_config,
            "/api/config/diagnostics": self.api_config_diagnostics,
            "/api/providers": self.api_providers,
            "/api/providers/health": self.api_providers_health,
            "/api/runs": self.api_runs,
            "/api/employee-tasks": self.api_runs,
            "/api/strategies": self.api_strategies,
            "/api/collection-strategies": self.api_strategies,
            "/api/collection-tasks": self.api_runs,
            "/api/raw-contents": self.api_contents,
            "/api/raw-contents/export": self.api_export_raw_dataset,
        }
        handler = handlers.get(path)
        if handler is None and path.startswith("/api/contents/"):
            content_id = path.removeprefix("/api/contents/").strip("/")
            if content_id.isdigit():
                json_response(self, HTTPStatus.OK, self.api_content_detail(int(content_id)))
                return
        if handler is None and path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/").strip("/")
            if run_id and "/" not in run_id:
                json_response(self, HTTPStatus.OK, self.api_run_detail(run_id))
                return
        if handler is None and path.startswith("/api/collection-tasks/"):
            run_id = path.removeprefix("/api/collection-tasks/").strip("/")
            if run_id and "/" not in run_id:
                json_response(self, HTTPStatus.OK, self.api_run_detail(run_id))
                return
        if handler is None and path.startswith("/api/raw-contents/"):
            content_id = path.removeprefix("/api/raw-contents/").strip("/")
            if content_id.isdigit():
                json_response(self, HTTPStatus.OK, self.api_content_detail(int(content_id)))
                return
        if handler is None:
            json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        json_response(self, HTTPStatus.OK, handler(query))

    def handle_api_post(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/import-excel":
            json_response(self, HTTPStatus.OK, self.api_import_excel())
            return
        if path == "/api/import-x-intel":
            json_response(self, HTTPStatus.OK, self.api_import_x_intel(self.read_json()))
            return
        if path == "/api/enrich-accounts":
            json_response(self, HTTPStatus.OK, self.api_enrich_accounts(self.read_json()))
            return
        if path == "/api/crawl":
            json_response(self, HTTPStatus.OK, self.api_crawl(self.read_json()))
            return
        if path == "/api/crawl-person":
            json_response(self, HTTPStatus.OK, self.api_crawl_person(self.read_json()))
            return
        if path == "/api/runs/crawl":
            json_response(self, HTTPStatus.OK, self.api_run_crawl(self.read_json()))
            return
        if path == "/api/collection-tasks":
            json_response(self, HTTPStatus.OK, self.api_create_collection_task(self.read_json()))
            return
        if path == "/api/employee-tasks":
            json_response(self, HTTPStatus.OK, self.api_create_employee_task(self.read_json()))
            return
        if path == "/api/strategies":
            json_response(self, HTTPStatus.OK, self.api_create_strategy(self.read_json()))
            return
        if path == "/api/agent/chat":
            json_response(self, HTTPStatus.OK, self.api_agent_chat(self.read_json()))
            return
        if path == "/api/agent/upload":
            try:
                filename, data = self.read_upload()
                json_response(self, HTTPStatus.OK, self.api_agent_upload(filename, data))
            except ValueError as exc:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if path == "/api/organize":
            json_response(self, HTTPStatus.OK, self.api_organize(self.read_json()))
            return
        if path == "/api/organize/save":
            json_response(self, HTTPStatus.OK, self.api_save_organized_content(self.read_json()))
            return
        if path == "/api/translation/save":
            json_response(self, HTTPStatus.OK, self.api_save_translation_result(self.read_json()))
            return
        if path == "/api/publish":
            json_response(self, HTTPStatus.OK, self.api_publish(self.read_json()))
            return
        if path in {"/api/raw-contents/handoff/organizer", "/api/raw-contents/handoff/beemax"}:
            json_response(self, HTTPStatus.OK, self.api_handoff_to_organizer(self.read_json()))
            return
        if path.startswith("/api/runs/") and path.endswith("/status"):
            run_id = path.removeprefix("/api/runs/").removesuffix("/status").strip("/")
            if run_id:
                json_response(self, HTTPStatus.OK, self.api_update_run_status(run_id, self.read_json()))
                return
        if path.startswith("/api/runs/") and path.endswith("/retry"):
            run_id = path.removeprefix("/api/runs/").removesuffix("/retry").strip("/")
            if run_id:
                json_response(self, HTTPStatus.OK, self.api_run_retry(run_id))
                return
        if path == "/api/config":
            json_response(self, HTTPStatus.OK, self.api_save_config(self.read_json()))
            return
        if path == "/api/config/xmcp":
            json_response(self, HTTPStatus.OK, self.api_save_xmcp_config(self.read_json()))
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def handle_api_patch(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "accounts"]:
            json_response(self, HTTPStatus.OK, self.api_update_account(int(parts[2]), self.read_json()))
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def api_summary(self, query: dict[str, list[str]]) -> dict:
        conn = self.conn()
        account_count = conn.execute("SELECT COUNT(*) FROM source_accounts").fetchone()[0]
        enabled_count = conn.execute("SELECT COUNT(*) FROM source_accounts WHERE enabled = 1").fetchone()[0]
        content_count = conn.execute("SELECT COUNT(*) FROM source_contents").fetchone()[0]
        failure_count = conn.execute("SELECT COUNT(*) FROM crawl_failures").fetchone()[0]
        qualified_count = conn.execute(
            "SELECT COUNT(*) FROM source_contents WHERE qualification_status = 'qualified'"
        ).fetchone()[0]
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM source_contents WHERE qualification_status = 'metrics_pending'"
        ).fetchone()[0]
        platforms = rows_to_dicts(
            conn.execute(
                """
                SELECT platform, COUNT(*) AS accounts,
                       SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled
                FROM source_accounts
                GROUP BY platform
                ORDER BY platform
                """
            )
        )
        categories = rows_to_dicts(
            conn.execute(
                """
                SELECT category, COUNT(*) AS accounts
                FROM source_accounts
                GROUP BY category
                ORDER BY accounts DESC, category
                """
            )
        )
        latest_run = rows_to_dicts(
            conn.execute(
                """
                SELECT id, source_type, platform, mode, status, saved_count,
                       failure_count, media_downloaded, started_at, finished_at
                FROM crawl_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
        )
        return {
            "accounts": account_count,
            "enabledAccounts": enabled_count,
            "contents": content_count,
            "qualifiedContents": qualified_count,
            "pendingContents": pending_count,
            "failures": failure_count,
            "platforms": platforms,
            "categories": categories,
            "latestRun": latest_run[0] if latest_run else None,
        }

    def api_accounts(self, query: dict[str, list[str]]) -> dict:
        platform = (query.get("platform") or [""])[0]
        category = (query.get("category") or [""])[0]
        status = (query.get("status") or [""])[0]
        search = (query.get("search") or [""])[0]
        limit = parse_int((query.get("limit") or ["200"])[0], 200)
        sql = """
            SELECT a.*,
                   COUNT(c.id) AS content_count,
                   MAX(c.fetched_at) AS latest_content_at
            FROM source_accounts a
            LEFT JOIN source_contents c ON c.source_account_id = a.id
            WHERE 1 = 1
        """
        params: list[object] = []
        if platform:
            sql += " AND a.platform = ?"
            params.append(platform)
        if category:
            sql += " AND a.category = ?"
            params.append(category)
        if status == "enabled":
            sql += " AND a.enabled = 1"
        elif status == "disabled":
            sql += " AND a.enabled = 0"
        elif status == "issue":
            sql += " AND a.data_quality_issue IS NOT NULL"
        if search:
            sql += " AND (a.account_name LIKE ? OR a.radar_name LIKE ? OR a.original_account LIKE ?)"
            token = f"%{search}%"
            params.extend([token, token, token])
        sql += " GROUP BY a.id ORDER BY a.platform, a.source_row_number, a.account_name LIMIT ?"
        params.append(limit)
        conn = self.conn()
        return {"items": rows_to_dicts(conn.execute(sql, params))}

    def api_strategies(self, query: dict[str, list[str]]) -> dict:
        conn = self.conn()
        platform = (query.get("platform") or [""])[0]
        sql = "SELECT * FROM crawl_strategies WHERE enabled = 1"
        params: list[object] = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY is_builtin DESC, platform, name"
        rows = rows_to_dicts(conn.execute(sql, params))
        for row in rows:
            row["payload"] = strategy_to_payload(row)
            row["params"] = json.loads(row.get("params_json") or "{}")
        return {"items": rows}

    def api_create_strategy(self, body: dict) -> dict:
        name = (body.get("name") or "").strip()
        if not name:
            return {"error": "name_required"}
        strategy_id = (body.get("id") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"strategy-{uuid.uuid4().hex[:8]}").strip()
        platform = (body.get("platform") or "x").strip().lower()
        mode = (body.get("mode") or "xmcp").strip()
        now_payload = {
            "source": "user",
            "raw": {key: value for key, value in body.items() if key not in {"id", "name"}},
        }
        conn = self.conn()
        conn.execute(
            """
            INSERT INTO crawl_strategies (
                id, name, description, platform, mode, date_range, category,
                max_results, min_views, language, include_original, include_quotes,
                include_replies, include_retweets, download_images, download_videos,
                media_only, translate_after_crawl, ocr_images, dedupe_policy,
                is_builtin, enabled, params_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                platform = excluded.platform,
                mode = excluded.mode,
                date_range = excluded.date_range,
                category = excluded.category,
                max_results = excluded.max_results,
                min_views = excluded.min_views,
                language = excluded.language,
                include_original = excluded.include_original,
                include_quotes = excluded.include_quotes,
                include_replies = excluded.include_replies,
                include_retweets = excluded.include_retweets,
                download_images = excluded.download_images,
                download_videos = excluded.download_videos,
                media_only = excluded.media_only,
                translate_after_crawl = excluded.translate_after_crawl,
                ocr_images = excluded.ocr_images,
                dedupe_policy = excluded.dedupe_policy,
                enabled = 1,
                params_json = excluded.params_json,
                updated_at = excluded.updated_at
            """,
            (
                strategy_id,
                name,
                body.get("description") or "",
                platform,
                mode,
                body.get("dateRange") or body.get("date_range") or "7d",
                body.get("category") or None,
                int(body.get("maxResults") or body.get("max_results") or 20),
                parse_int(str(body.get("minViews") or body.get("min_views") or ""), None),
                body.get("language") or "all",
                parse_bool(body.get("includeOriginal", True)),
                parse_bool(body.get("includeQuotes", True)),
                parse_bool(body.get("includeReplies", False)),
                parse_bool(body.get("includeRetweets", False)),
                parse_bool(body.get("downloadImages", True)),
                parse_bool(body.get("downloadVideos", True)),
                parse_bool(body.get("mediaOnly", False)),
                parse_bool(body.get("translateAfterCrawl", False)),
                parse_bool(body.get("ocrImages", False)),
                body.get("dedupePolicy") or body.get("dedupe_policy") or "platform_original_content_id",
                json.dumps(now_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
        row = rows_to_dicts(conn.execute("SELECT * FROM crawl_strategies WHERE id = ?", (strategy_id,)))[0]
        row["payload"] = strategy_to_payload(row)
        return {"item": row}

    def apply_strategy(self, conn: sqlite3.Connection, body: dict) -> dict:
        strategy_id = body.get("strategyId") or body.get("strategy_id")
        if not strategy_id:
            return body
        row = conn.execute("SELECT * FROM crawl_strategies WHERE id = ? AND enabled = 1", (strategy_id,)).fetchone()
        if row is None:
            return body
        strategy_body = strategy_to_payload(dict(row))
        merged = {**strategy_body, **body}
        merged["strategyId"] = strategy_id
        return merged

    def api_contents(self, query: dict[str, list[str]]) -> dict:
        conn = self.conn()
        platform = (query.get("platform") or [""])[0]
        qualification = (query.get("qualification") or [""])[0]
        run_id = (query.get("runId") or [""])[0]
        has_media = (query.get("hasMedia") or [""])[0]
        media_type = (query.get("mediaType") or [""])[0]
        limit = parse_int((query.get("limit") or ["100"])[0], 100)
        sql = """
            SELECT c.*, a.account_name, a.category, a.radar_name
            FROM source_contents c
            JOIN source_accounts a ON a.id = c.source_account_id
            WHERE 1 = 1
        """
        params: list[object] = []
        if platform:
            sql += " AND c.platform = ?"
            params.append(platform)
        if qualification:
            sql += " AND c.qualification_status = ?"
            params.append(qualification)
        if run_id:
            linked = conn.execute(
                "SELECT 1 FROM crawl_run_contents WHERE run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
            if linked is not None:
                sql += " AND c.id IN (SELECT content_id FROM crawl_run_contents WHERE run_id = ?)"
                params.append(run_id)
            else:
                run = conn.execute("SELECT started_at, finished_at FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
                if run is not None:
                    sql += " AND c.fetched_at >= ?"
                    params.append(run["started_at"])
                    if run["finished_at"]:
                        sql += " AND c.fetched_at <= ?"
                        params.append(run["finished_at"])
        if has_media == "1":
            sql += " AND c.media_assets_json IS NOT NULL AND c.media_assets_json != '[]'"
        if media_type:
            sql += " AND c.media_type = ?"
            params.append(media_type)
        sql += " ORDER BY COALESCE(c.published_at, c.fetched_at) DESC LIMIT ?"
        params.append(limit)
        rows = rows_to_dicts(conn.execute(sql, params))
        for row in rows:
            row["feishu_url"] = None
        return {"items": rows}

    def api_content_detail(self, content_id: int) -> dict:
        conn = self.conn()
        row = conn.execute(
            """
            SELECT c.*, a.account_name, a.category, a.radar_name
            FROM source_contents c
            JOIN source_accounts a ON a.id = c.source_account_id
            WHERE c.id = ?
            """,
            (content_id,),
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        item = dict(row)
        item["media_assets"] = compact_media_assets(item.get("media_assets_json"))
        item["markdown_preview"] = item.get("organized_markdown") or content_markdown(item)
        return item

    def raw_content_contract_item(self, row: dict) -> dict:
        return {
            "content_id": row["id"],
            "platform": row["platform"],
            "provider": row.get("provider") or safe_json(row.get("raw_payload_json")).get("source"),
            "source_account": row.get("account_name"),
            "category": row.get("category"),
            "radar_name": row.get("radar_name"),
            "original_content_id": row.get("original_content_id"),
            "source_url": row.get("url"),
            "title": row.get("title"),
            "original_text": row.get("original_text") or row.get("text"),
            "published_at": row.get("published_at"),
            "language": row.get("language"),
            "metrics": {
                "views": row.get("view_count"),
                "likes": row.get("like_count"),
                "comments": row.get("comment_count"),
                "reposts": row.get("share_count"),
            },
            "media_type": row.get("media_type"),
            "media_assets": compact_media_assets(row.get("media_assets_json")),
            "qualification_status": row.get("qualification_status"),
            "organize_status": row.get("organize_status"),
            "review_status": row.get("review_status"),
            "publish_status": row.get("publish_status"),
            "raw_payload": safe_json(row.get("raw_payload_json")),
        }

    def dataset_markdown(self, items: list[dict]) -> str:
        parts = ["# Radar 原始采集数据集", ""]
        for item in items:
            parts.extend(
                [
                    f"## {item.get('title') or item.get('original_content_id') or item.get('content_id')}",
                    "",
                    f"- 平台: {item.get('platform') or ''}",
                    f"- Provider: {item.get('provider') or ''}",
                    f"- 账号: {item.get('source_account') or ''}",
                    f"- 原文链接: {item.get('source_url') or ''}",
                    f"- 发布时间: {item.get('published_at') or ''}",
                    f"- 指标: views={item['metrics'].get('views')}, likes={item['metrics'].get('likes')}, comments={item['metrics'].get('comments')}, reposts={item['metrics'].get('reposts')}",
                    "",
                    "### 原文",
                    "",
                    item.get("original_text") or "",
                    "",
                ]
            )
            media_assets = item.get("media_assets") or []
            if media_assets:
                parts.extend(["### 媒体", ""])
                for asset in media_assets:
                    parts.append(f"- {asset.get('type') or 'media'}: {asset.get('local_path') or asset.get('url') or asset.get('download_url') or ''}")
                parts.append("")
        return "\n".join(parts).strip() + "\n"

    def api_export_raw_dataset(self, query: dict[str, list[str]]) -> dict:
        output_format = ((query.get("format") or ["json"])[0] or "json").lower()
        raw_ids = (query.get("contentIds") or query.get("ids") or [""])[0]
        ids = [int(part.strip()) for part in raw_ids.split(",") if part.strip().isdigit()]
        conn = self.conn()
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = rows_to_dicts(
                conn.execute(
                    f"""
                    SELECT c.*, a.account_name, a.category, a.radar_name
                    FROM source_contents c
                    JOIN source_accounts a ON a.id = c.source_account_id
                    WHERE c.id IN ({placeholders})
                    ORDER BY COALESCE(c.published_at, c.fetched_at) DESC
                    """,
                    ids,
                )
            )
        else:
            rows = self.api_contents(query)["items"]
        items = [self.raw_content_contract_item(row) for row in rows]
        payload: dict[str, object] = {
            "format": output_format,
            "count": len(items),
            "items": items,
        }
        if output_format == "jsonl":
            payload["dataset_jsonl"] = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items)
        elif output_format in {"md", "markdown"}:
            payload["dataset_markdown"] = self.dataset_markdown(items)
        return payload

    def api_organized(self, query: dict[str, list[str]]) -> dict:
        limit = parse_int((query.get("limit") or ["100"])[0], 100)
        conn = self.conn()
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT c.*, a.account_name, a.category, a.radar_name
                FROM source_contents c
                JOIN source_accounts a ON a.id = c.source_account_id
                WHERE c.organize_status = 'organized'
                ORDER BY COALESCE(c.updated_at, c.fetched_at) DESC
                LIMIT ?
                """,
                (limit,),
            )
        )
        return {"items": rows}

    def api_publishable(self, query: dict[str, list[str]]) -> dict:
        limit = parse_int((query.get("limit") or ["100"])[0], 100)
        conn = self.conn()
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT c.*, a.account_name, a.category, a.radar_name
                FROM source_contents c
                JOIN source_accounts a ON a.id = c.source_account_id
                WHERE c.organize_status = 'organized'
                  AND c.review_status = 'approved'
                  AND c.publish_status IN ('pending', 'failed')
                ORDER BY COALESCE(c.updated_at, c.fetched_at) DESC
                LIMIT ?
                """,
                (limit,),
            )
        )
        return {"items": rows}

    def api_media(self, query: dict[str, list[str]]) -> dict:
        platform = (query.get("platform") or [""])[0]
        media_type = (query.get("mediaType") or [""])[0]
        account = (query.get("account") or [""])[0]
        limit = parse_int((query.get("limit") or ["120"])[0], 120)
        sql = """
            SELECT c.id, c.platform, c.original_content_id, c.title, c.text, c.url,
                   c.published_at, c.media_type, c.media_assets_json,
                   a.account_name, a.category
            FROM source_contents c
            JOIN source_accounts a ON a.id = c.source_account_id
            WHERE c.media_assets_json IS NOT NULL AND c.media_assets_json != '[]'
        """
        params: list[object] = []
        if platform:
            sql += " AND c.platform = ?"
            params.append(platform)
        if media_type:
            sql += " AND c.media_type = ?"
            params.append(media_type)
        if account:
            sql += " AND a.account_name LIKE ?"
            params.append(f"%{account}%")
        sql += " ORDER BY COALESCE(c.published_at, c.fetched_at) DESC LIMIT ?"
        params.append(limit)
        conn = self.conn()
        items = []
        for row in rows_to_dicts(conn.execute(sql, params)):
            for index, asset in enumerate(compact_media_assets(row.get("media_assets_json")), start=1):
                items.append({
                    "content_id": row["id"],
                    "platform": row["platform"],
                    "account_name": row["account_name"],
                    "category": row["category"],
                    "original_content_id": row["original_content_id"],
                    "title": row["title"] or row["text"],
                    "source_url": row["url"],
                    "published_at": row["published_at"],
                    "media_type": asset.get("type") or row["media_type"] or "media",
                    "asset_index": index,
                    "url": asset.get("local_url") or asset.get("url") or asset.get("thumbnail_url"),
                    "thumbnail_url": asset.get("local_url") or asset.get("thumbnail_url") or asset.get("url"),
                    "download_url": asset.get("download_url"),
                    "local_path": asset.get("local_path"),
                    "bytes": asset.get("bytes"),
                    "download_status": "downloaded" if asset.get("local_path") else "linked",
                    "ocr_status": "待处理",
                })
        return {"items": items[:limit]}

    def api_failures(self, query: dict[str, list[str]]) -> dict:
        limit = parse_int((query.get("limit") or ["100"])[0], 100)
        conn = self.conn()
        rows = conn.execute(
            """
            SELECT f.*, a.account_name, a.category, a.radar_name
            FROM crawl_failures f
            LEFT JOIN source_accounts a ON a.id = f.source_account_id
            ORDER BY f.occurred_at DESC, f.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return {"items": rows_to_dicts(rows)}

    def api_config(self, query: dict[str, list[str]]) -> dict:
        conn = self.conn()
        settings = {
            row["key"]: row["value"]
            for row in conn.execute("SELECT key, value FROM app_settings ORDER BY key")
        }
        xmcp_url = os.getenv("XMCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
        chrome_session = webbridge_status()
        strategies = self.api_strategies({})["items"]
        return {
            "settings": settings,
            "xmcp": {
                "serverUrl": xmcp_url,
                "allowlist": read_env_file(ROOT / ".external" / "xmcp" / ".env").get("X_API_TOOL_ALLOWLIST", ""),
            },
            "tokens": {
                "x": bool(__import__("os").getenv("X_BEARER_TOKEN")),
                "youtube": bool(__import__("os").getenv("YOUTUBE_API_KEY")),
                "linkedin": bool(__import__("os").getenv("LINKEDIN_ACCESS_TOKEN")),
                "instagram": bool(__import__("os").getenv("INSTAGRAM_ACCESS_TOKEN")),
            },
            "chromeSession": chrome_session,
            "webbridge": chrome_session,
            "providerModes": provider_mode_capabilities(),
            "feedgrab": feedgrab_health(),
            "strategies": strategies,
        }

    def api_config_diagnostics(self, query: dict[str, list[str]]) -> dict:
        xmcp_url = os.getenv("XMCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
        xmcp = {"url": xmcp_url, "reachable": False, "message": "not_checked"}
        try:
            request = Request(
                xmcp_url,
                headers={"Accept": "application/json,text/event-stream"},
                method="GET",
            )
            opener = build_opener(ProxyHandler({}))
            with opener.open(request, timeout=2) as response:
                xmcp = {"url": xmcp_url, "reachable": response.status < 500, "message": f"HTTP {response.status}"}
        except HTTPError as exc:
            xmcp = {"url": xmcp_url, "reachable": exc.code < 500, "message": f"HTTP {exc.code}"}
        except Exception as exc:
            xmcp = {"url": xmcp_url, "reachable": False, "message": str(exc)}

        token_status = {
            "xBearerToken": bool(os.getenv("X_BEARER_TOKEN")),
            "xApiKey": bool(os.getenv("X_API_KEY")),
            "xApiSecret": bool(os.getenv("X_API_SECRET")),
            "youtube": bool(os.getenv("YOUTUBE_API_KEY")),
            "linkedin": bool(os.getenv("LINKEDIN_ACCESS_TOKEN")),
            "instagram": bool(os.getenv("INSTAGRAM_ACCESS_TOKEN")),
        }
        feishu_root = ROOT / "feishu_workspace"
        media_root = MEDIA_DIR
        chrome_session = webbridge_status()
        return {
            "xmcp": xmcp,
            "tokens": token_status,
            "credits": {
                "status": "unknown",
                "message": "X credits 需要在 X Developer Portal 查看；本地只能确认 token 是否存在。",
            },
            "feishu": {
                "mode": "local_mirror",
                "path": str(feishu_root),
                "writable": writable_path(feishu_root),
            },
            "media": {
                "path": str(media_root),
                "writable": writable_path(media_root),
            },
            "hermes": hermes_status(),
            "chromeSession": chrome_session,
            "webbridge": chrome_session,
            "providerModes": provider_mode_capabilities(),
            "feedgrab": feedgrab_health(),
        }

    def api_providers(self, query: dict[str, list[str]]) -> dict:
        platform = (query.get("platform") or [""])[0]
        items = provider_catalog()
        if platform:
            items = [item for item in items if item["platform"] == platform]
        return {"items": items}

    def api_providers_health(self, query: dict[str, list[str]]) -> dict:
        health = feedgrab_health()
        diagnostics = self.api_config_diagnostics({})
        return {
            **health,
            "radar": {
                "providerModes": diagnostics.get("providerModes", {}),
                "media": diagnostics.get("media", {}),
                "hermes": diagnostics.get("hermes", {}),
            },
        }

    def api_runs(self, query: dict[str, list[str]]) -> dict:
        limit = parse_int((query.get("limit") or ["50"])[0], 50)
        agent_type = (query.get("agentType") or query.get("agent_type") or [""])[0]
        conn = self.conn()
        sql = """
                SELECT *
                FROM crawl_runs
            """
        params: list[object] = []
        if agent_type:
            sql += " WHERE agent_type = ?"
            params.append(agent_type)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = rows_to_dicts(
            conn.execute(sql, params)
        )
        return {"items": [self.hydrate_run(row) for row in rows]}

    def api_run_detail(self, run_id: str) -> dict:
        conn = self.conn()
        row = conn.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return {"error": "not_found"}
        run = self.hydrate_run(dict(row))
        contents = self.api_contents({"runId": [run_id], "limit": ["50"]})["items"]
        run["contents"] = contents
        run["agent_feedback"] = self.agent_feedback_for_run(run)
        return run

    def api_run_retry(self, run_id: str) -> dict:
        conn = self.conn()
        row = conn.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return {"error": "not_found"}
        params = json.loads(row["params_json"] or "{}")
        return self.api_run_crawl(params)

    def api_update_run_status(self, run_id: str, body: dict) -> dict:
        status = (body.get("status") or "").strip()
        if not status:
            return {"error": "status_required"}
        allowed = {"scheduled", "running", "success", "partial_success", "failed", "paused", "cancelled"}
        if status not in allowed:
            return {"error": "unsupported_status"}
        conn = self.conn()
        row = conn.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return {"error": "not_found"}
        report = json.loads(row["report_json"] or "{}")
        if body.get("message"):
            details = report.get("details") if isinstance(report.get("details"), list) else []
            details.append({"message": body.get("message"), "updated_at": utc_now_iso()})
            report["details"] = details[-80:]
        finished_at = utc_now_iso() if status in {"success", "partial_success", "failed", "cancelled"} else row["finished_at"]
        conn.execute(
            """
            UPDATE crawl_runs
            SET status = ?, report_json = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, json.dumps(report, ensure_ascii=False, sort_keys=True), finished_at, utc_now_iso(), run_id),
        )
        conn.commit()
        return self.api_run_detail(run_id)

    def hydrate_run(self, row: dict) -> dict:
        row["params"] = json.loads(row.pop("params_json") or "{}")
        row["report"] = json.loads(row.pop("report_json") or "{}")
        return row

    def agent_feedback_for_run(self, run: dict) -> dict:
        contents = run.get("contents") or []
        report = run.get("report") or {}
        content_ids = [int(item["id"]) for item in contents if item.get("id") is not None]
        media_count = sum(len(compact_media_assets(item.get("media_assets_json"))) for item in contents)
        provider_values = []
        for item in contents:
            provider = item.get("provider") or safe_json(item.get("raw_payload_json")).get("source")
            if provider:
                provider_values.append(provider)
        providers = sorted(set(provider_values))
        errors = [
            detail
            for detail in report.get("details", [])
            if isinstance(detail, dict) and detail.get("error")
        ]
        status = run.get("status") or "unknown"
        saved = int(run.get("saved_count") or 0)
        failures = int(run.get("failure_count") or 0)
        media_failed = int(run.get("media_failed") or 0)
        has_credits_error = any(
            detail.get("error") == "credits_depleted" or detail.get("status_code") == 402
            for detail in errors
        )
        if status == "scheduled":
            message = f"已创建定时任务 {run.get('id')}，等待调度执行。"
        elif has_credits_error:
            message = f"采集失败：X API credits 不足，保存 {saved} 条，失败 {failures} 个。请先在 X Developer Portal 充值或改用 feedgrab:x_rss 免费模式。"
        elif status == "failed":
            message = f"采集失败：保存 0 条，失败 {failures} 个。"
        elif status == "partial_success":
            message = f"采集部分完成：保存 {saved} 条，失败 {failures} 个。"
        else:
            message = f"采集完成：保存 {saved} 条，失败 {failures} 个。"
        if media_failed:
            message += f" 媒体下载失败 {media_failed} 个，可稍后重试。"

        top_contents = []
        for item in contents[:5]:
            media_assets = compact_media_assets(item.get("media_assets_json"))
            top_contents.append(
                {
                    "content_id": item.get("id"),
                    "title": item.get("title") or (item.get("original_text") or item.get("text") or "")[:80],
                    "source_url": item.get("url"),
                    "provider": item.get("provider") or safe_json(item.get("raw_payload_json")).get("source"),
                    "metrics": {
                        "views": item.get("view_count"),
                        "likes": item.get("like_count"),
                        "comments": item.get("comment_count"),
                        "reposts": item.get("share_count"),
                    },
                    "media_count": len(media_assets),
                }
            )

        next_actions = []
        if content_ids:
            next_actions.extend(
                [
                    {
                        "label": "导出原始数据集",
                        "tool": "radar_export_raw_dataset",
                        "arguments": {
                            "content_ids": content_ids,
                            "output_format": "markdown",
                        },
                    },
                    {
                        "label": "交给内容整理 Agent",
                        "tool": "radar_handoff_to_organizer",
                        "arguments": {
                            "content_ids": content_ids,
                            "translate_to_zh": True,
                            "ocr_images": True,
                            "summarize": True,
                            "classify": True,
                            "quality_score": True,
                        },
                    },
                ]
            )
        report_lines = [
            f"# Radar 任务反馈",
            "",
            f"- 任务 ID: {run.get('id')}",
            f"- 状态: {status}",
            f"- 输入: {run.get('input_label') or '-'}",
            f"- 平台/模式: {run.get('platform') or '-'} / {run.get('mode') or '-'}",
            f"- 保存/失败: {saved} / {failures}",
            f"- 媒体: 已保存 {run.get('media_downloaded') or 0}，失败 {media_failed}",
            f"- 内容 IDs: {', '.join(str(item) for item in content_ids) if content_ids else '-'}",
        ]
        return {
            "audience": "ai_employee",
            "run_id": run.get("id"),
            "status": status,
            "message": message,
            "summary": {
                "platform": run.get("platform"),
                "mode": run.get("mode"),
                "input_label": run.get("input_label"),
                "saved_count": saved,
                "failure_count": failures,
                "media_downloaded": int(run.get("media_downloaded") or 0),
                "media_failed": media_failed,
                "providers": providers,
            },
            "content_ids": content_ids,
            "top_contents": top_contents,
            "errors": errors,
            "next_actions": next_actions,
            "report_markdown": "\n".join(report_lines),
        }

    def create_run(self, conn: sqlite3.Connection, *, body: dict, source_type: str, input_label: str | None, status: str = "running", agent_type: str = "crawler") -> str:
        run_id = f"crawl-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO crawl_runs (
                id, agent_type, source_type, platform, mode, status, input_label,
                params_json, started_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                agent_type,
                source_type,
                body.get("platform") or None,
                body.get("mode") or "auto",
                status,
                input_label,
                json.dumps(body, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        conn.commit()
        return run_id

    def finish_run(self, conn: sqlite3.Connection, run_id: str, report: dict) -> None:
        now = utc_now_iso()
        status = "success"
        if report["failures"] and report["saved"]:
            status = "partial_success"
        elif report["failures"] and not report["saved"]:
            status = "failed"
        conn.execute(
            """
            UPDATE crawl_runs
            SET status = ?, total_accounts = ?, success_count = ?, failure_count = ?,
                saved_count = ?, media_downloaded = ?, media_failed = ?,
                feishu_written = ?, report_json = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                report["accounts"],
                report["successes"],
                report["failures"],
                report["saved"],
                report["media"]["downloaded"],
                report["media"]["failed"],
                report.get("feishuWritten", 0),
                json.dumps(report, ensure_ascii=False, sort_keys=True),
                now,
                now,
                run_id,
            ),
        )
        conn.commit()

    def api_import_excel(self) -> dict:
        accounts = load_accounts_from_excel(self.excel_path)
        conn = self.conn()
        imported = upsert_accounts(conn, accounts)
        return {
            "imported": imported,
            "qualityIssues": sum(1 for account in accounts if account.data_quality_issue),
        }

    def api_import_x_intel(self, body: dict) -> dict:
        accounts = fetch_bestblogs_accounts(body.get("opmlUrl") or None) if body.get("opmlUrl") else fetch_bestblogs_accounts()
        conn = self.conn()
        imported = upsert_x_intel_accounts(
            conn,
            accounts,
            category=(body.get("category") or "AI情报源").strip() or "AI情报源",
            limit=parse_int(str(body.get("limit") or ""), None),
        )
        return {"imported": imported, "sourceAccounts": len(accounts)}

    def api_enrich_accounts(self, body: dict) -> dict:
        conn = self.conn()
        return enrich_accounts(conn, overwrite=bool(body.get("overwrite")))

    def api_save_config(self, body: dict) -> dict:
        conn = self.conn()
        for key, value in body.items():
            if key not in {"default_mode", "default_max_results", "default_platform"}:
                continue
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, str(value)),
            )
        conn.commit()
        return self.api_config({})

    def api_save_xmcp_config(self, body: dict) -> dict:
        allowed = {"XMCP_SERVER_URL", "X_BEARER_TOKEN", "X_API_KEY", "X_API_SECRET"}
        updates = {}
        for key in allowed:
            value = str(body.get(key) or "").strip()
            if value:
                updates[key] = value
        if not updates:
            return {"updated": 0, "message": "no_values_provided", **self.api_config({})}
        write_env_values(ROOT / ".env", updates)
        sync_xmcp_env(ROOT / ".env", ROOT / ".external" / "xmcp" / ".env")
        return {
            "updated": len(updates),
            "message": "saved_to_env_and_synced_to_xmcp",
            **self.api_config({}),
        }

    def api_update_account(self, account_id: int, body: dict) -> dict:
        updates = {key: value for key, value in body.items() if key in EDITABLE_ACCOUNT_FIELDS}
        if not updates:
            return {"updated": 0}
        assignments = []
        params: list[object] = []
        for key, value in updates.items():
            assignments.append(f"{key} = ?")
            if key == "enabled":
                params.append(parse_bool(value))
            else:
                params.append(value if value != "" else None)
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        params.append(account_id)
        conn = self.conn()
        cursor = conn.execute(
            f"UPDATE source_accounts SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        conn.commit()
        return {"updated": cursor.rowcount}

    def filter_run_result(self, result: FetchResult, body: dict) -> FetchResult:
        include_replies = bool_body(body, "includeReplies", True)
        include_retweets = bool_body(body, "includeRetweets", True)
        include_quotes = bool_body(body, "includeQuotes", True)
        include_original = bool_body(body, "includeOriginal", True)
        language = (body.get("language") or "all").strip()
        min_views = parse_int(str(body.get("minViews") or ""), None)
        download_images = bool_body(body, "downloadImages", True)
        download_videos = bool_body(body, "downloadVideos", True)

        filtered = []
        for item in result.items:
            refs = item.raw_payload.get("referenced_tweets") or []
            ref_types = {ref.get("type") for ref in refs if isinstance(ref, dict)}
            is_reply = "replied_to" in ref_types
            is_retweet = "retweeted" in ref_types
            is_quote = "quoted" in ref_types
            is_original = not refs
            if is_reply and not include_replies:
                continue
            if is_retweet and not include_retweets:
                continue
            if is_quote and not include_quotes:
                continue
            if is_original and not include_original:
                continue
            if language != "all" and item.language and item.language != language:
                continue
            if min_views is not None and item.view_count is not None and item.view_count < min_views:
                continue

            media_assets = []
            for asset in item.media_assets:
                asset_type = str(asset.get("type") or "").lower()
                if "video" in asset_type and not download_videos:
                    continue
                if "video" not in asset_type and not download_images:
                    continue
                media_assets.append(asset)
            filtered.append(replace(item, media_assets=media_assets))

        return FetchResult(
            account_id=result.account_id,
            platform=result.platform,
            items=filtered,
            next_cursor=result.next_cursor,
            last_seen_original_id=filtered[0].original_content_id if filtered else result.last_seen_original_id,
        )

    def run_accounts(self, conn: sqlite3.Connection, *, rows: list[sqlite3.Row], body: dict, run_id: str | None = None) -> dict:
        mode = body.get("mode") or "auto"
        max_results = parse_int(str(body.get("maxResults") or ""), 20) or 20
        download_media = bool_body(body, "downloadMedia", False) or bool_body(body, "downloadImages", False) or bool_body(body, "downloadVideos", False)
        media_only = bool_body(body, "mediaOnly", False)
        media_root = Path(body.get("mediaDir") or DEFAULT_MEDIA_DIR)
        providers = {}
        saved_total = 0
        failures = 0
        successes = 0
        media_totals = {"downloaded": 0, "failed": 0}
        details = []
        for row in rows:
            account = dict(row)
            provider_key = (account["platform"], mode)
            try:
                if provider_key not in providers:
                    providers[provider_key] = build_provider(account["platform"], mode=mode)
                result = providers[provider_key].fetch(account, max_results=max_results)
                result = self.filter_run_result(result, body)
                result = filter_fetch_result(result, media_only=media_only)
                media_stats = {"downloaded": 0, "failed": 0}
                if download_media:
                    media_stats = download_fetch_result_media(result, account=account, media_root=media_root)
                content_ids = save_fetch_result_with_ids(conn, result)
                link_run_contents(conn, run_id, content_ids)
                saved = len(content_ids)
                saved_total += saved
                successes += 1
                media_totals["downloaded"] += media_stats["downloaded"]
                media_totals["failed"] += media_stats["failed"]
                details.append({
                    "account": account["account_name"],
                    "platform": account["platform"],
                    "mode": mode,
                    "saved": saved,
                    "contentIds": content_ids,
                    "media": media_stats,
                })
            except ProviderError as exc:
                failures += 1
                log_failure(
                    conn,
                    source_account_id=account["id"],
                    platform=account["platform"],
                    error_type=exc.error_type,
                    error_message=str(exc),
                    status_code=exc.status_code,
                    raw_context={"account_name": account["account_name"], "mode": mode, "source": "web-run", "run_id": run_id},
                )
                details.append(
                    {
                        "account": account["account_name"],
                        "platform": account["platform"],
                        "error": exc.error_type,
                        "message": str(exc),
                        "status_code": exc.status_code,
                    }
                )
            except Exception as exc:
                failures += 1
                log_failure(
                    conn,
                    source_account_id=account["id"],
                    platform=account["platform"],
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    raw_context={"account_name": account["account_name"], "mode": mode, "source": "web-run", "run_id": run_id},
                )
                details.append(
                    {
                        "account": account["account_name"],
                        "platform": account["platform"],
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        return {
            "runId": run_id,
            "accounts": len(rows),
            "successes": successes,
            "saved": saved_total,
            "failures": failures,
            "media": media_totals,
            "feishuWritten": 0,
            "details": details[:80],
        }

    def api_crawl(self, body: dict) -> dict:
        platform = body.get("platform") or None
        mode = body.get("mode") or "auto"
        limit = parse_int(str(body.get("limit") or ""), None)
        category = body.get("category") or None
        conn = self.conn()
        rows = account_rows(conn, platform=platform, category=category, limit=limit)
        body = {**body, "mode": mode}
        report = self.run_accounts(conn, rows=rows, body=body)
        return {"accounts": report["accounts"], "saved": report["saved"], "failures": report["failures"], "details": report["details"][:50], "media": report["media"]}

    def api_run_crawl(self, body: dict) -> dict:
        conn = self.conn()
        body = self.apply_strategy(conn, body)
        source_type = body.get("sourceType") or ("account" if body.get("identifier") else "file")
        if source_type == "url" or body.get("url"):
            return self.api_run_feedgrab_url(body)
        if source_type == "keyword" or body.get("query"):
            return self.api_run_feedgrab_keyword(body)
        platform = body.get("platform") or None
        category = body.get("category") or None
        limit = parse_int(str(body.get("limit") or ""), None)
        input_label = body.get("identifier") or body.get("fileName") or category or platform or "全部数据源"
        run_id = self.create_run(conn, body=body, source_type=source_type, input_label=input_label)
        if source_type == "account" or body.get("identifier"):
            account = upsert_person_account(
                conn,
                platform=body.get("platform") or "x",
                identifier=(body.get("identifier") or "").strip(),
                account_name=(body.get("accountName") or "").strip() or None,
                category=(body.get("category") or "单人采集").strip() or "单人采集",
            )
            rows = [account]
        else:
            rows = account_rows(conn, platform=platform, category=category, limit=limit)
        report = self.run_accounts(conn, rows=rows, body=body, run_id=run_id)
        self.finish_run(conn, run_id, report)
        return self.api_run_detail(run_id)

    def upsert_feedgrab_url_account(self, conn: sqlite3.Connection, *, item_platform: str, url: str, source_name: str | None, category: str) -> sqlite3.Row:
        parsed = urlparse(url)
        account_name = (source_name or parsed.netloc or "feedgrab-url").strip() or "feedgrab-url"
        conn.execute(
            """
            INSERT INTO source_accounts (
                category, platform, account_name, account_handle, account_url,
                original_account, official_identity, radar_name, radar_persona,
                enabled, fetch_interval_minutes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 720, CURRENT_TIMESTAMP)
            ON CONFLICT(platform, account_name) DO UPDATE SET
                account_url = excluded.account_url,
                category = excluded.category,
                enabled = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                category,
                item_platform,
                account_name,
                parsed.netloc,
                url,
                f"{item_platform}-{account_name}",
                account_name,
                account_name,
                "feedgrab-url",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM source_accounts WHERE platform = ? AND account_name = ?",
            (item_platform, account_name),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to create feedgrab URL source account")
        return row

    def upsert_feedgrab_keyword_account(self, conn: sqlite3.Connection, *, platform: str, query: str, category: str) -> sqlite3.Row:
        account_name = f"{platform}:{query}".strip()
        account_url = f"feedgrab://{platform}/search?keyword={quote(query)}"
        conn.execute(
            """
            INSERT INTO source_accounts (
                category, platform, account_name, account_handle, account_url,
                original_account, official_identity, radar_name, radar_persona,
                enabled, fetch_interval_minutes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 720, CURRENT_TIMESTAMP)
            ON CONFLICT(platform, account_name) DO UPDATE SET
                account_url = excluded.account_url,
                category = excluded.category,
                enabled = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                category,
                platform,
                account_name,
                query,
                account_url,
                f"{platform}-search-{query}",
                query,
                query,
                "feedgrab-keyword",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM source_accounts WHERE platform = ? AND account_name = ?",
            (platform, account_name),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to create feedgrab keyword source account")
        return row

    def api_run_feedgrab_url(self, body: dict) -> dict:
        url = (body.get("url") or body.get("identifier") or "").strip()
        if not url:
            return {"error": "url_required"}
        conn = self.conn()
        body = {**body, "sourceType": "url", "mode": body.get("mode") or "feedgrab"}
        run_id = self.create_run(
            conn,
            body=body,
            source_type="url",
            input_label=url,
        )
        media_stats = {"downloaded": 0, "failed": 0}
        try:
            content = read_url(url)
            item = unified_content_to_item(content)
            requested_platform = (body.get("platform") or infer_platform_from_url(url) or item.platform).strip().lower()
            requested_platform = "xhs" if requested_platform == "xiaohongshu" else requested_platform
            if requested_platform not in {"", "web"} and item.platform != requested_platform:
                item = replace(
                    item,
                    platform=requested_platform,
                    raw_payload={**item.raw_payload, "requested_platform": requested_platform},
                )
            category = (body.get("category") or "feedgrab URL").strip() or "feedgrab URL"
            source_name = None
            if hasattr(content, "to_dict"):
                source_name = (content.to_dict().get("source_name") or "").strip()
            elif isinstance(content, dict):
                source_name = (content.get("source_name") or "").strip()
            account = self.upsert_feedgrab_url_account(
                conn,
                item_platform=item.platform,
                url=url,
                source_name=source_name,
                category=category,
            )
            result = FetchResult(account_id=int(account["id"]), platform=item.platform, items=[item])
            if bool_body(body, "downloadMedia", False) or bool_body(body, "downloadImages", False) or bool_body(body, "downloadVideos", False):
                media_stats = download_fetch_result_media(result, account=dict(account), media_root=Path(body.get("mediaDir") or DEFAULT_MEDIA_DIR))
            content_ids = save_fetch_result_with_ids(conn, result)
            link_run_contents(conn, run_id, content_ids)
            saved = len(content_ids)
            report = {
                "accounts": 1,
                "successes": 1,
                "saved": saved,
                "failures": 0,
                "media": media_stats,
                "feishuWritten": 0,
                "details": [{"url": url, "provider": "feedgrab:universal_reader", "saved": saved, "contentIds": content_ids}],
            }
        except FeedgrabUnavailable as exc:
            log_failure(
                conn,
                source_account_id=None,
                platform=body.get("platform") or "web",
                error_type="feedgrab_unavailable",
                error_message=str(exc),
                raw_context={"url": url, "run_id": run_id},
            )
            report = {
                "accounts": 1,
                "successes": 0,
                "saved": 0,
                "failures": 1,
                "media": media_stats,
                "feishuWritten": 0,
                "details": [{"url": url, "provider": "feedgrab:universal_reader", "error": "feedgrab_unavailable", "message": str(exc)}],
            }
        self.finish_run(conn, run_id, report)
        return self.api_run_detail(run_id)

    def api_run_feedgrab_keyword(self, body: dict) -> dict:
        platform = ((body.get("platform") or "xhs").strip().lower())
        platform = "xhs" if platform == "xiaohongshu" else platform
        query = (body.get("query") or body.get("identifier") or "").strip()
        if not query:
            return {"error": "query_required"}
        conn = self.conn()
        body = {**body, "sourceType": "keyword", "query": query, "platform": platform, "mode": body.get("mode") or "feedgrab"}
        run_id = self.create_run(conn, body=body, source_type="keyword", input_label=f"{platform}:{query}")
        media_stats = {"downloaded": 0, "failed": 0}
        category = (body.get("category") or f"{platform} 关键词").strip() or f"{platform} 关键词"
        if platform != "xhs":
            report = {
                "accounts": 1,
                "successes": 0,
                "saved": 0,
                "failures": 1,
                "media": media_stats,
                "feishuWritten": 0,
                "details": [
                    {
                        "platform": platform,
                        "query": query,
                        "provider": "feedgrab:keyword",
                        "error": "keyword_search_unavailable",
                        "message": "该平台当前关键词模式未接入；请使用 URL、账号或已授权 provider。",
                    }
                ],
            }
            log_failure(
                conn,
                source_account_id=None,
                platform=platform,
                error_type="keyword_search_unavailable",
                error_message=report["details"][0]["message"],
                raw_context={"query": query, "run_id": run_id, "source": "feedgrab-keyword"},
            )
            self.finish_run(conn, run_id, report)
            return self.api_run_detail(run_id)

        try:
            max_results = parse_int(str(body.get("maxResults") or ""), 20) or 20
            note_type = "all"
            if bool_body(body, "mediaOnly", False):
                note_type = "all"
            result_payload = search_feedgrab_xhs_keyword(
                keyword=query,
                sort=(body.get("sort") or "general"),
                note_type=note_type,
                max_results=max_results,
            )
            notes = result_payload.get("notes") or result_payload.get("items") or []
            items = []
            for note in notes:
                item = xhs_note_to_item(note, query=query)
                items.append(replace(item, raw_payload={**item.raw_payload, "source": "feedgrab:xhs_search"}))
            if bool_body(body, "mediaOnly", False):
                items = [item for item in items if item.media_assets]
            account = self.upsert_feedgrab_keyword_account(conn, platform="xhs", query=query, category=category)
            fetch_result = FetchResult(account_id=int(account["id"]), platform="xhs", items=items)
            if bool_body(body, "downloadMedia", False) or bool_body(body, "downloadImages", False) or bool_body(body, "downloadVideos", False):
                media_stats = download_fetch_result_media(fetch_result, account=dict(account), media_root=Path(body.get("mediaDir") or DEFAULT_MEDIA_DIR))
            content_ids = save_fetch_result_with_ids(conn, fetch_result)
            link_run_contents(conn, run_id, content_ids)
            saved = len(content_ids)
            report = {
                "accounts": 1,
                "successes": 1,
                "saved": saved,
                "failures": 0,
                "media": media_stats,
                "feishuWritten": 0,
                "details": [{"query": query, "provider": "feedgrab:xhs_search", "saved": saved, "contentIds": content_ids}],
            }
        except FeedgrabUnavailable as exc:
            log_failure(
                conn,
                source_account_id=None,
                platform=platform,
                error_type="feedgrab_unavailable",
                error_message=str(exc),
                raw_context={"query": query, "run_id": run_id, "source": "feedgrab-keyword"},
            )
            report = {
                "accounts": 1,
                "successes": 0,
                "saved": 0,
                "failures": 1,
                "media": media_stats,
                "feishuWritten": 0,
                "details": [{"query": query, "provider": "feedgrab:xhs_search", "error": "feedgrab_unavailable", "message": str(exc)}],
            }
        except Exception as exc:
            log_failure(
                conn,
                source_account_id=None,
                platform=platform,
                error_type=type(exc).__name__,
                error_message=str(exc),
                raw_context={"query": query, "run_id": run_id, "source": "feedgrab-keyword"},
            )
            report = {
                "accounts": 1,
                "successes": 0,
                "saved": 0,
                "failures": 1,
                "media": media_stats,
                "feishuWritten": 0,
                "details": [{"query": query, "provider": "feedgrab:xhs_search", "error": type(exc).__name__, "message": str(exc)}],
            }
        self.finish_run(conn, run_id, report)
        return self.api_run_detail(run_id)

    def api_create_collection_task(self, body: dict) -> dict:
        payload = dict(body)
        if payload.get("url"):
            payload["sourceType"] = "url"
        elif payload.get("identifier"):
            payload["sourceType"] = payload.get("sourceType") or "account"
        payload.setdefault("agentType", "crawler")
        payload.setdefault("mode", "auto" if (payload.get("platform") or "x") == "x" else "feedgrab")
        return self.api_run_crawl(payload)

    def api_create_employee_task(self, body: dict) -> dict:
        agent_type = (body.get("agentType") or body.get("agent_type") or "crawler").strip()
        if agent_type in {"crawler", "crawl"}:
            return self.api_run_crawl({**body, "agentType": "crawler"})
        if agent_type in {"organizer", "organize"}:
            return self.api_organize(body)
        if agent_type in {"publisher", "publish"}:
            return self.api_publish(body)
        conn = self.conn()
        run_id = self.create_run(
            conn,
            body=body,
            source_type=body.get("sourceType") or "manual",
            input_label=body.get("inputLabel") or body.get("identifier") or agent_type,
            status=body.get("status") or "scheduled",
            agent_type=agent_type,
        )
        report = {
            "accounts": 0,
            "successes": 0,
            "saved": 0,
            "failures": 0,
            "media": {"downloaded": 0, "failed": 0},
            "feishuWritten": 0,
            "details": [{"message": "员工任务已创建，等待对应 Agent 执行。"}],
        }
        self.finish_run(conn, run_id, report)
        if body.get("status") == "scheduled":
            conn.execute("UPDATE crawl_runs SET status = 'scheduled' WHERE id = ?", (run_id,))
            conn.commit()
        return self.api_run_detail(run_id)

    def selected_content_ids(self, body: dict, *, default_limit: int = 20) -> list[int]:
        raw_ids = body.get("contentIds") or []
        if isinstance(raw_ids, str):
            raw_ids = [part.strip() for part in raw_ids.split(",") if part.strip()]
        ids = [int(item) for item in raw_ids if str(item).isdigit()]
        if ids:
            return ids
        limit = int(body.get("limit") or default_limit)
        conn = self.conn()
        rows = conn.execute(
            """
            SELECT id FROM source_contents
            WHERE organize_status IN ('pending', 'failed')
            ORDER BY COALESCE(published_at, fetched_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def api_handoff_to_organizer(self, body: dict) -> dict:
        ids = self.selected_content_ids(body, default_limit=parse_int(str(body.get("limit") or ""), 20) or 20)
        conn = self.conn()
        run_id = self.create_run(
            conn,
            body=body,
            source_type="raw_contents",
            input_label=f"内容整理 handoff {len(ids)} 条",
            agent_type="organizer_handoff",
        )
        rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT c.*, a.account_name, a.category, a.radar_name
                FROM source_contents c
                JOIN source_accounts a ON a.id = c.source_account_id
                WHERE c.id IN ({",".join("?" for _ in ids) if ids else "NULL"})
                ORDER BY COALESCE(c.published_at, c.fetched_at) DESC
                """,
                ids,
            )
        ) if ids else []
        items = [self.raw_content_contract_item(row) for row in rows]
        requirements = {
            "translate_to_zh": bool_body(body, "translateToZh", True),
            "ocr_images": bool_body(body, "ocrImages", True),
            "summarize": bool_body(body, "summarize", True),
            "classify": bool_body(body, "classify", True),
            "quality_score": bool_body(body, "qualityScore", True),
        }
        handoff = {
            "task_id": run_id,
            "content_ids": [item["content_id"] for item in items],
            "handoff_type": "raw_content_for_organization",
            "requirements": requirements,
            "items": items,
        }
        organizer_task = {
            "agent": "内容整理 Agent",
            "status": "ready_for_organization",
            "handoff": handoff,
            "writeback_tool": "radar_save_organized_content",
            "writeback_api": "/api/organize/save",
            "expected_output_per_item": [
                "content_id",
                "organized_title",
                "organized_summary",
                "translated_text_zh",
                "quality_score",
                "quality_reason",
                "content_category",
                "organize_notes",
                "review_status",
                "publish_status",
            ],
            "instructions": [
                "Only organize the raw content IDs included in this handoff.",
                "Preserve original_text exactly; write Chinese translation into translated_text_zh.",
                "Keep source_url and media_assets available in the organized markdown.",
                "If OCR is unavailable, leave OCR fields empty and explain it in organize_notes.",
                "Call radar_save_organized_content once per accepted item.",
            ],
        }
        report = {
            "accounts": len(items),
            "successes": len(items),
            "saved": len(items),
            "failures": max(0, len(ids) - len(items)),
            "media": {"downloaded": 0, "failed": 0},
            "feishuWritten": 0,
            "details": [{"message": "内容整理 Agent handoff payload generated", "content_ids": handoff["content_ids"]}],
            "handoff": handoff,
            "organizer_task": organizer_task,
            "beemax_task": organizer_task,
        }
        self.finish_run(conn, run_id, report)
        return {
            "handoff": handoff,
            "organizer_task": organizer_task,
            "beemax_task": organizer_task,
            "run": self.api_run_detail(run_id),
        }

    def api_handoff_to_beemax(self, body: dict) -> dict:
        return self.api_handoff_to_organizer(body)

    def api_organize(self, body: dict) -> dict:
        ids = self.selected_content_ids(body)
        conn = self.conn()
        run_id = self.create_run(
            conn,
            body=body,
            source_type="contents",
            input_label=f"{len(ids)} 条内容",
            agent_type="organizer",
        )
        now = utc_now_iso()
        success = 0
        details = []
        for content_id in ids:
            row = conn.execute(
                """
                SELECT c.*, a.account_name, a.category
                FROM source_contents c
                JOIN source_accounts a ON a.id = c.source_account_id
                WHERE c.id = ?
                """,
                (content_id,),
            ).fetchone()
            if row is None:
                continue
            title = row["title"] or (row["text"] or row["original_content_id"])[:80]
            original_text = row["original_text"] or row["text"] or ""
            existing_translation = row["translated_text_zh"] or ""
            summary = (existing_translation or original_text or title or "")[:220]
            translation_status = row["translation_status"] or "pending"
            if bool_body(body, "translate", True) and not existing_translation:
                translation_status = "pending"
            elif existing_translation:
                translation_status = "translated"
            else:
                translation_status = "not_required"
            row_data = dict(row)
            row_data.update(
                {
                    "organized_title": title,
                    "organized_summary": summary,
                    "original_text": original_text,
                    "translated_text_zh": existing_translation,
                    "translation_status": translation_status,
                    "translation_provider": row["translation_provider"] or "hermes-agent",
                    "quality_score": row["quality_score"] if row["quality_score"] is not None else 0.7,
                    "quality_reason": row["quality_reason"] or "待 Hermes 内容整理 Agent 根据事实密度、时效性和可发布性复核。",
                    "content_category": row["content_category"] or row["category"],
                    "organize_notes": row["organize_notes"] or "已保留英文原文，等待或使用 Hermes 回写中文翻译。",
                    "organize_status": "organized",
                    "review_status": "approved",
                    "publish_status": "pending",
                }
            )
            markdown = content_markdown(row_data, fallback_title=title)
            conn.execute(
                """
                UPDATE source_contents
                SET organize_status = 'organized',
                    review_status = 'approved',
                    publish_status = 'pending',
                    organized_title = ?,
                    organized_summary = ?,
                    organized_markdown = ?,
                    original_text = COALESCE(original_text, text),
                    translation_status = ?,
                    translation_provider = COALESCE(translation_provider, ?),
                    quality_score = COALESCE(quality_score, ?),
                    quality_reason = COALESCE(quality_reason, ?),
                    content_category = COALESCE(content_category, ?),
                    organize_notes = COALESCE(organize_notes, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    summary,
                    markdown,
                    translation_status,
                    "hermes-agent",
                    0.7,
                    "待 Hermes 内容整理 Agent 根据事实密度、时效性和可发布性复核。",
                    row["category"],
                    "已保留英文原文，等待或使用 Hermes 回写中文翻译。",
                    now,
                    content_id,
                ),
            )
            success += 1
            details.append({"content_id": content_id, "title": title})
        conn.commit()
        report = {
            "accounts": len(ids),
            "successes": success,
            "saved": success,
            "failures": max(0, len(ids) - success),
            "media": {"downloaded": 0, "failed": 0},
            "feishuWritten": 0,
            "details": details[:50],
        }
        self.finish_run(conn, run_id, report)
        return self.api_run_detail(run_id)

    def api_save_translation_result(self, body: dict) -> dict:
        content_id = int(body.get("contentId") or body.get("content_id") or 0)
        if not content_id:
            return {"error": "content_id_required"}
        translated = body.get("translatedTextZh") or body.get("translated_text_zh") or ""
        ocr_original = body.get("ocrTextOriginal") or body.get("ocr_text_original")
        ocr_zh = body.get("ocrTextZh") or body.get("ocr_text_zh")
        provider = body.get("translationProvider") or body.get("translation_provider") or "hermes-agent"
        now = utc_now_iso()
        conn = self.conn()
        row = conn.execute("SELECT * FROM source_contents WHERE id = ?", (content_id,)).fetchone()
        if row is None:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE source_contents
            SET original_text = COALESCE(original_text, text),
                translated_text_zh = COALESCE(NULLIF(?, ''), translated_text_zh),
                translation_status = ?,
                translation_provider = ?,
                ocr_text_original = COALESCE(?, ocr_text_original),
                ocr_text_zh = COALESCE(?, ocr_text_zh),
                updated_at = ?
            WHERE id = ?
            """,
            (
                translated,
                "translated" if translated else "pending",
                provider,
                ocr_original,
                ocr_zh,
                now,
                content_id,
            ),
        )
        updated = conn.execute(
            """
            SELECT c.*, a.account_name, a.category, a.radar_name
            FROM source_contents c
            JOIN source_accounts a ON a.id = c.source_account_id
            WHERE c.id = ?
            """,
            (content_id,),
        ).fetchone()
        markdown = content_markdown(updated)
        conn.execute("UPDATE source_contents SET organized_markdown = ?, updated_at = ? WHERE id = ?", (markdown, now, content_id))
        conn.commit()
        return self.api_content_detail(content_id)

    def api_save_organized_content(self, body: dict) -> dict:
        content_id = int(body.get("contentId") or body.get("content_id") or 0)
        if not content_id:
            return {"error": "content_id_required"}
        now = utc_now_iso()
        conn = self.conn()
        row = conn.execute(
            """
            SELECT c.*, a.account_name, a.category, a.radar_name
            FROM source_contents c
            JOIN source_accounts a ON a.id = c.source_account_id
            WHERE c.id = ?
            """,
            (content_id,),
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        title = body.get("organizedTitle") or body.get("organized_title") or row["organized_title"] or row["title"] or row["original_content_id"]
        translated = body.get("translatedTextZh") or body.get("translated_text_zh") or row["translated_text_zh"] or ""
        row_data = dict(row)
        row_data.update(
            {
                "organized_title": title,
                "organized_summary": body.get("organizedSummary") or body.get("organized_summary") or row["organized_summary"] or (translated or row["text"] or "")[:220],
                "translated_text_zh": translated,
                "translation_status": "translated" if translated else (row["translation_status"] or "pending"),
                "translation_provider": body.get("translationProvider") or body.get("translation_provider") or row["translation_provider"] or "hermes-agent",
                "ocr_text_original": body.get("ocrTextOriginal") or body.get("ocr_text_original") or row["ocr_text_original"],
                "ocr_text_zh": body.get("ocrTextZh") or body.get("ocr_text_zh") or row["ocr_text_zh"],
                "quality_score": body.get("qualityScore") or body.get("quality_score") or row["quality_score"],
                "quality_reason": body.get("qualityReason") or body.get("quality_reason") or row["quality_reason"],
                "content_category": body.get("contentCategory") or body.get("content_category") or row["content_category"] or row["category"],
                "organize_notes": body.get("organizeNotes") or body.get("organize_notes") or row["organize_notes"],
                "organize_status": "organized",
                "review_status": body.get("reviewStatus") or body.get("review_status") or "approved",
                "publish_status": body.get("publishStatus") or body.get("publish_status") or "pending",
            }
        )
        markdown = body.get("organizedMarkdown") or body.get("organized_markdown") or content_markdown(row_data, fallback_title=title)
        conn.execute(
            """
            UPDATE source_contents
            SET organize_status = 'organized',
                review_status = ?,
                publish_status = ?,
                organized_title = ?,
                organized_summary = ?,
                organized_markdown = ?,
                original_text = COALESCE(original_text, text),
                translated_text_zh = COALESCE(NULLIF(?, ''), translated_text_zh),
                translation_status = ?,
                translation_provider = ?,
                ocr_text_original = COALESCE(?, ocr_text_original),
                ocr_text_zh = COALESCE(?, ocr_text_zh),
                quality_score = COALESCE(?, quality_score),
                quality_reason = COALESCE(?, quality_reason),
                content_category = COALESCE(?, content_category),
                organize_notes = COALESCE(?, organize_notes),
                updated_at = ?
            WHERE id = ?
            """,
            (
                row_data["review_status"],
                row_data["publish_status"],
                title,
                row_data["organized_summary"],
                markdown,
                translated,
                row_data["translation_status"],
                row_data["translation_provider"],
                row_data["ocr_text_original"],
                row_data["ocr_text_zh"],
                row_data["quality_score"],
                row_data["quality_reason"],
                row_data["content_category"],
                row_data["organize_notes"],
                now,
                content_id,
            ),
        )
        conn.commit()
        return self.api_content_detail(content_id)

    def api_publish(self, body: dict) -> dict:
        raw_ids = body.get("contentIds") or []
        ids = self.selected_content_ids(body, default_limit=10) if raw_ids else []
        if not ids:
            conn_for_ids = self.conn()
            rows = conn_for_ids.execute(
                """
                SELECT id FROM source_contents
                WHERE organize_status = 'organized'
                  AND review_status = 'approved'
                  AND publish_status IN ('pending', 'failed')
                ORDER BY COALESCE(updated_at, fetched_at) DESC
                LIMIT ?
                """,
                (int(body.get("limit") or 10),),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
        target = (body.get("targetChannel") or body.get("target") or "雷达号 APP").strip()
        conn = self.conn()
        run_id = self.create_run(
            conn,
            body=body,
            source_type="contents",
            input_label=target,
            agent_type="publisher",
        )
        now = utc_now_iso()
        success = 0
        details = []
        for content_id in ids:
            row = conn.execute("SELECT * FROM source_contents WHERE id = ?", (content_id,)).fetchone()
            if row is None or row["organize_status"] != "organized":
                continue
            published_url = f"mock://{target}/{row['platform']}/{row['original_content_id']}"
            payload = {
                "title": row["organized_title"] or row["title"] or row["original_content_id"],
                "body": row["organized_markdown"] or row["text"] or "",
                "source_url": row["url"],
                "target_channel": target,
            }
            conn.execute(
                """
                INSERT INTO publish_records (
                    content_id, target_channel, status, payload_json,
                    published_url, created_at, updated_at
                )
                VALUES (?, ?, 'published', ?, ?, ?, ?)
                """,
                (content_id, target, json.dumps(payload, ensure_ascii=False, sort_keys=True), published_url, now, now),
            )
            conn.execute(
                """
                UPDATE source_contents
                SET publish_status = 'published',
                    target_channel = ?,
                    published_url = ?,
                    channel_published_at = ?,
                    publish_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (target, published_url, now, now, content_id),
            )
            success += 1
            details.append({"content_id": content_id, "target": target, "published_url": published_url})
        conn.commit()
        report = {
            "accounts": len(ids),
            "successes": success,
            "saved": success,
            "failures": max(0, len(ids) - success),
            "media": {"downloaded": 0, "failed": 0},
            "feishuWritten": 0,
            "details": details[:50],
        }
        self.finish_run(conn, run_id, report)
        return self.api_run_detail(run_id)

    def api_agent_chat(self, body: dict) -> dict:
        message = (body.get("message") or "").strip()
        if not message:
            return {"error": "message_required"}
        task = parse_chat_prompt(message)
        if body.get("strategyId") or body.get("strategy_id"):
            task["strategyId"] = body.get("strategyId") or body.get("strategy_id")
            task = self.apply_strategy(self.conn(), task)
            identifier = extract_identifier_from_prompt(message)
            if identifier:
                task["identifier"] = identifier[1:] if identifier.startswith("@") else identifier
                task["sourceType"] = "account"
            task["prompt"] = message
        if body.get("execute") is False:
            return {
                "reply": "已解析为任务草稿，请确认后发布。",
                "task": task,
                "run": None,
            }

        conn = self.conn()
        if task.get("schedule"):
            input_label = task.get("identifier") or task.get("category") or "Chat 定时任务"
            run_id = self.create_run(
                conn,
                body=task,
                source_type=task["sourceType"],
                input_label=input_label,
                status="scheduled",
            )
            report = {
                "accounts": 0,
                "successes": 0,
                "saved": 0,
                "failures": 0,
                "media": {"downloaded": 0, "failed": 0},
                "feishuWritten": 0,
                "details": [{"message": "任务已进入定时任务列表，等待调度器执行。"}],
            }
            self.finish_run(conn, run_id, report)
            conn.execute(
                "UPDATE crawl_runs SET status = 'scheduled', report_json = ? WHERE id = ?",
                (json.dumps(report, ensure_ascii=False, sort_keys=True), run_id),
            )
            conn.commit()
            run = self.api_run_detail(run_id)
            feedback = run["agent_feedback"]
            return {
                "reply": feedback["message"],
                "task": task,
                "run": run,
                "agent_feedback": feedback,
            }

        if task["sourceType"] == "account" and not task.get("identifier"):
            return {
                "reply": "我没有识别到账号，请输入 @handle 或 X 主页链接。",
                "task": task,
                "run": None,
            }
        run = self.api_run_crawl(task)
        feedback = run.get("agent_feedback") or self.agent_feedback_for_run(run)
        return {
            "reply": feedback["message"],
            "task": task,
            "run": run,
            "agent_feedback": feedback,
        }

    def api_agent_upload(self, filename: str, data: bytes) -> dict:
        uploads_dir = ROOT / "data" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        saved_path = uploads_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{filename}"
        saved_path.write_bytes(data)
        suffix = saved_path.suffix.lower()
        if suffix == ".xlsx":
            accounts = load_accounts_from_excel(saved_path)
            conn = self.conn()
            imported = upsert_accounts(conn, accounts)
            quality_issues = [account for account in accounts if account.data_quality_issue]
            platforms: dict[str, int] = {}
            categories: dict[str, int] = {}
            for account in accounts:
                platforms[account.platform] = platforms.get(account.platform, 0) + 1
                categories[account.category] = categories.get(account.category, 0) + 1
            return {
                "type": "xlsx",
                "filename": filename,
                "savedPath": str(saved_path),
                "imported": imported,
                "accounts": len(accounts),
                "qualityIssues": len(quality_issues),
                "platforms": platforms,
                "categories": categories,
                "suggestedPrompt": f"解析 {filename} 中的账号，按 X 平台批量采集最近7天内容，只保留原创，下载图片和视频",
                "message": f"已解析 {len(accounts)} 个账号，导入 {imported} 条，数据问题 {len(quality_issues)} 条。",
            }
        if suffix in {".txt", ".md", ".csv"}:
            text = data.decode("utf-8", errors="replace")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            handles = []
            for line in lines:
                found = extract_identifier_from_prompt(line)
                if found:
                    handles.append(found)
            return {
                "type": suffix.lstrip("."),
                "filename": filename,
                "savedPath": str(saved_path),
                "lines": len(lines),
                "handles": handles[:50],
                "preview": "\n".join(lines[:12]),
                "suggestedPrompt": f"解析 {filename} 中的账号，批量采集最近7天原创内容，下载图片和视频",
                "message": f"已读取 {len(lines)} 行文本，识别到 {len(handles)} 个账号线索。",
            }
        return {
            "type": "unsupported",
            "filename": filename,
            "savedPath": str(saved_path),
            "message": "已保存附件，但当前只支持自动解析 xlsx、txt、md、csv。",
            "suggestedPrompt": f"使用附件 {filename} 创建采集任务",
        }

    def api_crawl_person(self, body: dict) -> dict:
        platform = body.get("platform")
        identifier = (body.get("identifier") or "").strip()
        mode = body.get("mode") or "auto"
        max_results = parse_int(str(body.get("maxResults") or ""), 20) or 20
        download_media = bool(body.get("downloadMedia"))
        media_only = bool(body.get("mediaOnly"))
        if platform not in {"x", "youtube", "linkedin", "instagram"} or not identifier:
            return {"saved": 0, "failures": 1, "error": "platform_and_identifier_required"}
        conn = self.conn()
        account = dict(
            upsert_person_account(
                conn,
                platform=platform,
                identifier=identifier,
                account_name=(body.get("accountName") or "").strip() or None,
                category=(body.get("category") or "单人采集").strip() or "单人采集",
            )
        )
        try:
            result = build_provider(platform, mode=mode).fetch(account, max_results=max_results)
            result = filter_fetch_result(result, media_only=media_only)
            media_stats = {"downloaded": 0, "failed": 0}
            if download_media:
                media_stats = download_fetch_result_media(result, account=account, media_root=DEFAULT_MEDIA_DIR)
            saved = save_fetch_result(conn, result)
            media_count = sum(len(item.media_assets) for item in result.items)
            return {
                "account": account["account_name"],
                "platform": platform,
                "saved": saved,
                "mediaAssets": media_count,
                "media": media_stats,
                "failures": 0,
            }
        except ProviderError as exc:
            log_failure(
                conn,
                source_account_id=account["id"],
                platform=platform,
                error_type=exc.error_type,
                error_message=str(exc),
                status_code=exc.status_code,
                raw_context={"identifier": identifier, "mode": mode, "source": "web-crawl-person"},
            )
            return {
                "account": account["account_name"],
                "platform": platform,
                "saved": 0,
                "failures": 1,
                "error": exc.error_type,
                "message": str(exc),
            }


def auto_import_if_empty(db_path: Path, excel_path: Path) -> None:
    conn = connect(db_path)
    init_db(conn)
    count = conn.execute("SELECT COUNT(*) FROM source_accounts").fetchone()[0]
    if count == 0 and excel_path.exists():
        upsert_accounts(conn, load_accounts_from_excel(excel_path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Radar source account management web platform")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-auto-import", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv_file(ROOT / ".env")
    RadarAdminHandler.db_path = args.db
    RadarAdminHandler.excel_path = args.excel
    if not args.no_auto_import:
        auto_import_if_empty(args.db, args.excel)
    server = ThreadingHTTPServer((args.host, args.port), RadarAdminHandler)
    print(f"Radar admin platform running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
