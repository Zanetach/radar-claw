# Radar Claw

Radar Claw is the data-collection tool layer for Qianfeng AI / Hermes Agent workflows.

It lets an AI employee receive a natural-language collection request, create a Radar collection task, call feedgrab-backed platform providers, store raw content and media metadata, and return a structured task result to the user.

## Current Scope

Radar Claw is focused on the collection layer:

- intent parsing from AI employee chat instructions
- collection task creation and status tracking
- feedgrab/provider execution
- raw content storage in SQLite
- media asset metadata and optional local media download
- provider failures and run reports
- MCP tools for Hermes Agent integration
- optional raw-data handoff for downstream organization or analysis

Translation, OCR, summarization, classification, and publishing are optional downstream capabilities. They can run in the same AI employee or in separate employees, but Radar remains the source of truth for raw collected data.

## Architecture

```text
User
  -> Qianfeng / Hermes AI employee
  -> Radar MCP tools
  -> Radar collection task
  -> feedgrab provider
  -> external platform
  -> Radar raw data store
  -> agent_feedback / optional organizer handoff
```

## Key Directories

- `crawler/` - Python backend, database, providers, feedgrab adapter, local storage helpers.
- `web/` - local workspace UI built with native HTML/CSS/JS.
- `tools/radar_mcp_server.py` - Hermes MCP server exposing Radar tools.
- `tools/hermes_skills/` - Hermes skill definitions.
- `docs/` - PRD, workflow, and setup documentation.
- `tests/` - unit tests for backend, providers, MCP tools, and workflow behavior.
- `接口文档/` - legacy Radar mobile app API documentation.

## Local Setup

Create or reuse the Radar virtual environment and start the web app:

```bash
./tools/run_radar_web.sh
```

Default local URL:

```text
http://127.0.0.1:8780
```

Health check:

```bash
curl --noproxy '*' http://127.0.0.1:8780/api/summary
```

## X MCP

Copy the example config and fill it locally:

```bash
cp tools/xmcp/.env.example tools/xmcp/.env
```

Start the local X MCP bridge:

```bash
./tools/run_xmcp.sh
```

Real credentials must stay in local ignored env files or Hermes Secrets. Do not commit tokens.

## Hermes Integration

Radar exposes MCP tools through:

```bash
python3 tools/radar_mcp_server.py
```

Important tools:

- `radar_agent_collect`
- `radar_create_collection_task`
- `radar_get_collection_task`
- `radar_list_raw_contents`
- `radar_get_raw_content_detail`
- `radar_export_raw_dataset`
- `radar_handoff_to_organizer`

After updating MCP tools or skills in a running Hermes session, reload MCP from Hermes:

```text
/reload-mcp
```

## Tests

Run backend tests:

```bash
python3 -m unittest discover -s tests -v
```

Check frontend JavaScript syntax:

```bash
node --check web/app.js
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
