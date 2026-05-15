# AGENTS.md

This repository is the Radar data-collection tool for Qianfeng AI / Hermes Agent workflows.

## Project Overview

Radar provides a data-collection MCP toolset. The product entry is the AI Agent. AI employees use Hermes tools to create collection tasks, fetch external content through feedgrab providers, store raw data and media metadata, and optionally hand selected raw content to downstream organization workflows.

The current first-stage product boundary is data collection:

1. User instruction from a Hermes/Qianfeng AI employee.
2. Radar parses the collection intent.
3. Radar creates a collection task.
4. feedgrab/provider performs platform collection.
5. Radar stores raw content, original URLs, media assets, metrics, raw payload, failures, and run reports.
6. Radar returns `agent_feedback` for the AI employee to answer the user.

Content organization, translation, OCR, analysis, and publishing are optional downstream capabilities. They can be handled by the same AI employee or by separate employees, but Radar must remain the shared source of truth.

Do not add or describe a standalone Radar user interface. Normal workflows must happen through the AI Agent calling Radar tools.

## Important Paths

- `crawler/` - Python backend, providers, database, feedgrab adapter, local Feishu/Markdown helpers.
- `crawler/web.py` - local HTTP API backend used by MCP tools.
- `crawler/providers.py` - X/API/RSS/XMCP/platform-gateway/browser provider routing.
- `crawler/beeclaw_adapter/` - Beeclaw adapter from upstream feedgrab unified output to Radar content items.
- `crawler/platform_mcp_gateway.py` - Platform MCP Manager/Gateway client used to call platform-managed backend MCPs.
- `tools/radar_mcp_server.py` - Hermes MCP server exposing Radar tools.
- `tools/hermes_skills/` - Hermes skill definitions copied to `~/.hermes/skills`.
- `docs/` - product, workflow, and deployment documentation.
- `tests/` - unittest coverage for parsing, providers, database, MCP, web workflow, and feedgrab mapping.
- `接口文档/` - legacy Radar mobile app API docs.
- `外网抓取账号0424.xlsx` - source account spreadsheet used by import flows.

## Local Runtime

Start the local Radar API service:

```bash
./tools/run_radar_api.sh
```

Default API URL:

```text
http://127.0.0.1:8780
```

When checking localhost from scripts, prefer:

```bash
curl --noproxy '*' http://127.0.0.1:8780/api/summary
```

Start local X MCP bridge when configured:

```bash
./tools/run_xmcp.sh
```

## Configuration

Do not commit real secrets.

- `.env` is local-only.
- `tools/xmcp/.env` is local-only.
- Use `tools/xmcp/.env.example` for documented settings.
- X/Youtube/LinkedIn/Instagram credentials must come from Hermes Secret, environment variables, or local ignored env files.

## Git Hygiene

Do not commit:

- `.env`
- `tools/xmcp/.env`
- `.external/`
- `.chrome-webbridge-profile/`
- `data/`
- `feishu_workspace/`
- generated weekly report artifacts
- Python caches

## Testing

Run the full backend test suite:

```bash
python3 -m unittest discover -s tests -v
```

## Editing Guidelines

- Preserve original collected text in `original_text`; translations belong in `translated_text_zh`.
- Do not overwrite raw content when organizing downstream content.
- Keep platform credentials out of source files.
- Prefer extending Radar APIs/tools over introducing parallel state stores.
- Keep provider failures explicit and visible in run reports.
- For X production, prefer `beeclaw:x` auto mode. In platform production, `x_mcp` should call the platform-managed `X MCP` through the configured Platform MCP Manager/Gateway with `RADAR_BACKEND_MCP_MODE=platform_gateway`; use `beeclaw:x_rss` as free fallback.
- Keep MCP tools as proxies to Radar HTTP APIs rather than importing `crawler.web` internals into the MCP process.
