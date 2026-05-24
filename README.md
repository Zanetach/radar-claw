# Radar Claw

Radar Claw is the data-collection tool layer for Qianfeng AI / Hermes Agent workflows.

The product entry is the AI Agent. Radar runs behind the Agent: it receives tool calls, creates collection tasks, calls Beeclaw platform providers, stores raw content and media metadata, and returns structured execution results to the AI employee.

## Current Scope

Radar Claw is focused on the collection layer:

- intent parsing from AI employee chat instructions
- collection task creation and status tracking
- Beeclaw provider execution
- raw content storage in SQLite
- media asset metadata and optional local media download
- provider failures and run reports
- MCP tools for Hermes Agent integration
- optional raw-data handoff for downstream organization or analysis

Translation, OCR, summarization, classification, and publishing are optional downstream capabilities. They can run in the same AI employee or in separate employees, but Radar remains the source of truth for raw collected data.

Radar does not ship a standalone user interface. End users interact through Qianfeng/Hermes AI employees; Radar exposes HTTP APIs and MCP tools for those employees.

## Beeclaw Platform Coverage

Radar exposes Beeclaw as its public provider engine. The upstream `iBigQiang/feedgrab` package remains a replaceable backend behind Beeclaw. Current Radar support is:

- Account/search routes: X/Twitter defaults to `provider=beeclaw:x`, `mode=auto`, which auto-selects `x_mcp`, `x_api`, `twitterapi_io`, `x_rss`, then browser-session backends; XHS keyword search runs through `beeclaw:xhs`.
- URL/content routes through Beeclaw: XHS, WeChat official account articles, YouTube, Bilibili, Douyin, Weibo, Zhihu, GitHub, Feishu, Kdocs, Youdao, RSS, Telegram, Reddit, HackerNews, Medium, LinuxDo, IDCFlare, Xiaoyuzhou, Ximalaya, and generic Web URLs.
- Key backend hierarchy is exposed in `/api/providers` and `/api/providers/health`: `beeclaw:x` can use `x_mcp/x_api/twitterapi_io/x_rss/twitter-cli/cloud_browser_session/headless_browser_session/local_browser_session`; `beeclaw:youtube` can use `yt-dlp/youtube_api/rss`; `beeclaw:xhs` can use `xiaohongshu-mcp/xhs-cli/universal_reader`; `beeclaw:reddit` can use `rdt-cli/reddit_api/universal_reader`; `beeclaw:github` can use `gh/github_api/universal_reader`; `beeclaw:rss` can use `rss_parser/universal_reader`; `beeclaw:web` can use `Jina Reader/agent-browser/universal_reader`.
- Executable backend adapters are currently wired for `beeclaw:web -> Jina Reader/agent-browser`, `beeclaw:youtube -> yt-dlp`, `beeclaw:github -> gh`, `beeclaw:xhs -> xhs-cli`, `beeclaw:reddit -> rdt-cli`, and `beeclaw:rss -> rss_parser`, with upstream `feedgrab` UniversalReader as fallback when a backend is unavailable or fails. RSS/Atom feeds are expanded so each feed entry is stored as its own raw content row.

For URL/content routes, the AI employee can pass a source URL to `radar_agent_collect` or `radar_create_collection_task`; Radar identifies the platform, calls Beeclaw, stores raw text, source URL, metadata, media asset metadata, and the raw payload. Account-level and keyword-level deep crawling is enabled platform by platform.

URL collection defaults to automatic backend routing. Users and AI employees do
not need to specify a backend. Radar infers the platform from the URL, tries the
platform-specific backend first, then generic readers, then upstream
UniversalReader. The selected route and all failed attempts are saved in
`backend_attempts`.

Current URL backend order:

```text
YouTube URL: yt-dlp -> Jina Reader -> agent-browser -> universal_reader
GitHub URL: gh -> Jina Reader -> agent-browser -> universal_reader
XHS URL: xhs-cli -> Jina Reader -> agent-browser -> universal_reader
Reddit URL: rdt-cli -> Jina Reader -> agent-browser -> universal_reader
RSS/Atom URL: rss_parser -> Jina Reader -> agent-browser -> universal_reader
Other platform URL: Jina Reader -> agent-browser -> universal_reader
```

In task feedback, `provider` is the public Radar route such as `beeclaw:x` or `beeclaw:github`; `execution_backend` records the selected backend such as `x_mcp`, `x_api`, `twitterapi_io`, `x_rss`, `Jina Reader`, `yt-dlp`, `gh`, `xhs-cli`, `rdt-cli`, `rss_parser`, or `beeclaw:universal_reader`. `backend_attempts` records successful backend selection and fallback attempts for production debugging.

X browser-session fallback supports three execution modes and does not require
a visible local browser when cloud/headless mode is configured:

```bash
# Cloud browser worker, for Browserbase or a self-hosted Playwright service.
export BEECLAW_X_BROWSER_SESSION_MODE=cloud
export BEECLAW_X_BROWSER_ENDPOINT='https://browser-worker.example.com/x/profile-posts'
export BEECLAW_X_BROWSER_API_KEY='<secret>'
export BEECLAW_X_BROWSER_PROVIDER=browserbase

# Headless command on the same server. Command must output JSON with items/tweets.
export BEECLAW_X_BROWSER_SESSION_MODE=headless
export BEECLAW_X_BROWSER_CMD='/opt/beeclaw/x-browser --json {handle} {max_results}'
export BEECLAW_X_BROWSER_PROFILE_DIR='/srv/beeclaw/x-profile'

# Local development fallback using Chrome WebBridge.
export BEECLAW_X_BROWSER_SESSION_MODE=local
export WEBBRIDGE_URL='http://127.0.0.1:10086'
```

The browser worker/command contract is JSON. It should return either
`{"items": [...]}` or `{"tweets": [...]}`. Each item can include `id`, `text`,
`url`, `published_at`, `view_count`, `like_count`, `reply_count`,
`retweet_count`, and `media_assets`. Radar stores these as raw content and
records the selected backend as `cloud_browser_session`,
`headless_browser_session`, or `browser_session`.

CLI backend command lines can be overridden when the local tool uses a different syntax:

```bash
export BEECLAW_XHS_CLI_CMD='xhs-cli --json {url}'
export BEECLAW_RDT_CLI_CMD='rdt-cli --json {url}'
export BEECLAW_AGENT_BROWSER_CMD='agent-browser --json {url}'
```

### Bundled Beeclaw CLI Tools

Radar also ships project-local CLI wrappers under `tools/beeclaw-bin/` so
deployments do not depend on global `PATH` state:

```text
tools/beeclaw-bin/yt-dlp
tools/beeclaw-bin/xhs-cli
tools/beeclaw-bin/rdt-cli
tools/beeclaw-bin/twitter-cli
tools/beeclaw-bin/agent-browser
```

Install the local CLI bundle after creating the Radar environment:

```bash
./tools/install_beeclaw_clis.sh
```

`yt-dlp` is installed into the Radar venv (`RADAR_VENV_DIR`, default
`/Users/zane/.radar-venv`) and exposed through the bundled wrapper.
The bundled `xhs-cli`, `rdt-cli`, and `twitter-cli` provide no-key compatible
readers for lightweight fallback/testing. For production-grade XHS/Reddit/X
deep collection, override them with real platform CLIs or MCP/API backends:

```bash
export BEECLAW_XHS_CLI_CMD='/opt/beeclaw/xhs-cli --json {url}'
export BEECLAW_RDT_CLI_CMD='/opt/beeclaw/rdt-cli --json {url}'
export BEECLAW_TWITTER_CLI_BIN='/opt/beeclaw/twitter-cli'
```

`agent-browser` is optional and intended for rendered-page capture on pages
where static readers are not enough. On cloud servers without a visible desktop,
configure it as either a remote extraction endpoint or an external headless
command:

```bash
# Option A: Radar calls a cloud/headless browser worker.
export BEECLAW_AGENT_BROWSER_ENDPOINT='https://browser-worker.example.com/extract'
export AGENT_BROWSER_MODE=headless
export AGENT_BROWSER_HEADLESS=true
export AGENT_BROWSER_API_KEY='<secret>'

# Option B: Radar calls a JSON-producing local command.
export BEECLAW_AGENT_BROWSER_CMD='/opt/agent-browser/extract --json {url}'
```

When no real browser command or endpoint is configured, the bundled
`tools/beeclaw-bin/agent-browser` falls back to Jina Reader for lightweight
testing and marks the result as `bundled-agent-browser`.

Run the real platform smoke matrix through Radar API:

```bash
# Dry-run all URL/account/keyword cases and show missing inputs.
./tools/beeclaw_platform_smoke.py --platforms all --types url,account,keyword

# Execute a safe URL subset.
./tools/beeclaw_platform_smoke.py --execute --platforms web,rss,github,youtube,reddit --types url --limit 2

# Test web URL capture through the agent-browser backend.
./tools/beeclaw_platform_smoke.py --execute --platforms web --types url --backend agent-browser
```

For platforms without public default samples, provide real test inputs through
environment variables such as `BEECLAW_SMOKE_XHS_URL`,
`BEECLAW_SMOKE_WECHAT_URL`, `BEECLAW_SMOKE_X_ACCOUNT`, or
`BEECLAW_SMOKE_YOUTUBE_KEYWORD`.

Scheduled collection is owned by the AI Agent runtime, not by Radar. When a user asks for "daily", "every hour", or similar scheduling, Radar returns `agent_feedback.status=requires_runtime_schedule` with a `runtime_schedule` payload. Hermes/Qianfeng runtime should create the schedule and call `radar_create_collection_task` with the provided `execution_payload` at runtime.

## Architecture

```text
User
  -> Qianfeng / Hermes AI employee
  -> Radar MCP tools
  -> Radar collection task
  -> Beeclaw provider
  -> external platform
  -> Radar raw data store
  -> agent_feedback / optional organizer handoff
```

Detailed product scope, collection flow, and architecture are documented in [docs/千蜂AI-Radar数据采集工具PRD.md](docs/千蜂AI-Radar数据采集工具PRD.md).
Agent-browser backend and real platform smoke testing are documented in [docs/Beeclaw-agent-browser与真实平台测试.md](docs/Beeclaw-agent-browser与真实平台测试.md).
Current capability review, capability descriptions, verification evidence, and remaining risks are documented in [docs/radar-capability-review.md](docs/radar-capability-review.md).

## Key Directories

- `crawler/` - Python backend, database, providers, Beeclaw/feedgrab backend adapter, local storage helpers.
- `tools/radar_mcp_server.py` - Hermes MCP server exposing Radar tools.
- `tools/hermes_skills/` - Hermes skill definitions.
- `docs/` - PRD, workflow, and setup documentation.
- `tests/` - unit tests for backend, providers, MCP tools, and workflow behavior.

## Local Setup

NPX one-command install from GitHub:

```bash
npx github:Zanetach/radar-claw install
```

This installs the package into `~/.beeclaw-radar`, runs the same
`tools/install_beeclaw.sh` installer, and starts the Radar API service
automatically. After installation:

```bash
npx github:Zanetach/radar-claw doctor
```

Shell one-liner for agents that prefer curl:

```bash
curl -fsSL https://raw.githubusercontent.com/Zanetach/radar-claw/main/install.sh | bash
```

Install without service autostart:

```bash
npx github:Zanetach/radar-claw install --no-start
```

Recommended unified install:

```bash
./tools/install_beeclaw.sh
```

This creates/updates the Python runtime, installs Beeclaw backend wrappers,
installs Hermes Radar skills/MCP config, and runs a local doctor check.

Create or reuse the Radar virtual environment and start the local Radar API service:

```bash
./tools/install_beeclaw.sh start-api
```

Default local API URL:

```text
http://127.0.0.1:8780
```

Health check:

```bash
curl --noproxy '*' http://127.0.0.1:8780/api/summary
```

Build a handoff package:

```bash
./tools/package_beeclaw_release.sh
```

The generated `dist/beeclaw-radar-*.tar.gz` excludes local secrets, runtime
data, media files, reports, browser profiles, caches, and git metadata.

Unified installation and usage details are documented in
[docs/Beeclaw统一安装与使用手册.md](docs/Beeclaw统一安装与使用手册.md).

## Platform MCP Manager and Backend MCPs

In Qianfeng AI, MCP integrations are managed by the platform runtime. Radar is
the collection tool execution layer: AI employees call `Radar MCP`, and Radar
calls backend MCPs such as `X MCP` and `小红书 MCP` through the platform
`MCP Manager` / Gateway.

Production MCP Manager/Gateway configuration is injected by the platform. Use
generic variable names by default; `QF_MCP_*` aliases are accepted for Qianfeng
deployments.

```bash
RADAR_BACKEND_MCP_MODE=platform_gateway
MCP_MANAGER_NAME=platform-mcp-manager
MCP_MANAGER_DISPLAY_NAME="Platform MCP Manager"
MCP_MANAGER_MANAGED_BY=platform_runtime
PLATFORM_MCP_GATEWAY_URL=https://platform.example.com/mcp-gateway
PLATFORM_MCP_WORKSPACE_ID=<workspace-id>
PLATFORM_MCP_RUNTIME_TOKEN=<runtime-secret>
```

Radar sends MCP Manager/Gateway requests in this shape:

```json
{
  "integration": "x-mcp",
  "tool": "searchPostsRecent",
  "arguments": {"query": "from:elonmusk", "max_results": 20},
  "trace_id": "collection-task-id"
}
```

Secrets stay in the platform. Radar only receives backend MCP results, stores
raw content/media/metrics, and returns `agent_feedback`.

For local development without the platform MCP Manager/Gateway, copy the
example X MCP config and fill it locally:

```bash
cp tools/xmcp/.env.example tools/xmcp/.env
```

Start the local X MCP bridge:

```bash
./tools/run_xmcp.sh
```

Real credentials must stay in local ignored env files or Hermes Secrets. Do not commit tokens.

### Qianfeng MCP Integration Visibility

Qianfeng platform should display Radar and backend MCP integrations:

```text
Radar MCP: AI employee tool entrypoint
X MCP: backend platform connector used by Radar / Beeclaw X provider
小红书 MCP: backend platform connector used by Radar / Beeclaw XHS provider
TwitterAPI.io: optional third-party read-only X data backend used by Radar / Beeclaw X provider
```

Radar exposes this platform-facing catalog at:

```bash
curl --noproxy '*' http://127.0.0.1:8780/api/mcp/integrations
```

Bind normal data-collection AI employees to `Radar MCP`. Keep backend MCPs
visible for configuration, connection checks, credits/session diagnostics, and
admin debugging, but do not bind raw platform tools to ordinary AI employees by
default. Production collection should stay inside Radar's task, storage,
dedupe, fallback, and report chain.

Optional TwitterAPI.io production config belongs in the platform Secret/MCP
Manager, not in source code:

```bash
TWITTERAPI_IO_KEY=<secret>
TWITTERAPI_IO_BASE_URL=https://api.twitterapi.io
TWITTERAPI_IO_READ_ONLY=true
```

Radar exposes it as the `twitterapi-io` backend integration and as
`execution_backend=twitterapi_io` under `provider=beeclaw:x`. Keep it read-only:
do not expose tweet creation, likes, follows, DMs, login, or upload endpoints to
normal data-collection AI employees.

See [`tools/platform-mcp-integrations.example.yaml`](tools/platform-mcp-integrations.example.yaml)
for a production-side integration template covering Radar MCP, X MCP,
小红书 MCP, and TwitterAPI.io.

### X MCP Pressure Test

Radar exposes a bounded pressure-test entry for real X MCP / credits validation:

```bash
curl --noproxy '*' -X POST http://127.0.0.1:8780/api/providers/xmcp/pressure-test \
  -H 'Content-Type: application/json' \
  -d '{"handles":["@OpenAI","@Anthropic"],"maxAccounts":2,"maxResults":3,"execute":false}'
```

`execute:false` returns the selected accounts, estimated API calls, and safety guard without consuming credits. Use `execute:true` only when the X MCP server is configured and the account has available X API credits; Radar will create a parent batch run and one queued child run per account with `mode=beeclaw:x_mcp`.

## Hermes Integration

Radar exposes MCP tools through:

```bash
python3 tools/radar_mcp_server.py
```

Important tools:

- `radar_agent_collect`
- `radar_list_mcp_integrations`
- `radar_create_collection_task`
- `radar_get_collection_task`
- `radar_list_raw_contents`
- `radar_get_raw_content_detail`
- `radar_list_media_assets`
- `radar_retry_media_asset`
- `radar_retry_media_assets`
- `radar_export_media_assets`
- `radar_xmcp_pressure_test`
- `radar_retry_collection_task`
- `radar_export_raw_dataset`
- `radar_handoff_to_interaction_agent`
- `radar_save_interaction_candidates`
- `radar_list_interaction_candidates`
- `radar_export_interaction_candidates`
- `radar_push_interaction_candidates`
- `radar_handoff_to_organizer`
- `radar_update_task_status`

## Golden Interaction Window Workflow

Radar can support an AI employee workflow for "黄金互动窗口":

```text
set target accounts / keywords
  -> collect posts, media, and metrics through Radar
  -> hand selected raw content to Hermes interaction scoring
  -> save window scores and reply/quote suggestions
  -> export or mark pushed to table / Feishu / storage workflows
```

Radar stores the generated candidates in `interaction_candidates`. It does not
auto-reply, auto-quote, like, follow, or perform any X write action. Downstream
table/Feishu/storage pushes should consume `radar_export_interaction_candidates`
or use `radar_push_interaction_candidates` to mark handoff status.

Queued collection tasks can be processed locally with:

```bash
python3 -m crawler worker --limit 10
```

Run a production polling worker with:

```bash
python3 -m crawler worker --daemon --limit 0 --poll-interval 5 --idle-limit 0 --retry-delay 60
```

Large URL batches can use the same collection tool with newline/comma separated
`urls`; Radar creates one parent batch task and queued child tasks for the worker.
Queued account-source tasks also split imported Excel/source accounts into one
child task per account.

Running task cancellation is best-effort and cooperative. Setting a run to
`cancelled` stops the account loop before the next account and prevents final
status overwrite, while an already-blocking external provider call may continue
until that call returns. Production hard-kill requires process-level isolation
around provider execution.

## Beeclaw Agent CLI

Beeclaw CLI is a command-style adapter for AI employee runtimes and local operators that can execute shell tools. It does not replace MCP; both MCP and CLI call the same Radar HTTP API and write to the same task/content tables.

Use MCP inside Hermes when tool discovery is available. Use CLI when an Agent runtime only supports command tools, shell tools, cron jobs, or server scripts.

```bash
./tools/beeclaw provider list --platform rss
./tools/beeclaw chat "采集 @OpenAI 最近 7 天原创 X 内容，保留图片和视频"
./tools/beeclaw chat "采集 @OpenAI 最近 7 天原创 X 内容，保留图片和视频" --json
./tools/beeclaw collect --url https://example.com/feed.xml --platform rss --json
./tools/beeclaw task get crawl-20260514-000000-demo --json
```

If Radar API is not running, the CLI exits non-zero and prints:

```bash
./tools/run_radar_api.sh
```

After updating MCP tools or skills in a running Hermes session, reload MCP from Hermes:

```text
/reload-mcp
```

## Tests

Run backend tests:

```bash
python3 -m unittest discover -s tests -v
```

## Security

The repository intentionally ignores local runtime state and secrets:

- `.env`
- `tools/xmcp/.env`
- `.external/`
- `.chrome-webbridge-profile/`
- `data/`
- `feishu_workspace/`

Only commit source code, docs, tests, scripts, and non-secret examples.
