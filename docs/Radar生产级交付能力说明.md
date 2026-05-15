# Radar 生产级交付能力说明

更新时间：2026-05-15

## 1. 交付结论

Radar 当前已经可以作为千蜂 AI / Hermes Agent Runtime 的生产级“数据采集工具”交付。

交付边界是：

```text
AI 员工下发采集任务
-> Radar MCP 接收
-> Radar API 创建 collection task
-> Beeclaw provider 路由执行采集
-> 原始内容、媒体、指标、失败记录入库
-> agent_feedback 回传给 AI 员工
```

Radar v1 负责采集闭环，不内置内容整理、翻译、OCR、分类、质量判断和发布。后续处理由同一个 AI 员工继续调用能力完成，或由独立内容整理 AI 员工读取 Radar 已采集数据完成。

当前生产就绪状态：

```text
项目侧：可交付
外部侧：需要完成千蜂 Platform MCP Gateway 接入、X credits 生产压测、小红书等 backend MCP 接入验收
```

本地生产就绪检查接口：

```bash
curl --noproxy '*' http://127.0.0.1:8780/api/production-readiness
```

当前本地返回：

```text
overallStatus = requires_external_configuration
totalChecks = 6
implementedProjectSide = 5
blocking = 1
```

阻塞项不是 Radar 代码能力，而是平台生产环境尚未注入 `Platform MCP Gateway`。

## 2. 已可交付能力

### 2.1 AI 员工入口

AI 员工通过 Radar MCP 使用采集能力，不需要直接操作 Radar Web。

已暴露核心 MCP 工具：

| 工具 | 作用 | 生产状态 |
| --- | --- | --- |
| `radar_agent_collect` | 自然语言采集入口 | 可交付 |
| `radar_create_collection_task` | 结构化创建采集任务 | 可交付 |
| `radar_get_collection_task` | 查询任务状态与反馈 | 可交付 |
| `radar_list_raw_contents` | 查询已采集原始数据 | 可交付 |
| `radar_get_raw_content_detail` | 读取单条内容详情 | 可交付 |
| `radar_export_raw_dataset` | 导出原始数据集 | 可交付 |
| `radar_list_media_assets` | 查询媒体资产 | 可交付 |
| `radar_retry_media_asset(s)` | 媒体失败重试 | 可交付 |
| `radar_export_media_assets` | 导出媒体 manifest | 可交付 |
| `radar_xmcp_pressure_test` | X MCP credits 受控压测 | 可交付，需生产 credits 验收 |
| `radar_check_provider_health` | provider 健康检查 | 可交付 |
| `radar_check_production_readiness` | 生产就绪检查 | 可交付 |
| `radar_list_mcp_integrations` | 查看平台 MCP 集成状态 | 可交付 |

### 2.2 Platform MCP Manager / Gateway 抽象

Radar 已支持平台 MCP 控制面抽象，不再写死千蜂实现名称。

支持环境变量：

```bash
RADAR_BACKEND_MCP_MODE=platform_gateway
PLATFORM_MCP_GATEWAY_URL=<platform gateway url>
PLATFORM_MCP_WORKSPACE_ID=<workspace id>
PLATFORM_MCP_RUNTIME_TOKEN=<runtime token>
```

兼容别名：

```bash
MCP_GATEWAY_URL
MCP_WORKSPACE_ID
MCP_RUNTIME_TOKEN
QF_MCP_*
QIANFENG_MCP_*
```

生产模式下：

- 千蜂平台 MCP Manager 管理 X MCP、小红书 MCP、未来平台 MCP。
- Radar 通过 Gateway 调用 backend MCP。
- Radar 不保存平台 token。
- AI 员工默认只绑定 Radar MCP，不直接操作底层平台 MCP。

### 2.3 Beeclaw Provider Engine

Beeclaw 是 Radar 对外 provider namespace。底层 backend 可替换。

统一语义：

```text
provider = beeclaw:<platform>
execution_backend = 实际执行 backend
```

X 示例：

```text
provider=beeclaw:x
execution_backend=x_mcp / x_api / twitterapi_io / x_rss / browser_session
```

当前已纳入 provider catalog 的平台：

```text
X / Twitter
小红书 / XHS
微信公众号 / WeChat
YouTube
Bilibili
抖音 / Douyin
微博 / Weibo
知乎 / Zhihu
GitHub
飞书 / Feishu
金山文档 / Kdocs
有道云笔记 / Youdao
RSS
Telegram
Reddit
HackerNews
Medium
LinuxDo
IDCFlare
小宇宙
喜马拉雅
通用 Web URL
```

需要区分：

- 已纳入 provider 框架：可配置、可路由、可记录 provider / backend。
- 已完成生产深度采集：需要真实 backend、凭证、限流、媒体、失败重试全部验收。

### 2.4 X / Twitter 生产链路

X 是当前最完整的生产主链路。

已支持：

- `beeclaw:x` 默认 `mode=auto`。
- 自动选择 backend：`x_mcp -> x_api -> twitterapi_io -> x_rss -> browser_session`。
- 账号 posts。
- keyword recent search。
- 单条 post 详情。
- metrics / media metadata。
- 图片和视频媒体 metadata。
- X API credits 不足时结构化失败。
- `x_rss` 免费 fallback。
- 生产前受控压测：`radar_xmcp_pressure_test`。

压测方式：

```text
execute=false：只估算账号数、条数、预估 API 调用量，不消耗真实采集额度。
execute=true：创建受控 queued batch，进入 worker 执行。
```

生产验收要求：

- X MCP 在千蜂平台 Manager 中 connected。
- X API credits 可用。
- allowlist 只开放只读工具。
- 小批量账号压测通过。
- rate limit / credits depleted / auth failed 都能进入 `backend_attempts` 和 run report。

### 2.5 大任务队列和 worker

已支持：

- `queue=true` 创建 queued 任务。
- 批量 URL 拆分父子任务。
- Excel / 账号源批量任务按账号拆子任务。
- worker 领取 queued 任务执行。
- `attempt_count`、`max_attempts`、`next_attempt_at`。
- 失败自动回队列重试。
- 手动 retry。
- paused / cancelled 状态。
- 运行中任务协作式取消。
- 父任务聚合子任务成功数、失败数、保存数和报告。

worker 命令：

```bash
python3 -m crawler worker --daemon --limit 0 --poll-interval 5 --idle-limit 0 --retry-delay 60
```

生产部署需要用 systemd、Supervisor、K8s Deployment 或千蜂平台任务运行器托管该 worker。

当前限制：

```text
单个阻塞 provider 调用无法被进程内强制杀掉，只能在调用返回后协作式停止。
```

如果要强制中断单个阻塞调用，需要增加子进程隔离执行器。

### 2.6 原始数据存储

Radar 当前本地使用 SQLite 作为开发和单机部署存储，数据模型已按生产语义设计。

核心表：

| 表 | 作用 |
| --- | --- |
| `source_accounts` | 账号源 |
| `crawl_runs` | 采集任务 / 员工任务 |
| `crawl_run_contents` | 任务与内容关联 |
| `source_contents` | 原始内容主表 |
| `media_assets` | 图片 / 视频 / 媒体资产 |
| `crawl_failures` | 采集失败记录 |
| `crawl_strategies` | 采集策略 |
| `interaction_candidates` | 黄金互动窗口候选 |

原始内容必须保留：

- 原文正文。
- 原始链接。
- 原始平台 ID。
- metrics。
- media assets。
- raw payload。
- provider / execution_backend。
- fetch time。

### 2.7 media_assets 生产化

已支持：

- 独立 `media_assets` 表。
- 图片 / 视频 download status。
- `pending / downloaded / failed` 状态。
- 错误原因。
- retry count。
- last attempt time。
- 本地路径。
- manifest 导出。
- 单个和批量媒体重试。

API：

```text
GET  /api/media-assets
POST /api/media-assets/{id}/retry
POST /api/media-assets/retry
GET  /api/media-assets/export
```

待生产接入：

```text
对象存储 bucket、签名上传、CDN/访问权限策略。
```

### 2.8 agent_feedback 标准化

每个采集任务都会返回 `agent_feedback`，供 AI 员工直接回复用户。

标准字段：

```json
{
  "message": "采集完成：保存 4 条，失败 0 个。",
  "summary": {},
  "content_ids": [],
  "top_contents": [],
  "backend_attempts": [],
  "warnings": [],
  "next_actions": [],
  "report_markdown": ""
}
```

AI 员工必须遵守：

- 回复用户优先使用 `agent_feedback.message`。
- 不自行编造保存数量、backend、成功状态。
- 需要整理时使用 `next_actions` 里的 handoff。
- 需要导出时调用 `radar_export_raw_dataset` 或 `radar_export_media_assets`。

## 3. 生产部署架构

### 3.1 推荐部署结构

```text
千蜂 AI Agent Runtime
  |
  | AI 员工绑定
  v
Radar MCP
  |
  v
Radar API
  |
  +-- SQLite / 后续可替换 Postgres
  +-- media storage
  +-- worker
  |
  v
Beeclaw Provider Router
  |
  +-- Platform MCP Gateway
  |     +-- X MCP
  |     +-- 小红书 MCP
  |     +-- 未来平台 MCP
  |
  +-- fallback backend
        +-- X API
        +-- x-rss
        +-- browser-session
        +-- Jina Reader
        +-- RSS parser
        +-- gh / CLI tools
```

### 3.2 服务组件

| 组件 | 是否必须 | 作用 |
| --- | --- | --- |
| Radar API | 必须 | 任务、采集、入库、查询、反馈 |
| Radar MCP | 必须 | AI 员工工具入口 |
| Radar Skill | 必须 | 约束 AI 员工如何使用 Radar |
| Worker | 生产必须 | 执行 queued / batch / retry 任务 |
| Platform MCP Gateway | 生产必须 | 统一调用平台 backend MCP |
| X MCP | X 生产必须 | 官方 X 数据采集 |
| 小红书 MCP | 小红书生产必须 | 小红书平台采集 |
| 对象存储 | 媒体生产建议必须 | 图片 / 视频长期保存 |

## 4. 生产配置清单

### 4.1 Radar API

```bash
RADAR_HOST=0.0.0.0
RADAR_PORT=8780
RADAR_DB_PATH=/data/radar/radar.sqlite3
RADAR_MEDIA_DIR=/data/radar/media
```

启动：

```bash
./tools/run_radar_api.sh
```

健康检查：

```bash
curl http://<radar-api>:8780/api/summary
curl http://<radar-api>:8780/api/production-readiness
```

### 4.2 Radar MCP

千蜂平台 MCP 集成：

```yaml
name: radar
displayName: Radar MCP
type: agent_tool
command: python3
args:
  - /app/tools/radar_mcp_server.py
env:
  RADAR_BASE_URL: http://radar-api:8780
```

AI 员工默认绑定 Radar MCP。

### 4.3 Platform MCP Gateway

Radar 服务环境：

```bash
RADAR_BACKEND_MCP_MODE=platform_gateway
PLATFORM_MCP_GATEWAY_URL=http://platform-mcp-gateway/mcp
PLATFORM_MCP_WORKSPACE_ID=<workspace-id>
PLATFORM_MCP_RUNTIME_TOKEN=<runtime-token>
```

说明：

- `PLATFORM_MCP_RUNTIME_TOKEN` 只能作为服务到平台 Gateway 的运行时凭证。
- 不进入数据库。
- 不进入 run report。
- 不进入 `agent_feedback`。

### 4.4 Backend MCP

X MCP 示例：

```yaml
name: x-mcp
displayName: X MCP
type: backend
endpoint: http://x-mcp:8000/mcp
env:
  X_BEARER_TOKEN: <secret>
  X_AUTH_MODE: bearer
  X_API_TOOL_ALLOWLIST: getUsersByUsername,getUsersPosts,getUsersIdPosts,getPosts,searchPostsRecent,getUsage
```

要求：

- 只读 allowlist。
- token 由千蜂平台 Secret 管理。
- 普通 AI 员工不直接绑定 X MCP。
- Radar 通过 Gateway 调用。

## 5. 生产验收用例

### 5.1 基础健康检查

```bash
curl http://<radar-api>:8780/api/summary
curl http://<radar-api>:8780/api/providers/health
curl http://<radar-api>:8780/api/mcp/integrations
curl http://<radar-api>:8780/api/production-readiness
```

验收标准：

- Radar MCP connected。
- Platform MCP Gateway enabled。
- X MCP connected。
- 不暴露任何 token 明文。

### 5.2 AI 员工自然语言采集

AI 员工输入：

```text
用 Radar 采集 @elonmusk 最近 7 天原创 X 内容，图片和视频保留，默认 auto 通道。
```

预期：

- 调用 `radar_agent_collect`。
- 返回 `task_id`。
- `provider=beeclaw:x`。
- `execution_backend=x_mcp` 或合理 fallback。
- 数据入库到 `source_contents`。
- 媒体写入 `media_assets`。
- 返回 `agent_feedback.message`。

### 5.3 X MCP credits 受控压测

第一步只估算：

```text
radar_xmcp_pressure_test(handles="@OpenAI,@Anthropic", max_accounts=2, max_results=3, execute=false)
```

确认 credits 后执行：

```text
radar_xmcp_pressure_test(handles="@OpenAI,@Anthropic", max_accounts=2, max_results=3, execute=true, queue=true)
```

验收标准：

- 生成 queued batch。
- worker 执行。
- 失败写入 backend_attempts。
- credits 不足时返回明确错误。

### 5.4 大任务队列

创建批量 URL / 账号任务：

```text
radar_create_collection_task(urls="...", platform="web", queue=true)
```

启动 worker：

```bash
python3 -m crawler worker --daemon --limit 0 --poll-interval 5 --idle-limit 0 --retry-delay 60
```

验收标准：

- 父任务和子任务状态正确。
- 成功、失败、保存数聚合正确。
- 手动取消后 queued 子任务停止。
- 失败任务按 maxAttempts 重试。

### 5.5 媒体资产

验收：

```text
radar_list_media_assets
radar_retry_media_assets
radar_export_media_assets(output_format="jsonl")
```

验收标准：

- 媒体状态可查。
- 失败媒体可重试。
- manifest 可导出。

### 5.6 下游整理交接

采集完成后：

```text
radar_handoff_to_organizer(content_ids=[...])
```

验收标准：

- 下游 AI 员工读取已采集数据。
- 不重新触发采集。
- 原文、链接、媒体、raw payload 保留。

## 6. 当前可交付清单

| 模块 | 交付状态 | 说明 |
| --- | --- | --- |
| Radar API | 可交付 | 本地已运行，接口完整 |
| Radar MCP | 可交付 | AI 员工工具入口 |
| Radar Skill | 可交付 | 约束 Agent 正确使用采集能力 |
| Beeclaw Provider Router | 可交付 | provider namespace 和 backend 自动选择 |
| X 采集链路 | 可交付，待生产 credits 验收 | 支持 X MCP / API / RSS / browser fallback |
| URL / RSS / Web / GitHub | 可交付 | Jina Reader、RSS parser、gh、universal_reader 可用 |
| 小红书 / YouTube / Reddit 深度能力 | 可交付基础深度能力，待生产 backend 验收 | 小红书已支持关键词采集；YouTube 已支持关键词视频采集；Reddit 已支持关键词帖子采集；生产仍需 MCP / CLI / API 凭证和限流验收 |
| 任务队列 / Worker | 可交付 | queued、retry、cancel、parent-child batch |
| media_assets | 可交付 | 本地媒体状态、重试、manifest；对象存储待接 |
| agent_feedback | 可交付 | AI 员工可稳定回复用户 |
| 生产就绪检查 | 可交付 | `/api/production-readiness` |

## 7. 仍需外部环境完成的事项

这些不是当前代码内部能单独完成的事项，需要生产平台配合：

1. 千蜂平台接入真实 Platform MCP Gateway。
2. 在 MCP Manager 中注册 X MCP、小红书 MCP 等 backend MCP。
3. 注入 Radar 到 Gateway 的 runtime identity。
4. X Developer credits 可用，并完成小批量生产压测。
5. 小红书、YouTube、Reddit 等平台准备真实 MCP、CLI、API 凭证，并完成小批量生产验收。
6. 媒体对象存储 bucket、权限和 CDN 策略。
7. worker 进程生产托管和监控告警。

## 8. 风险控制

生产默认策略：

- AI 员工只绑定 Radar MCP。
- X MCP、小红书 MCP 作为 backend connector，不直接暴露给普通 AI 员工。
- X 生产默认 `beeclaw:x` + `mode=auto`。
- X MCP/API credits 不足时 fallback 到 `beeclaw:x_rss`，同时提示指标和视频可能不完整。
- 大批量任务必须 queued，由 worker 执行。
- 媒体下载失败不阻断内容入库，进入 `media_assets` 重试队列。
- 所有 provider 失败必须写入 run report 和 `agent_feedback.errors`。

## 9. 最终交付判断

当前项目可以交付为：

```text
千蜂 AI Agent Runtime 的生产级数据采集工具 Radar
```

具备：

- Agent 工具入口。
- 采集任务编排。
- Beeclaw provider 路由。
- 多平台 provider 框架。
- X 生产主链路。
- 原始数据与媒体资产存储。
- 大任务队列和 worker。
- 失败、重试、取消、压测。
- 标准化 `agent_feedback`。
- 生产就绪检查。

生产上线前必须完成的不是重新开发核心链路，而是完成平台接入验收：

```text
Platform MCP Gateway 接入
X MCP credits 小批量压测
对象存储接入
重点平台 backend MCP / API 验收
worker 生产托管
```
