---
name: radar-data-collection
description: Use when a Hermes or Qianfeng AI employee needs to collect external content through Radar and Beeclaw, inspect raw results, or export raw data for optional downstream organization.
---

# Radar Data Collection

## Boundary

Radar is the data collection tool behind the AI employee. The product entry is the Hermes/Qianfeng AI Agent. Beeclaw is Radar's public provider engine. The upstream feedgrab package is one replaceable backend behind Beeclaw, not the product-facing provider namespace. Organization, translation, OCR, summarization, classification, and quality judgment are optional downstream capabilities. They may be handled by the same AI employee if it has those tools, or by a separate content organization employee.

Use Radar MCP tools. Do not edit Radar files directly.

## Allowed Work

Use only these tools for this skill:

- `radar_list_providers`
- `radar_check_provider_health`
- `radar_check_production_readiness`
- `radar_list_mcp_integrations`
- `radar_list_strategies`
- `radar_agent_collect`
- `radar_create_collection_task`
- `radar_get_collection_task`
- `radar_list_raw_contents`
- `radar_get_raw_content_detail`
- `radar_list_media_assets`
- `radar_retry_media_asset`
- `radar_retry_media_assets`
- `radar_export_media_assets`
- `radar_retry_collection_task`
- `radar_export_raw_dataset`
- `radar_handoff_to_interaction_agent`
- `radar_save_interaction_candidates`
- `radar_list_interaction_candidates`
- `radar_export_interaction_candidates`
- `radar_push_interaction_candidates`
- `radar_xmcp_pressure_test`
- `radar_handoff_to_organizer`
- `radar_update_task_status`

## Optional Beeclaw CLI Adapter

If the Agent runtime cannot call MCP tools but can execute shell commands, use Beeclaw CLI as the command adapter:

```bash
./tools/beeclaw chat "采集 @OpenAI 最近 7 天原创 X 内容，保留图片和视频" --json
./tools/beeclaw collect --url https://example.com/feed.xml --platform rss --json
./tools/beeclaw task get <task_id> --json
```

CLI and MCP are equivalent integration paths at the Radar boundary: both call the same Radar HTTP API, both return structured execution results, and both preserve Radar as the source of truth. Prefer MCP for Hermes-native tool use; prefer CLI for command-only AI employee runtimes, cron, or server scripts.

## Rules

- Create collection tasks only.
- Do not translate, summarize, classify, approve, or publish content.
- Preserve original text exactly as collected.
- Preserve source URLs, media metadata, metrics, and raw payload.
- For large jobs, create queued tasks and let the worker execute them; do not pretend queued tasks have already collected content.
- Prefer named strategies from `radar_list_strategies`.
- For X, use `auto` by default. Radar exposes the public provider as `beeclaw:x` and auto-selects the execution backend in this order: `x_mcp` -> `x_api` -> `twitterapi_io` -> `x_rss` -> browser-session backends. Browser-session can be `cloud_browser_session`, `headless_browser_session`, or local `browser_session` depending on Radar configuration. The goal is to return useful collected content; do not stop at credits/API failures if a later backend can satisfy the user's requested result. Do not force XMCP unless the user explicitly asks for XMCP, production API/credits validation, or a named strategy requires it.
- Before a real X production rollout or batch increase, use `radar_xmcp_pressure_test` with `execute=false` to estimate selected accounts and API call volume. Use `execute=true` only after the user confirms credits are available.
- Use `beeclaw:x_rss` or `no-token` as the free fallback when X API/XMCP is unavailable or credits are insufficient. It can accept normal `@handle` or profile URL input.
- For non-X platforms, prefer URL/content collection through Beeclaw first: XHS, WeChat, YouTube, Bilibili, Douyin, Weibo, Zhihu, GitHub, Feishu, Kdocs, Youdao, RSS, Telegram, Reddit, HackerNews, Medium, LinuxDo, IDCFlare, Xiaoyuzhou, Ximalaya, and generic Web URLs.
- Treat `beeclaw:*` as the public provider and the listed backend as an implementation detail. Examples: `beeclaw:youtube -> youtube_api/yt-dlp/rss`, `beeclaw:xhs -> xiaohongshu-mcp/xhs-cli/universal_reader`, `beeclaw:github -> gh/github_api/universal_reader`, `beeclaw:rss -> rss_parser/universal_reader`, `beeclaw:web -> Jina Reader/universal_reader`. Current executable URL backends include Jina Reader for web, yt-dlp for YouTube, gh for GitHub, xhs-cli for XHS, rdt-cli for Reddit, and rss_parser for RSS/Atom feeds. Keyword collection is available for X, XHS, YouTube, and Reddit. RSS/Atom collection stores each feed entry as a separate raw content item. Unsupported or failed URL backends fall back to UniversalReader.
- Do not ask the user to choose a backend such as MCP, CLI, API, browser, Jina, or RSS. The user only provides the collection target; Radar/Beeclaw chooses and records the backend attempts.
- If a non-X task only provides an account name or keyword and Radar has no dedicated provider for that platform yet, return a structured provider limitation with the next required input, usually a source URL or an enabled platform MCP. Do not ask the user to choose an implementation backend.
- Use browser session as the final X fallback when official/API/RSS backends cannot return content and an authenticated cloud/headless/local browser session is available.
- If metrics are unavailable, state that they are unavailable; never fabricate metrics.
- Do not expose API tokens, cookies, or OAuth secrets.
- If the user asks about platform MCP integration, call `radar_list_mcp_integrations`. Explain that `Radar MCP` is the AI employee tool, while `X MCP`, `小红书 MCP`, and future platform MCPs are managed by the Qianfeng platform `MCP Manager`. Radar calls those backend MCPs through the Manager/Gateway; normal AI employees should not bypass Radar by directly composing raw platform tools for production collection.
- Do not tell end users to open a Radar UI for normal operation. Return task summaries, content IDs, source URLs, and export/handoff options through the AI Agent response.
- When the user asks for scheduled collection, Radar does not create or own the scheduler. Use `agent_feedback.runtime_schedule` to create the schedule in Hermes/Qianfeng Agent runtime. The scheduled job should call `radar_create_collection_task` with the provided `execution_payload`.
- When the user asks for organization, translation, OCR, scoring, or classification, generate an organizer handoff with `radar_handoff_to_organizer` instead of starting a new crawl.
- When the user asks for "黄金互动窗口", reply/quote opportunities, or interaction suggestions, first collect or select raw content, then call `radar_handoff_to_interaction_agent`. Score only the returned raw items, write candidates back with `radar_save_interaction_candidates`, and export or mark pushed through the interaction tools. Do not post, reply, quote, like, follow, or otherwise write to X directly.
- When the user asks to stop a running task, call `radar_update_task_status` with `status=cancelled`. Explain that cancellation is cooperative: queued child tasks and the next account are stopped, but a single in-flight provider call may finish before the task fully settles.

## Typical Flow

1. Check provider readiness with `radar_check_provider_health`.
2. For platform MCP setup or import questions, list visible integrations with `radar_list_mcp_integrations`.
3. List strategies with `radar_list_strategies`.
4. Send the user's original instruction to `radar_agent_collect`.
5. Use `radar_create_collection_task` only when the task is already structured or a system workflow requires explicit fields. For many URLs, pass newline- or comma-separated `urls`; Radar will create a parent batch task and queued child tasks. For imported Excel/source-account batches, pass platform/category/limit with `queue=true`; Radar will create one child task per account.
6. Read `agent_feedback` from the returned task. Use `agent_feedback.message` as the user-facing task result.
7. If `agent_feedback.status` is `requires_runtime_schedule`, create the schedule in Hermes/Qianfeng Agent runtime. Do not tell the user Radar has created a scheduled job.
8. Read task status with `radar_get_collection_task` if a collection task is still running.
9. Inspect results with `radar_list_raw_contents` and `radar_get_raw_content_detail`.
10. Retry failed collection tasks with `radar_retry_collection_task` when the user asks to rerun failures.
11. Inspect media assets and retry failed media with `radar_list_media_assets`, `radar_retry_media_asset`, or `radar_retry_media_assets` when needed.
12. Export selected task output with `radar_export_raw_dataset` when another agent needs a portable JSON/JSONL/Markdown dataset.
13. Export media manifests with `radar_export_media_assets` when downstream storage or object-sync workflows need media metadata.
14. If requested, hand selected raw content to an interaction-capable workflow with `radar_handoff_to_interaction_agent`; save generated candidates with `radar_save_interaction_candidates`.
15. If requested, hand selected raw content to an organizer-capable workflow with `radar_handoff_to_organizer`.

## Golden Interaction Window Flow

Use this when the user wants to find posts worth replying to, quoting, or tracking:

1. Collect target accounts or keywords with `radar_agent_collect` or `radar_create_collection_task`.
2. Select raw content IDs from the task output or with `radar_list_raw_contents`.
3. Call `radar_handoff_to_interaction_agent(content_ids=[...], target_channel="feishu_table")`.
4. For each handoff item, evaluate:
   - freshness and likely remaining interaction window
   - comments/reposts/likes/views velocity when available
   - account relevance and keyword match
   - reply/quote suitability
   - brand and compliance risk
5. Call `radar_save_interaction_candidates` with a JSON array. Each item should include `contentId`, `windowScore`, `scoreReason`, `actionType`, `suggestedReply`, `suggestedQuote`, `riskLevel`, `riskReason`, and `targetChannel`.
6. Use `radar_export_interaction_candidates` for Markdown/JSON delivery or `radar_push_interaction_candidates` to mark records as handed to table/Feishu/storage workflows.

## X MCP Pressure Test Flow

Use this before high-volume real X collection:

1. Call `radar_xmcp_pressure_test(handles="@OpenAI,@Anthropic", max_accounts=2, max_results=3, execute=false)`.
2. Report selected accounts and `estimatedApiCalls` to the user.
3. If the user confirms credits, call the same tool with `execute=true`.
4. Process queued child runs with the Radar worker or wait for the production worker.
5. Use `radar_get_collection_task` to report parent batch progress.

## Task Feedback

Every collection task response includes `agent_feedback` for the AI employee:

- `message`: concise user-facing result summary.
- `content_ids`: raw content IDs produced by the task.
- `top_contents`: first collected items with source URL, metrics, provider, and media count.
- `execution_backend`: the selected backend, for example `x_mcp`, `x_api`, `twitterapi_io`, `x_rss`, `Jina Reader`, `yt-dlp`, `gh`, `xhs-cli`, `rdt-cli`, `rss_parser`, or `beeclaw:universal_reader`. `provider` is the public Beeclaw route, for X normally `beeclaw:x`.
- `backend_attempts`: shows failed and successful backend attempts. For X it explains `x_mcp/x_api/twitterapi_io/x_rss` auto routing; for Beeclaw URL collection it explains CLI/Jina/UniversalReader fallback.
- `warnings`: data completeness warnings such as `metrics_incomplete` or `video_metadata_incomplete`.
- `errors`: failed account/provider details.
- `next_actions`: ready-to-call tool suggestions such as `radar_export_raw_dataset` and `radar_handoff_to_organizer`.
- `report_markdown`: Markdown report that can be sent to the user or saved.

When a task finishes, reply with `agent_feedback.message`, then offer the relevant `next_actions`. Do not invent counts outside `agent_feedback`.

## X Defaults

Default X collection:

- mode: `auto`
- public provider: `beeclaw:x`
- backend order: `x_mcp` -> `x_api` -> `twitterapi_io` -> `x_rss` -> `cloud_browser_session/headless_browser_session/local browser_session`
- date range: recent 7 days
- include original posts: true
- include quotes: true
- include replies: false
- include retweets: true for generic "X content" requests; false only when the user asks for original-only content or explicitly excludes retweets
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
