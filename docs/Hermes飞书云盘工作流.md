# Hermes 飞书云盘 Markdown 工作流

本项目支持两套存储路径：

- 现有本地 SQLite 与 HTTP API：用于本地验证和调试。
- Hermes/飞书工作流：以飞书云盘 Markdown 为内容主存储，以飞书多维表为状态索引。

当前代码提供 `LocalFeishuStore`，用 `feishu_workspace/` 模拟飞书云盘和多维表。Hermes 接入真实飞书能力时，只需替换 store adapter；采集、整理、发布可以按需绑定到同一个 AI 员工，也可以拆成多个员工协作。

## 初始化飞书工作区

```bash
python3 -m crawler.hermes_agents --workspace feishu_workspace init-feishu --excel 外网抓取账号0424.xlsx
```

生成结构：

```text
feishu_workspace/
  bitable/
    source_accounts.json
    content_index.json
    agent_runs.json
  drive/Radar内容库/
    00_运行报告/
    01_待整理/
    02_待审核/
    03_待发布/
    04_已发布/
    99_失败/
```

## 内容抓取 Agent

```bash
python3 -m crawler.hermes_agents --workspace feishu_workspace crawler --platform youtube --mode no-token --max-results 5 --allow-failures
```

职责：

- 读取 `source_accounts`。
- 抓取内容。
- 为每条内容生成 Markdown 文件。
- upsert `content_index`。
- 写入 `00_运行报告/crawler/{run_id}.json`。

### X API via XMCP

生产环境建议让 Hermes 内容抓取 Agent 通过 X 官方 XMCP 调 X API。XMCP 仍然消耗 X API credits，不能绕过 `CreditsDepleted`。

准备只读 XMCP 配置：

```bash
cp tools/xmcp/.env.example tools/xmcp/.env
```

填写：

```text
X_OAUTH_CONSUMER_KEY=...
X_OAUTH_CONSUMER_SECRET=...
X_BEARER_TOKEN=...
X_API_TOOL_ALLOWLIST=getUsersByUsername,getUsersPosts,searchPostsRecent,getPostsById,getPostsByIds,getUsage
```

启动 XMCP：

```bash
tools/run_xmcp.sh
```

启动时 XMCP 会打开 OAuth1 授权页。完成授权后，本地 MCP endpoint 为：

```text
http://127.0.0.1:8000/mcp
```

本项目通过 `--mode xmcp` 调用：

```bash
XMCP_SERVER_URL=http://127.0.0.1:8000/mcp \
python3 -m crawler.hermes_agents --workspace feishu_workspace crawler --platform x --mode xmcp --max-results 20 --allow-failures
```

Hermes 生产部署时：

- `X_BEARER_TOKEN`、`X_OAUTH_CONSUMER_KEY`、`X_OAUTH_CONSUMER_SECRET` 放 Hermes Secret。
- XMCP 只开放只读 allowlist，不开放 `createPosts`、`likePost`、`deletePosts`、`followUser` 等写操作。
- `content_index` 仍用 `platform + original_content_id` 去重。
- X credits 必须大于 0；否则 XMCP 也会返回 `CreditsDepleted`。

## 内容整理 Agent

```bash
python3 -m crawler.hermes_agents --workspace feishu_workspace organizer --limit 3
```

职责：

- 查询 `organize_status = pending` 的内容。
- 读取 Markdown。
- 写入摘要、风险提示、发布建议。
- 移动到 `02_待审核`。
- 更新 `content_index`。

## 内容发布 Agent

```bash
python3 -m crawler.hermes_agents --workspace feishu_workspace publisher --target-app radar_app --limit 20 --dry-run
```

职责：

- 查询 `review_status = approved` 且 `publish_status = pending`。
- 读取 Markdown。
- 生成 dry-run 发布记录。
- 更新 `publish_records` 和运行报告。

真实发布接口确定后，将 dry-run 部分替换为内部 APP HTTP API 或 browser-session 调用。

## Hermes 通知

每个 Agent 运行结束后都会生成标准 JSON 报告。Hermes Agent 使用自己绑定的飞书智能体机器人读取报告并通知。

项目代码不保存飞书 webhook、机器人 token 或 OAuth 凭证。
