#!/usr/bin/env python3
"""Radar MCP server for Hermes Agent.

This server exposes the local Radar data collection platform as MCP tools.
It intentionally talks to the existing local HTTP API instead of importing
server internals, so Hermes can use it as a stable integration boundary.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP


RADAR_BASE_URL = os.environ.get("RADAR_BASE_URL", "http://127.0.0.1:8780").rstrip("/")

mcp = FastMCP(
    "radar",
    instructions=(
        "Tools for the local Radar/Hermes content workflow. "
        "Crawler tools create raw data, organizer tools process selected raw "
        "content, and publisher tools publish only organized content. "
        "Radar MCP is the AI employee entrypoint; platform backend MCPs such "
        "as X MCP and Xiaohongshu MCP are managed by a platform MCP Manager and "
        "called by Radar through its Gateway. They are visible through "
        "radar_list_mcp_integrations."
    ),
)


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{RADAR_BASE_URL}{path}"
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Radar API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Radar API unavailable at {RADAR_BASE_URL}: {exc.reason}") from exc
    return json.loads(data) if data else {}


def _query(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "", [])}
    if not clean:
        return path
    return f"{path}?{urllib.parse.urlencode(clean, doseq=True)}"


@mcp.tool()
def radar_diagnostics() -> dict[str, Any]:
    """Check Radar local service, X token, XMCP, Feishu mirror, and media directory status."""
    return _request("GET", "/api/config/diagnostics")


@mcp.tool()
def radar_list_providers(platform: str = "") -> dict[str, Any]:
    """List Beeclaw providers and their collection capabilities."""
    return _request("GET", _query("/api/providers", {"platform": platform}))


@mcp.tool()
def radar_check_provider_health() -> dict[str, Any]:
    """Check Beeclaw, upstream feedgrab backend, X MCP, XHS MCP, and media readiness."""
    return _request("GET", "/api/providers/health")


@mcp.tool()
def radar_check_production_readiness() -> dict[str, Any]:
    """Check the six production-readiness areas for large-scale collection.

    Use this before production rollout or when the user asks what still blocks
    large-scale collection. The result separates project-side implemented
    capabilities from external platform/MCP/credits validation.
    """
    return _request("GET", "/api/production-readiness")


@mcp.tool()
def radar_list_mcp_integrations(integration_type: str = "") -> dict[str, Any]:
    """List MCP integrations visible to Qianfeng platform.

    Radar MCP is the AI-employee tool entrypoint. Backend MCPs such as X MCP
    and Xiaohongshu MCP are platform-managed connectors used by Radar/Beeclaw
    through the configured platform MCP Manager/Gateway and should not be bound to normal AI
    employees by default.
    """
    return _request("GET", _query("/api/mcp/integrations", {"type": integration_type}))


@mcp.tool()
def radar_xmcp_pressure_test(
    handles: str = "",
    max_accounts: int = 2,
    max_results: int = 5,
    execute: bool = False,
    queue: bool = True,
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Create a bounded real X MCP pressure test plan or queued batch task.

    Keep max_accounts and max_results small unless the user explicitly accepts
    the X API credits impact.
    """
    return _request(
        "POST",
        "/api/providers/xmcp/pressure-test",
        {
            "handles": handles,
            "maxAccounts": max_accounts,
            "maxResults": max_results,
            "execute": execute,
            "queue": queue,
            "maxAttempts": max_attempts,
        },
    )


@mcp.tool()
def radar_agent_collect(
    instruction: str,
    execute: bool = True,
    strategy_id: str = "",
) -> dict[str, Any]:
    """Natural-language Radar collection entrypoint for AI employees.

    Pass the user's original instruction here. Radar parses intent, chooses the
    strategy/provider, calls Beeclaw, saves raw content and media assets, then
    returns agent_feedback for the AI employee to relay.

    If the user asks for scheduled collection, Radar returns
    agent_feedback.status=requires_runtime_schedule and a runtime_schedule
    payload. The Agent runtime owns actual scheduling.
    """
    payload: dict[str, Any] = {
        "message": instruction,
        "execute": execute,
    }
    if strategy_id:
        payload["strategyId"] = strategy_id
    return _request("POST", "/api/agent/chat", payload)


@mcp.tool()
def radar_create_collection_task(
    identifier: str = "",
    url: str = "",
    urls: str = "",
    query: str = "",
    platform: str = "x",
    mode: str = "auto",
    strategy_id: str = "",
    category: str = "Chat采集",
    date_range: str = "7d",
    limit: int = 20,
    include_original: bool = True,
    include_replies: bool = False,
    include_retweets: bool = False,
    include_quotes: bool = True,
    download_images: bool = True,
    download_videos: bool = True,
    media_only: bool = False,
    queue: bool = False,
) -> dict[str, Any]:
    """Create a Radar collection task backed by Beeclaw providers.

    For URL/content collection, pass url. For large URL batches, pass urls as
    newline- or comma-separated URLs; Radar will create a parent batch task and
    queued child tasks for the worker.

    Radar will route supported Beeclaw
    platforms such as XHS, WeChat, YouTube, Bilibili, Douyin, Weibo, Zhihu,
    GitHub, Feishu, Kdocs, Youdao, RSS, Telegram, Reddit, HackerNews, Medium,
    LinuxDo, IDCFlare, Xiaoyuzhou, Ximalaya, and generic Web URLs.

    The response includes agent_feedback. AI employees should use
    agent_feedback.message as the user-facing result and agent_feedback.next_actions
    for export or content organizer handoff.
    """
    has_urls = bool(urls.strip())
    payload = {
        "sourceType": "url" if (url or has_urls) else ("keyword" if query else ("account" if identifier else "file")),
        "identifier": identifier,
        "url": url,
        "urls": urls,
        "query": query,
        "platform": platform,
        "mode": mode,
        "strategyId": strategy_id,
        "category": category,
        "dateRange": date_range,
        "limit": limit,
        "maxResults": limit,
        "includeOriginal": include_original,
        "includeReplies": include_replies,
        "includeRetweets": include_retweets,
        "includeQuotes": include_quotes,
        "downloadImages": download_images,
        "downloadVideos": download_videos,
        "downloadMedia": download_images or download_videos,
        "mediaOnly": media_only,
        "queue": queue,
    }
    return _request("POST", "/api/collection-tasks", payload)


@mcp.tool()
def radar_get_collection_task(task_id: str) -> dict[str, Any]:
    """Get a Radar collection task by ID, including agent_feedback for the AI employee."""
    return _request("GET", f"/api/collection-tasks/{urllib.parse.quote(task_id)}")


@mcp.tool()
def radar_retry_collection_task(task_id: str, queue: bool = True) -> dict[str, Any]:
    """Retry an existing collection task. Use queue=true for production async retry."""
    return _request("POST", f"/api/runs/{urllib.parse.quote(task_id)}/retry", {"queue": queue})


@mcp.tool()
def radar_list_media_assets(content_id: int = 0, run_id: str = "", status: str = "", limit: int = 100) -> dict[str, Any]:
    """List collected media assets and their download status."""
    return _request(
        "GET",
        _query(
            "/api/media-assets",
            {
                "contentId": content_id or "",
                "runId": run_id,
                "status": status,
                "limit": limit,
            },
        ),
    )


@mcp.tool()
def radar_retry_media_asset(media_id: int) -> dict[str, Any]:
    """Retry one failed or pending media asset download."""
    return _request("POST", f"/api/media-assets/{media_id}/retry", {})


@mcp.tool()
def radar_retry_media_assets(content_id: int = 0, run_id: str = "", status: str = "failed", limit: int = 100) -> dict[str, Any]:
    """Retry a batch of failed or pending media assets."""
    return _request(
        "POST",
        "/api/media-assets/retry",
        {
            "contentId": content_id,
            "runId": run_id,
            "status": status,
            "limit": limit,
        },
    )


@mcp.tool()
def radar_export_media_assets(content_id: int = 0, run_id: str = "", status: str = "", limit: int = 100, output_format: str = "json") -> dict[str, Any]:
    """Export collected media asset manifests as JSON, JSONL, or Markdown."""
    return _request(
        "GET",
        _query(
            "/api/media-assets/export",
            {
                "contentId": content_id or "",
                "runId": run_id,
                "status": status,
                "limit": limit,
                "format": output_format,
            },
        ),
    )


@mcp.tool()
def radar_create_crawl_run(
    identifier: str = "",
    platform: str = "x",
    mode: str = "auto",
    category: str = "Chat采集",
    date_range: str = "7d",
    limit: int = 20,
    include_original: bool = True,
    include_replies: bool = False,
    include_retweets: bool = False,
    include_quotes: bool = True,
    download_images: bool = True,
    download_videos: bool = True,
    media_only: bool = False,
) -> dict[str, Any]:
    """Create and run a crawl task. Use this only from the crawler agent.

    For X, use auto by default. Radar exposes provider beeclaw:x and records
    the selected execution_backend such as x_mcp, x_api, or x_rss. Explicit
    legacy modes such as beeclaw:x_mcp and beeclaw:x_rss remain supported.
    """
    payload = {
        "sourceType": "account" if identifier else "file",
        "identifier": identifier,
        "platform": platform,
        "mode": mode,
        "category": category,
        "dateRange": date_range,
        "limit": limit,
        "includeOriginal": include_original,
        "includeReplies": include_replies,
        "includeRetweets": include_retweets,
        "includeQuotes": include_quotes,
        "downloadImages": download_images,
        "downloadVideos": download_videos,
        "downloadMedia": download_images or download_videos,
        "mediaOnly": media_only,
    }
    return _request("POST", "/api/runs/crawl", payload)


@mcp.tool()
def radar_list_strategies(platform: str = "") -> dict[str, Any]:
    """List enabled crawl strategies that can be used when creating employee tasks."""
    return _request("GET", _query("/api/collection-strategies", {"platform": platform}))


@mcp.tool()
def radar_create_strategy(
    name: str,
    description: str = "",
    platform: str = "x",
    mode: str = "auto",
    date_range: str = "7d",
    category: str = "",
    max_results: int = 20,
    min_views: int | None = None,
    language: str = "all",
    include_original: bool = True,
    include_quotes: bool = True,
    include_replies: bool = False,
    include_retweets: bool = False,
    download_images: bool = True,
    download_videos: bool = True,
    media_only: bool = False,
    translate_after_crawl: bool = False,
    ocr_images: bool = False,
) -> dict[str, Any]:
    """Create or update a Radar crawl strategy for future chat or scheduled tasks."""
    return _request(
        "POST",
        "/api/strategies",
        {
            "name": name,
            "description": description,
            "platform": platform,
            "mode": mode,
            "dateRange": date_range,
            "category": category,
            "maxResults": max_results,
            "minViews": min_views,
            "language": language,
            "includeOriginal": include_original,
            "includeQuotes": include_quotes,
            "includeReplies": include_replies,
            "includeRetweets": include_retweets,
            "downloadImages": download_images,
            "downloadVideos": download_videos,
            "mediaOnly": media_only,
            "translateAfterCrawl": translate_after_crawl,
            "ocrImages": ocr_images,
        },
    )


@mcp.tool()
def radar_create_employee_task(
    agent_type: str = "crawler",
    identifier: str = "",
    strategy_id: str = "",
    platform: str = "x",
    mode: str = "auto",
    category: str = "Chat采集",
    max_results: int = 20,
    content_ids: list[int] | None = None,
    target_channel: str = "雷达号 APP",
) -> dict[str, Any]:
    """Create a crawler, organizer, or publisher employee task from Hermes."""
    payload: dict[str, Any] = {
        "agentType": agent_type,
        "identifier": identifier,
        "strategyId": strategy_id,
        "platform": platform,
        "mode": mode,
        "category": category,
        "maxResults": max_results,
        "contentIds": content_ids or [],
        "targetChannel": target_channel,
    }
    return _request("POST", "/api/employee-tasks", payload)


@mcp.tool()
def radar_list_raw_contents(
    platform: str = "",
    qualification: str = "",
    has_media: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List raw collected contents from the crawler stage for human selection or organizing."""
    return _request(
        "GET",
        _query(
            "/api/raw-contents",
            {
                "platform": platform,
                "qualification": qualification,
                "hasMedia": "1" if has_media else "",
                "limit": limit,
            },
        ),
    )


@mcp.tool()
def radar_get_raw_content_detail(content_id: int) -> dict[str, Any]:
    """Get a single raw content item with original text, media, translation fields, and markdown preview."""
    return _request("GET", f"/api/raw-contents/{content_id}")


@mcp.tool()
def radar_export_raw_dataset(
    platform: str = "",
    run_id: str = "",
    content_ids: list[int] | None = None,
    has_media: bool = False,
    limit: int = 100,
    output_format: str = "json",
) -> dict[str, Any]:
    """Export raw collected contents as JSON, JSONL, or Markdown for downstream agents."""
    ids = ",".join(str(item) for item in (content_ids or []))
    return _request(
        "GET",
        _query(
            "/api/raw-contents/export",
            {
                "platform": platform,
                "runId": run_id,
                "contentIds": ids,
                "hasMedia": "1" if has_media else "",
                "limit": limit,
                "format": output_format,
            },
        ),
    )


@mcp.tool()
def radar_handoff_to_organizer(
    content_ids: list[int],
    translate_to_zh: bool = True,
    ocr_images: bool = True,
    summarize: bool = True,
    classify: bool = True,
    quality_score: bool = True,
) -> dict[str, Any]:
    """Generate a content organization task for selected raw content.

    The response includes handoff raw data plus organizer_task instructions.
    The content organizer Agent should process those items and write results back with
    radar_save_organized_content.
    """
    return _request(
        "POST",
        "/api/raw-contents/handoff/organizer",
        {
            "contentIds": content_ids,
            "translateToZh": translate_to_zh,
            "ocrImages": ocr_images,
            "summarize": summarize,
            "classify": classify,
            "qualityScore": quality_score,
        },
    )


@mcp.tool()
def radar_handoff_to_interaction_agent(
    content_ids: list[int],
    target_channel: str = "",
    golden_window_score: bool = True,
    generate_reply: bool = True,
    generate_quote: bool = True,
    risk_check: bool = True,
) -> dict[str, Any]:
    """Generate a golden-interaction-window task for selected raw content.

    The interaction-capable Agent should score the included items, generate
    reply/quote suggestions, then write candidates back with
    radar_save_interaction_candidates.
    """
    return _request(
        "POST",
        "/api/raw-contents/handoff/interaction",
        {
            "contentIds": content_ids,
            "targetChannel": target_channel,
            "goldenWindowScore": golden_window_score,
            "generateReply": generate_reply,
            "generateQuote": generate_quote,
            "riskCheck": risk_check,
        },
    )


@mcp.tool()
def radar_save_interaction_candidates(candidates_json: str) -> dict[str, Any]:
    """Save Hermes-generated golden-window scores and interaction suggestions.

    candidates_json must be a JSON array. Each item should include contentId,
    windowScore, scoreReason, actionType, suggestedReply and/or suggestedQuote.
    """
    candidates = json.loads(candidates_json)
    return _request("POST", "/api/interaction-candidates", {"candidates": candidates})


@mcp.tool()
def radar_list_interaction_candidates(
    status: str = "",
    target_channel: str = "",
    run_id: str = "",
    platform: str = "",
    min_score: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """List saved golden-interaction-window candidates."""
    return _request(
        "GET",
        _query(
            "/api/interaction-candidates",
            {
                "status": status,
                "targetChannel": target_channel,
                "runId": run_id,
                "platform": platform,
                "minScore": min_score or "",
                "limit": limit,
            },
        ),
    )


@mcp.tool()
def radar_export_interaction_candidates(
    status: str = "",
    target_channel: str = "",
    limit: int = 100,
    output_format: str = "json",
) -> dict[str, Any]:
    """Export golden-interaction-window candidates as JSON, JSONL, or Markdown."""
    return _request(
        "GET",
        _query(
            "/api/interaction-candidates/export",
            {
                "status": status,
                "targetChannel": target_channel,
                "limit": limit,
                "format": output_format,
            },
        ),
    )


@mcp.tool()
def radar_push_interaction_candidates(
    candidate_ids: list[int],
    target_channel: str = "",
    push_status: str = "pushed",
) -> dict[str, Any]:
    """Mark interaction candidates as pushed to a downstream table/storage channel."""
    return _request(
        "POST",
        "/api/interaction-candidates/push",
        {
            "candidateIds": candidate_ids,
            "targetChannel": target_channel,
            "pushStatus": push_status,
        },
    )


@mcp.tool()
def radar_handoff_to_beemax(
    content_ids: list[int],
    translate_to_zh: bool = True,
    ocr_images: bool = True,
    summarize: bool = True,
    classify: bool = True,
    quality_score: bool = True,
) -> dict[str, Any]:
    """Compatibility alias for radar_handoff_to_organizer."""
    return radar_handoff_to_organizer(
        content_ids=content_ids,
        translate_to_zh=translate_to_zh,
        ocr_images=ocr_images,
        summarize=summarize,
        classify=classify,
        quality_score=quality_score,
    )


@mcp.tool()
def radar_organize_contents(
    content_ids: list[int],
    translate: bool = True,
    ocr_images: bool = True,
    download_media: bool = True,
) -> dict[str, Any]:
    """Organize selected raw content IDs. Use only IDs from radar_list_raw_contents."""
    return _request(
        "POST",
        "/api/organize",
        {
            "contentIds": content_ids,
            "translate": translate,
            "ocrImages": ocr_images,
            "downloadMedia": download_media,
        },
    )


@mcp.tool()
def radar_save_translation_result(
    content_id: int,
    translated_text_zh: str = "",
    ocr_text_original: str = "",
    ocr_text_zh: str = "",
    translation_provider: str = "hermes-agent",
) -> dict[str, Any]:
    """Save Hermes-generated Chinese translation and OCR results while preserving original text."""
    return _request(
        "POST",
        "/api/translation/save",
        {
            "contentId": content_id,
            "translatedTextZh": translated_text_zh,
            "ocrTextOriginal": ocr_text_original,
            "ocrTextZh": ocr_text_zh,
            "translationProvider": translation_provider,
        },
    )


@mcp.tool()
def radar_save_organized_content(
    content_id: int,
    organized_title: str,
    organized_summary: str,
    translated_text_zh: str = "",
    quality_score: float | None = None,
    quality_reason: str = "",
    content_category: str = "",
    organize_notes: str = "",
    review_status: str = "approved",
    publish_status: str = "pending",
) -> dict[str, Any]:
    """Save Hermes organizer output and move content into the organized archive."""
    return _request(
        "POST",
        "/api/organize/save",
        {
            "contentId": content_id,
            "organizedTitle": organized_title,
            "organizedSummary": organized_summary,
            "translatedTextZh": translated_text_zh,
            "qualityScore": quality_score,
            "qualityReason": quality_reason,
            "contentCategory": content_category,
            "organizeNotes": organize_notes,
            "reviewStatus": review_status,
            "publishStatus": publish_status,
        },
    )


@mcp.tool()
def radar_list_organized_contents(limit: int = 50) -> dict[str, Any]:
    """List organized/archive contents that can be reviewed or selected for publishing."""
    return _request("GET", _query("/api/organized", {"limit": limit}))


@mcp.tool()
def radar_list_publishable_contents(limit: int = 50) -> dict[str, Any]:
    """List approved organized contents that are pending publication."""
    return _request("GET", _query("/api/publishable", {"limit": limit}))


@mcp.tool()
def radar_publish_contents(content_ids: list[int], target_channel: str = "雷达号 APP") -> dict[str, Any]:
    """Publish selected organized content IDs to a target channel. Do not pass raw unorganized IDs."""
    return _request("POST", "/api/publish", {"contentIds": content_ids, "targetChannel": target_channel})


@mcp.tool()
def radar_get_run_report(run_id: str) -> dict[str, Any]:
    """Get a crawl, organize, or publish run report by run ID."""
    return _request("GET", f"/api/runs/{urllib.parse.quote(run_id)}")


@mcp.tool()
def radar_update_task_status(run_id: str, status: str, message: str = "") -> dict[str, Any]:
    """Update an employee task status after Hermes finishes or fails a workflow step."""
    return _request(
        "POST",
        f"/api/runs/{urllib.parse.quote(run_id)}/status",
        {"status": status, "message": message},
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
