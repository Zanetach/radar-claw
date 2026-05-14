---
name: radar-data-collection
description: Use when a Hermes or Qianfeng AI employee needs to collect external content through Radar and feedgrab, inspect raw results, or export raw data for optional downstream organization.
---

# Radar Data Collection

## Boundary

Radar is the data collection tool behind the AI employee. The product entry is the Hermes/Qianfeng AI Agent. feedgrab is the platform collection kernel behind Radar. Organization, translation, OCR, summarization, classification, and quality judgment are optional downstream capabilities. They may be handled by the same AI employee if it has those tools, or by a separate content organization employee.

Use Radar MCP tools. Do not edit Radar files directly.

## Allowed Work

Use only these tools for this skill:

- `radar_list_providers`
- `radar_check_provider_health`
- `radar_list_strategies`
- `radar_agent_collect`
- `radar_create_collection_task`
- `radar_get_collection_task`
- `radar_list_raw_contents`
- `radar_get_raw_content_detail`
- `radar_export_raw_dataset`
- `radar_handoff_to_organizer`
- `radar_update_task_status`

## Rules

- Create collection tasks only.
- Do not translate, summarize, classify, approve, or publish content.
- Preserve original text exactly as collected.
- Preserve source URLs, media metadata, metrics, and raw payload.
- Prefer named strategies from `radar_list_strategies`.
- For X production, prefer `feedgrab:x_mcp`.
- Use `feedgrab:x_rss` or `no-token` as the free fallback when X API/XMCP is unavailable or credits are insufficient. It can accept normal `@handle` or profile URL input.
- For non-X platforms, prefer URL/content collection through feedgrab first: XHS, WeChat, YouTube, Bilibili, Douyin, Weibo, Zhihu, GitHub, Feishu, Kdocs, Youdao, RSS, Telegram, Reddit, HackerNews, Medium, LinuxDo, IDCFlare, Xiaoyuzhou, Ximalaya, and generic Web URLs.
- If a non-X task only provides an account name or keyword and Radar has no dedicated provider for that platform yet, ask for a URL or create a structured task that clearly reports the provider limitation.
- Use browser session only for debugging or low-volume validation.
- If metrics are unavailable, state that they are unavailable; never fabricate metrics.
- Do not expose API tokens, cookies, or OAuth secrets.
- Do not tell end users to open a Radar UI for normal operation. Return task summaries, content IDs, source URLs, and export/handoff options through the AI Agent response.
- When the user asks for organization, translation, OCR, scoring, or classification, generate an organizer handoff with `radar_handoff_to_organizer` instead of starting a new crawl.

## Typical Flow

1. Check provider readiness with `radar_check_provider_health`.
2. List strategies with `radar_list_strategies`.
3. Send the user's original instruction to `radar_agent_collect`.
4. Use `radar_create_collection_task` only when the task is already structured or a system workflow requires explicit fields.
5. Read `agent_feedback` from the returned task. Use `agent_feedback.message` as the user-facing task result.
6. Read task status with `radar_get_collection_task` if the task is scheduled or still running.
7. Inspect results with `radar_list_raw_contents` and `radar_get_raw_content_detail`.
8. Export selected task output with `radar_export_raw_dataset` when another agent needs a portable JSON/JSONL/Markdown dataset.
9. If requested, hand selected raw content to an organizer-capable workflow with `radar_handoff_to_organizer`.

## Task Feedback

Every collection task response includes `agent_feedback` for the AI employee:

- `message`: concise user-facing result summary.
- `content_ids`: raw content IDs produced by the task.
- `top_contents`: first collected items with source URL, metrics, provider, and media count.
- `errors`: failed account/provider details.
- `next_actions`: ready-to-call tool suggestions such as `radar_export_raw_dataset` and `radar_handoff_to_organizer`.
- `report_markdown`: Markdown report that can be sent to the user or saved.

When a task finishes, reply with `agent_feedback.message`, then offer the relevant `next_actions`. Do not invent counts outside `agent_feedback`.

## X Defaults

Default X collection:

- provider: `feedgrab:x_mcp`
- date range: recent 7 days
- include original posts: true
- include quotes: true
- include replies: false
- include retweets: false
- download images: true
- download videos: true

Recommended X MCP allowlist:

```bash
X_API_TOOL_ALLOWLIST="getUsersByUsername,getUsersPosts,getUsersIdPosts,getPosts,searchPostsRecent"
```

## Content Organizer Handoff

Use handoff payloads for downstream organization. The payload must include:

- `task_id`
- `content_ids`
- `handoff_type`
- `requirements`
- raw item text
- source URLs
- media assets
- metrics
- raw payload

Radar does not perform content organization work in this skill.
