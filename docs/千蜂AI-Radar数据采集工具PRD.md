# 千蜂 AI · Radar 数据采集工具 PRD

## 定位

Radar 是千蜂 AI Agent Runtime 的标准数据采集工具，基于 Hermes Agent 的 MCP + Skill 机制接入。产品入口是 AI 员工。AI 员工选择 Radar 工具后，可以通过对话创建采集任务、查询状态、读取原始数据、导出原始数据集，并按需把采集结果交给后续整理/分析流程。

feedgrab 使用 `iBigQiang/feedgrab` 作为底层采集内核。所有媒介平台接入、provider 选择、抓取动作和媒体下载由 feedgrab 管理；Radar 负责工具封装、任务管理、数据存储、状态追踪和 Agent 协作契约。

## 角色与能力绑定

- 平台管理员：配置 X MCP、API token、媒体存储和 provider 可用性。
- AI 员工创建者：在千蜂 AI 中选择 Radar 数据采集工具。
- AI 员工：通过 Hermes/Radar tools 执行采集任务，查看任务反馈和原始数据。
- 内容整理能力：读取 Radar 原始数据，做翻译、OCR、摘要、分类和质量判断。

这些不是固定三段式角色。一个 AI 员工可以只绑定 Radar 做采集；也可以同时绑定采集和整理能力；团队也可以把采集、整理、发布拆成不同 AI 员工。Radar v1 的产品边界只承诺数据采集、原始数据沉淀和可交接的数据契约。

## 核心流程

```text
用户
  -> 千蜂 AI 员工
  -> Hermes Skill: radar-data-collection
  -> Radar MCP Tools
  -> Radar 任务/存储
  -> feedgrab provider
  -> 外部平台
  -> Radar 原始数据
  -> 可选：导出 / 整理 / 分析 / 发布
```

典型请求：

```text
抓取 @elonmusk 最近 7 天原创 X post，包含图片和视频
```

执行步骤：

1. AI 员工读取 `radar-data-collection` Skill。
2. 调用 `radar_check_provider_health` 检查 feedgrab / X MCP。
3. 调用 `radar_list_strategies` 选择策略。
4. 优先调用 `radar_agent_collect` 传入用户原始指令，由 Radar 解析意图并创建任务；结构化流程可直接调用 `radar_create_collection_task`。
5. Radar 调用 feedgrab provider 执行采集。
6. Radar 保存原文、原始链接、媒体、指标和 raw payload。
7. Radar 生成 `agent_feedback`，包含可直接回复用户的任务结果、内容 ID、失败原因和下一步工具建议。
8. AI 员工使用 `agent_feedback.message` 返回采集报告。
9. 后续如需整理/分析，再由当前 AI 员工或另一个内容整理员工调用 `radar_handoff_to_organizer`。

定时采集边界：Hermes/千蜂 AI Agent runtime 负责定时唤醒。Radar 不内置 cron，不主动循环执行。用户提出“每天/每小时/定时”时，Radar 返回 `agent_feedback.status=requires_runtime_schedule` 和 `runtime_schedule.execution_payload`；Agent runtime 以此创建调度，到点调用 `radar_create_collection_task`。

## v1 边界

v1 做：

- feedgrab 依赖接入。
- X MCP 作为 feedgrab X provider 的生产默认路径。
- feedgrab URL/content 路由：小红书、微信公众号、YouTube、Bilibili、抖音、微博、知乎、GitHub、飞书、金山文档、有道云笔记、RSS、Telegram、Reddit、HackerNews、Medium、LinuxDo、IDCFlare、小宇宙、喜马拉雅、通用 Web URL。
- collection task / raw content / provider health / optional organizer handoff API。
- 对定时需求返回 Agent runtime 调度契约，不在 Radar 内部执行 cron。
- `crawl_run_contents` 精确记录任务产出内容，避免并发任务用时间窗口误关联。
- 原始数据集导出，支持 JSON、JSONL、Markdown，供同一 AI 员工或其他 Agent 消费。
- Radar MCP collection tools。
- `radar-data-collection` Skill。

v1 不做：

- 不在 Radar 内置 LLM 翻译、摘要、分类。
- 不在 Radar 内置发布链路。
- 不重写 feedgrab 已支持的平台抓取逻辑。
- 不一次性承诺所有平台的账号级/关键词级深度采集；v1 先保证 URL/content 采集闭环，账号/搜索路由按平台逐步增强。
- 不提供独立用户界面；Radar 只提供 HTTP API、MCP tools、Skill 和采集执行能力。
- 不在任何界面展示 token 明文。
- 不绕过平台登录、付费、限流或风控。

## X MCP 规则

生产 provider 优先级：

```text
feedgrab:x_mcp -> xmcp -> api -> chrome-session -> x-rss
```

推荐只读 allowlist：

```bash
X_API_TOOL_ALLOWLIST="getUsersByUsername,getUsersPosts,getUsersIdPosts,getPosts,searchPostsRecent"
```

X MCP 仍消耗 X API credits。Radar/feedgrab 不绕过官方 API 权限。

## MCP Tools

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

## HTTP APIs

- `GET /api/providers`
- `GET /api/providers/health`
- `POST /api/agent/chat`
- `GET /api/collection-strategies`
- `POST /api/collection-tasks`
- `GET /api/collection-tasks`
- `GET /api/collection-tasks/{id}`
- `GET /api/raw-contents`
- `GET /api/raw-contents/{id}`
- `GET /api/raw-contents/export?format=json|jsonl|markdown`
- `POST /api/raw-contents/handoff/organizer`

## Raw Content Contract

```json
{
  "platform": "x",
  "provider": "feedgrab:x_mcp",
  "source_account": "elonmusk",
  "original_content_id": "123",
  "source_url": "https://x.com/elonmusk/status/123",
  "original_text": "...",
  "published_at": "...",
  "metrics": {
    "views": 1000,
    "likes": 100,
    "comments": 10,
    "reposts": 5
  },
  "media_assets": [],
  "raw_payload": {}
}
```

## 内容整理 Agent Handoff Contract

```json
{
  "task_id": "crawl-20260513-100000-abc123",
  "content_ids": [1, 2, 3],
  "handoff_type": "raw_content_for_organization",
  "requirements": {
    "translate_to_zh": true,
    "ocr_images": true,
    "summarize": true,
    "classify": true,
    "quality_score": true
  }
}
```

## Agent Feedback Contract

每个采集任务完成后，Radar 会在 run 结果里返回 `agent_feedback`：

```json
{
  "audience": "ai_employee",
  "run_id": "crawl-20260513-100000-abc123",
  "status": "success",
  "message": "采集完成：保存 3 条，失败 0 个。",
  "content_ids": [1, 2, 3],
  "top_contents": [
    {
      "content_id": 1,
      "title": "Example post",
      "source_url": "https://x.com/example/status/1",
      "provider": "xgo_rss",
      "metrics": {
        "views": 1000,
        "likes": 100,
        "comments": 10,
        "reposts": 5
      },
      "media_count": 1
    }
  ],
  "errors": [],
  "next_actions": [
    {
      "label": "导出原始数据集",
      "tool": "radar_export_raw_dataset"
    },
    {
      "label": "交给 内容整理 Agent 整理",
      "tool": "radar_handoff_to_organizer"
    }
  ],
  "report_markdown": "# Radar 任务反馈\\n..."
}
```

AI 员工只需要读取 `agent_feedback.message` 回复用户；需要继续整理或导出时，使用 `next_actions` 中给出的工具和参数。
