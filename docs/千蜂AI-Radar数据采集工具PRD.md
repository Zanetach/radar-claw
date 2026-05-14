# 千蜂 AI · Radar 数据采集工具 PRD

版本：2026-05-14

## 1. 产品定位

Radar 是千蜂 AI Agent Runtime 中的标准数据采集工具。它不是面向普通用户的独立 Web 产品，也不是内容整理/发布系统。用户入口是 AI 员工；AI 员工通过 Hermes MCP tools 调用 Radar，Radar 负责执行采集、保存原始数据、返回结构化结果。

一句话定位：

```text
用户 / AI 员工发起采集需求
-> Radar 创建一次采集任务
-> feedgrab / X provider 执行抓取
-> 原始内容、媒体、指标和 raw payload 入库
-> Radar 返回 agent_feedback
-> 可选交给内容整理 Agent
```

Radar 的核心价值是把“外部平台数据采集”标准化成 AI 员工可调用的工具能力，供千蜂 AI 创建的数据采集类员工复用。

## 2. 当前真实项目状态

当前项目已经从“演示型后台”调整为“Agent 背后的采集工具层”：

- 产品入口：AI Agent / Hermes / 千蜂 AI 员工。
- 用户不直接使用 Radar Web；Radar Web 已移除用户入口，只保留 HTTP API、MCP tools、Skill、文档和测试。
- feedgrab 已作为底层采集内核接入。
- X 平台已有多 provider 路径：`feedgrab:x_mcp`、`feedgrab:x_rss`、API、browser/chrome session fallback。
- 非 X 平台当前优先支持 URL/content 采集闭环。
- 采集结果保存到 SQLite，后续可扩展同步飞书多维表/云盘。
- 内容整理、翻译、OCR、分类、质量判断、发布不属于 Radar v1 内置能力，由内容整理 Agent 或具备整理能力的 AI 员工处理。

## 3. 用户角色

### 3.1 平台管理员

负责配置：

- X MCP Server URL。
- X API token / credits。
- feedgrab 依赖和运行环境。
- 媒体存储路径。
- Hermes MCP server 和 Radar Skill。
- 后续飞书、云盘、对象存储等外部存储。

管理员不参与日常采集操作。

### 3.2 AI 员工创建者

在千蜂 AI 中创建 AI 员工，并为该员工绑定 Radar 数据采集工具。

典型员工：

- 数据采集员工。
- 市场情报员工。
- 竞品监测员工。
- 行业资讯监测员工。

### 3.3 AI 员工 / 数据采集员工

通过对话接收用户需求，并调用 Radar tools：

- 解析采集意图。
- 创建采集任务。
- 查询任务结果。
- 返回采集报告。
- 按需把原始数据交给内容整理 Agent。

### 3.4 内容整理 Agent

读取 Radar 原始数据，负责：

- 翻译。
- OCR。
- 摘要。
- 分类。
- 质量评分。
- 内容清洗。
- 发布建议。

内容整理 Agent 可以是独立员工，也可以是同一个 AI 员工绑定额外整理能力。

## 4. 核心使用流程

### 4.1 单次采集

用户对 AI 员工说：

```text
抓取 @elonmusk 最近 7 天原创 X post，包含图片和视频
```

执行流程：

1. AI 员工读取 `radar-data-collection` Skill。
2. 调用 `radar_check_provider_health` 检查 feedgrab、X MCP、媒体目录等状态。
3. 优先调用 `radar_agent_collect`，传入用户原始指令。
4. Radar 解析平台、账号、URL、时间范围、媒体需求、过滤条件。
5. Radar 创建 collection task / crawl run。
6. Radar 调用对应 provider 执行采集。
7. Radar 保存原文、链接、指标、媒体 asset metadata、raw payload。
8. Radar 返回 `agent_feedback`。
9. AI 员工把 `agent_feedback.message` 回复给用户。
10. 用户需要整理时，AI 员工调用 `radar_handoff_to_organizer`。

### 4.2 URL/content 采集

用户对 AI 员工说：

```text
采集这个 GitHub 项目 https://github.com/iBigQiang/feedgrab
```

Radar 行为：

- 根据 URL 识别平台为 `github`。
- 执行 `feedgrab:github` 路由。
- 底层执行器可能是 `feedgrab:universal_reader`。
- 保存原始内容。
- `agent_feedback.top_contents` 返回：
  - `provider=feedgrab:github`
  - `execution_backend=feedgrab:universal_reader`

### 4.3 定时采集

用户对 AI 员工说：

```text
每天 10 点抓取 @OpenAI 最近 24 小时推文
```

边界：

- Hermes / 千蜂 AI Agent runtime 负责定时调度。
- Radar 不内置 cron。
- Radar 不主动循环执行。
- Radar 只返回调度契约。

Radar 返回：

```json
{
  "agent_feedback": {
    "status": "requires_runtime_schedule",
    "runtime_schedule": {
      "owner": "hermes_agent_runtime",
      "radar_executes_schedule": false,
      "execution_tool": "radar_create_collection_task",
      "execution_payload": {
        "identifier": "OpenAI",
        "platform": "x",
        "date_range": "24h"
      }
    }
  }
}
```

AI Agent runtime 根据 `runtime_schedule` 创建定时任务，到点调用 `radar_create_collection_task`。

## 5. 平台能力范围

### 5.1 当前生产优先级

```text
X -> YouTube -> RSS/Web -> 小红书 -> 微信公众号 -> B站/抖音/微博 -> Reddit/Telegram
```

### 5.2 当前已接入能力

| 平台 | 当前能力 | 说明 |
| --- | --- | --- |
| X / Twitter | 账号采集、RSS fallback、X MCP、API/browser fallback | 生产默认优先 `feedgrab:x_mcp` |
| YouTube | 账号 RSS / URL content | 可无 token 获取基础视频元数据 |
| 小红书 / XHS | URL/content、关键词搜索 | 关键词搜索已走 feedgrab XHS search |
| 微信公众号 / WeChat | URL/content | 账号级深度采集待增强 |
| Bilibili | URL/content | 账号级/关键词级待增强 |
| 抖音 / Douyin | URL/content | 依赖公开 URL 可读性 |
| 微博 / Weibo | URL/content | 无 URL 的关键词/账号请求会要求用户补 URL |
| 知乎 / Zhihu | URL/content | 账号级/关键词级待增强 |
| GitHub | URL/content | 已验证可采集 GitHub repo 页面 |
| 飞书 / Feishu | URL/content | 私有文档需要授权或公开链接 |
| 金山文档 / Kdocs | URL/content | 私有文档需要授权或公开链接 |
| 有道云笔记 / Youdao | URL/content | 私有笔记需要授权或公开链接 |
| RSS | feed URL | RSS/Atom/feed 地址 |
| Telegram | URL/content | 优先公开频道 URL |
| Reddit | URL/content | 账号级/关键词级待增强 |
| HackerNews | URL/content | HN item/page |
| Medium | URL/content | 文章 URL |
| LinuxDo | URL/content | topic/page URL |
| IDCFlare | URL/content | article/page URL |
| 小宇宙 | URL/content | episode/page URL |
| 喜马拉雅 | URL/content | sound/episode URL |
| 通用 Web URL | URL/content | 通用网页读取 |

### 5.3 非 X 平台约束

非 X 平台当前默认是 URL/content 采集。如果用户只提供“账号名”或“关键词”，而该平台尚未接入深度 provider，Radar 不创建失败采集任务，而是返回 `requires_input`，要求补充具体 URL。

示例：

```text
抓取微博上雷军最近 10 条内容
```

Radar 返回：

```json
{
  "status": "requires_input",
  "required_input": "url",
  "message": "weibo 当前只接入 feedgrab URL/content 采集，尚未接入 keyword 深度采集。请提供具体内容链接或主页链接后再采集。"
}
```

## 6. Provider 设计

### 6.1 Provider 路由与执行器

Radar 区分两个概念：

- `provider`：Radar 对外暴露的采集路由，例如 `feedgrab:github`。
- `execution_backend`：feedgrab 内部实际执行器，例如 `feedgrab:universal_reader`。

原因：

- 业务侧需要知道内容来自哪个平台路由。
- 工程侧需要知道实际是哪个 reader 执行，方便排查失败。

示例：

```json
{
  "provider": "feedgrab:github",
  "execution_backend": "feedgrab:universal_reader"
}
```

### 6.2 X provider 优先级

生产优先级：

```text
feedgrab:x_mcp -> xmcp -> api -> chrome-session -> x-rss
```

说明：

- `feedgrab:x_mcp` 是生产默认。
- `feedgrab:x_rss` 是无 token fallback。
- X MCP 仍消耗 X API credits。
- browser/chrome session 仅用于调试或低频验证。

推荐 X MCP allowlist：

```bash
X_API_TOOL_ALLOWLIST="getUsersByUsername,getUsersPosts,getUsersIdPosts,getPosts,searchPostsRecent"
```

## 7. 数据模型与存储

### 7.1 核心表

- `source_accounts`：账号源。
- `source_contents`：原始内容。
- `crawl_runs`：采集任务记录。
- `crawl_run_contents`：任务与内容的精确关联。
- `crawl_failures`：失败记录。
- `crawl_strategies`：采集策略。

### 7.2 原始内容字段

核心字段：

- `platform`
- `provider`
- `original_content_id`
- `title`
- `text`
- `original_text`
- `published_at`
- `url`
- `view_count`
- `like_count`
- `comment_count`
- `share_count`
- `media_type`
- `media_assets_json`
- `raw_payload_json`
- `qualification_status`
- `organize_status`
- `review_status`
- `publish_status`

### 7.3 Raw Content Contract

```json
{
  "content_id": 1,
  "platform": "github",
  "provider": "feedgrab:github",
  "execution_backend": "feedgrab:universal_reader",
  "source_account": "GitHub",
  "original_content_id": "abc123",
  "source_url": "https://github.com/iBigQiang/feedgrab",
  "title": "万能内容抓取器",
  "original_text": "...",
  "published_at": null,
  "metrics": {
    "views": null,
    "likes": null,
    "comments": null,
    "reposts": null
  },
  "media_type": "text",
  "media_assets": [],
  "raw_payload": {}
}
```

## 8. Agent Feedback Contract

每次一次性采集任务完成后，Radar 返回 `agent_feedback`。

```json
{
  "audience": "ai_employee",
  "run_id": "crawl-20260514-113001-dc466e",
  "status": "success",
  "message": "采集完成：保存 1 条，失败 0 个。",
  "summary": {
    "platform": "github",
    "mode": "feedgrab",
    "saved_count": 1,
    "failure_count": 0,
    "providers": ["feedgrab:github"],
    "execution_backends": ["feedgrab:universal_reader"]
  },
  "content_ids": [241],
  "top_contents": [
    {
      "content_id": 241,
      "title": "万能内容抓取器",
      "source_url": "https://github.com/iBigQiang/feedgrab",
      "provider": "feedgrab:github",
      "execution_backend": "feedgrab:universal_reader",
      "metrics": {
        "views": null,
        "likes": null,
        "comments": null,
        "reposts": null
      },
      "media_count": 0
    }
  ],
  "errors": [],
  "next_actions": [
    {
      "label": "导出原始数据集",
      "tool": "radar_export_raw_dataset"
    },
    {
      "label": "交给内容整理 Agent",
      "tool": "radar_handoff_to_organizer"
    }
  ],
  "report_markdown": "# Radar 任务反馈\\n..."
}
```

AI 员工应直接使用 `agent_feedback.message` 回复用户，不自行编造数量、指标或成功状态。

## 9. 内容整理 Agent Handoff Contract

Radar 不负责整理，但提供交接契约：

```json
{
  "task_id": "crawl-20260514-113001-dc466e",
  "content_ids": [241],
  "handoff_type": "raw_content_for_organization",
  "requirements": {
    "translate_to_zh": true,
    "ocr_images": true,
    "summarize": true,
    "classify": true,
    "quality_score": true
  },
  "items": []
}
```

内容整理 Agent 读取原文、媒体、指标和 raw payload，再写回整理结果。

## 10. MCP Tools

当前标准工具：

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

推荐调用方式：

- 自然语言任务：优先 `radar_agent_collect`。
- 已结构化任务：使用 `radar_create_collection_task`。
- 定时任务：先调用 `radar_agent_collect` 获取 `runtime_schedule`，由 Agent runtime 创建调度。
- 整理任务：使用 `radar_handoff_to_organizer`。

## 11. HTTP APIs

当前核心 API：

- `GET /api/providers`
- `GET /api/providers/health`
- `POST /api/agent/chat`
- `GET /api/collection-strategies`
- `POST /api/collection-tasks`
- `GET /api/collection-tasks`
- `GET /api/collection-tasks/{id}`
- `POST /api/runs/{id}/status`
- `GET /api/raw-contents`
- `GET /api/raw-contents/{id}`
- `GET /api/raw-contents/export?format=json|jsonl|markdown`
- `POST /api/raw-contents/handoff/organizer`

## 12. v1 做与不做

### 12.1 v1 已做 / 当前应保持

- Radar 作为 AI 员工背后的采集工具。
- feedgrab 接入。
- 多平台 URL/content 路由。
- X 平台生产优先 provider。
- 小红书关键词搜索。
- 原始内容入库。
- 媒体 asset metadata 保存。
- 任务结果通过 `agent_feedback` 返回。
- 内容整理 Agent handoff。
- 定时任务 runtime 契约。
- Hermes Skill 安装。
- MCP server 代理 Radar HTTP API。
- 单测覆盖核心流程。

### 12.2 v1 不做

- 不提供普通用户直接使用的 Web 工作台。
- 不内置 LLM 翻译/摘要/分类。
- 不内置发布链路。
- 不负责定时调度。
- 不绕过平台登录、付费、限流或风控。
- 不承诺所有平台账号级/关键词级深度采集。
- 不展示 token 明文。

## 13. 验收标准

### 13.1 Agent 闭环

输入：

```text
采集这个 GitHub 项目 https://github.com/iBigQiang/feedgrab
```

期望：

- AI 员工调用 Radar。
- Radar 保存 1 条原始内容。
- 返回 `agent_feedback.message`。
- `top_contents[0].provider = feedgrab:github`。
- `top_contents[0].execution_backend = feedgrab:universal_reader`。

### 13.2 非 X 无 URL 请求

输入：

```text
抓取微博上雷军最近 10 条内容
```

期望：

- 不创建失败 run。
- 返回 `requires_input`。
- 要求用户提供具体 URL。

### 13.3 定时请求

输入：

```text
每天 10 点抓取 @OpenAI 最近 24 小时推文
```

期望：

- 不创建 `scheduled` run。
- 返回 `requires_runtime_schedule`。
- `runtime_schedule.owner = hermes_agent_runtime`。
- `runtime_schedule.execution_tool = radar_create_collection_task`。

### 13.4 X 免费 fallback

输入：

```text
免费抓取 @OpenAI 最近 7 天原创推文
```

期望：

- 使用 `feedgrab:x_rss` 或 X RSS fallback。
- 无需 X API token。
- 保存原始文本和链接。

## 14. 下一阶段 Roadmap

### Phase 1：X 生产化

- 跑通真实 X MCP 生产采集。
- 明确 X API credits 失败处理。
- 增加账号批量采集稳定性。
- 补齐媒体下载失败重试。

### Phase 2：任务队列化

- MCP tool 只创建任务。
- worker 异步执行采集。
- 支持批量 URL / Excel 大任务。
- 支持任务取消、重试、暂停。

### Phase 3：媒体资产表

- 新增 `media_assets` 表。
- 单独记录图片/视频下载状态。
- 支持媒体重试。
- 支持媒体导出和对象存储。

### Phase 4：平台深度 provider

优先级：

```text
YouTube -> RSS/Web -> 小红书 -> 微信公众号 -> B站/抖音/微博 -> Reddit/Telegram
```

目标：

- 支持账号级采集。
- 支持关键词搜索。
- 支持平台特有指标。
- 支持授权态/公开态能力区分。

### Phase 5：内容整理 Agent 对接

- 内容整理 Agent 读取 Radar raw dataset。
- 输出翻译、OCR、摘要、分类、质量评分。
- 回写 Radar 整理字段。
- 支持按分类/质量状态导出。

## 15. 风险与约束

- X MCP 仍消耗 X API credits。
- 非 X 平台公开 URL 可读性取决于 feedgrab 和目标平台页面结构。
- 私有文档类平台需要授权或公开链接。
- 浏览器 session 方式只适合低频调试，不作为默认生产方案。
- SQLite 适合本地 demo 和轻量运行，生产需要评估 Postgres/飞书多维表/对象存储。
- 内容整理和发布属于下游 Agent，不应塞回 Radar v1。
