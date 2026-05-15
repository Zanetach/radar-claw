# Radar 当前能力状态与数据采集流程

更新时间：2026-05-15

## 1. 当前定位

Radar 当前不是面向普通用户独立使用的前台产品，而是千蜂 AI / Hermes Agent Runtime 里的“数据采集工具执行面”。

标准入口是：

```text
用户 -> AI 员工 -> Radar MCP -> Radar API / Task Runtime -> Beeclaw Provider -> 外部平台
```

Radar v1 的边界是数据采集闭环：

- 解析 AI 员工下发的采集任务。
- 创建 collection task。
- 调用 Beeclaw provider 执行抓取。
- 保存原始正文、原始链接、指标、媒体元数据、raw payload、失败原因和运行报告。
- 返回 `agent_feedback`，让 AI 员工把结果反馈给用户。

内容整理、翻译、OCR、分类、质量判断、发布不属于 Radar v1 内置能力。它们可以由同一个 AI 员工继续处理，也可以由另一个内容整理型 AI 员工读取 Radar 已采集的数据后处理。

## 2. 当前能力状态

### 2.1 Agent 工具入口

Radar 已通过 MCP 暴露给 AI 员工使用，核心工具包括：

- `radar_agent_collect`：自然语言采集入口。
- `radar_create_collection_task`：结构化创建采集任务。
- `radar_get_collection_task`：查询任务状态。
- `radar_list_raw_contents`：查询已采集原始内容。
- `radar_get_raw_content_detail`：读取单条原始内容详情。
- `radar_list_media_assets`：查询媒体资产。
- `radar_export_raw_dataset`：导出原始数据集。
- `radar_check_provider_health`：检查 provider / MCP / backend 状态。

MCP 工具保持代理模式：`tools/radar_mcp_server.py` 调用 Radar HTTP API，不直接导入 `crawler.web` 内部状态。

### 2.2 Platform MCP Manager / Gateway

当前架构已经把平台 MCP 管理能力抽象出来，不再写死成某个具体的 `qianfeng-mcp-manager`。

生产架构中：

- 千蜂平台 MCP Manager 负责 MCP 的接入、部署、Secret、登录态、tool allowlist、健康检查。
- Radar 只通过 Platform MCP Gateway 调用已授权的 backend MCP。
- Radar 不保存 X、小红书等平台 token。
- AI 员工默认调用 Radar MCP，不直接串联多个平台 MCP。

本地状态快照：

- `Radar MCP`：connected。
- `X MCP`：本地直连可达，endpoint 为 `http://127.0.0.1:8000/mcp`。
- `Platform MCP Gateway`：本地未启用，因为没有注入 `PLATFORM_MCP_GATEWAY_URL / MCP_GATEWAY_URL` 等网关变量。
- `小红书 MCP`：本地未启动，当前 health 为 unavailable。

### 2.3 Beeclaw Provider Engine

Radar 对外使用 Beeclaw provider 命名，底层可以复用 upstream `feedgrab`、MCP、CLI、API、RSS、浏览器 session 等 backend。

核心设计是：

```text
provider = beeclaw:<platform>
execution_backend = 实际执行 backend
```

例如：

```text
provider=beeclaw:x
execution_backend=x_mcp / x_api / x_rss / browser_session
```

这样 AI 员工只需要说“采集 X 上 @elonmusk 最近 7 天内容”，不需要关心底层到底走 X MCP、X API 还是 RSS fallback。

### 2.4 当前平台能力

当前已形成统一 provider catalog，重点平台能力如下。

| 平台 | 对外 provider | 当前 backend 设计 | 当前状态 |
| --- | --- | --- | --- |
| X / Twitter | `beeclaw:x` | `x_mcp`、`x_api`、`x_rss`、`browser_session`、可选 `twitter-cli` | 已可跑通本地采集；X MCP 可达；真实生产受 X API credits / 权限影响 |
| 小红书 / XHS | `beeclaw:xhs` | `xiaohongshu-mcp`、`xhs-cli`、`universal_reader` | provider 入口已设计；本地 MCP 未启动；深度生产能力待接入 |
| YouTube | `beeclaw:youtube` | `yt-dlp`、`youtube_api`、`rss` | provider 框架已纳入；本地 `yt-dlp` 未安装 |
| RSS | `beeclaw:rss` | 内置 RSS parser | 可用 |
| Web URL | `beeclaw:web` | Jina Reader、universal_reader | 可用 |
| GitHub | `beeclaw:github` | `gh`、GitHub API、universal_reader | 本地 `gh` 可用 |
| Reddit | `beeclaw:reddit` | `rdt-cli`、Reddit API、universal_reader | provider 框架已纳入；本地 `rdt-cli` 未安装 |
| 其他内容平台 | `beeclaw:<platform>` | feedgrab / MCP / CLI / universal_reader | 统一框架已纳入，深度账号级能力按平台逐步补齐 |

扩展清单已覆盖：

```text
X / Twitter、小红书、微信公众号、YouTube、Bilibili、抖音、微博、知乎、
GitHub、飞书、金山文档、有道云笔记、RSS、Telegram、Reddit、
HackerNews、Medium、LinuxDo、IDCFlare、小宇宙、喜马拉雅、通用 Web URL
```

需要区分两类状态：

- “平台已纳入 Beeclaw provider 框架”：可以被统一配置、路由、健康检查、fallback。
- “平台已完成生产级深度采集”：需要具体 backend、凭证、限额、反风控策略、媒体下载、失败重试全部跑通。

目前 X 是最完整的主链路；RSS / Web / GitHub 是可用基础链路；小红书、YouTube、Reddit 等处于 provider 框架已接入、生产深度能力继续补齐阶段。

### 2.5 数据与任务能力

当前 Radar 已具备：

- collection task 创建、查询、重试、取消。
- queued task worker 执行框架。
- account / keyword / URL / batch 输入模型。
- provider 健康检查与 fallback 记录。
- 原始内容入库。
- 媒体资产 metadata 保存。
- 运行报告和失败原因记录。
- 原始数据导出。
- handoff 给下游内容整理 AI 员工的契约。

本地数据库快照显示：

- 账号源：234 个。
- 原始内容：149 条。
- 失败记录：110 条。
- 最新任务状态：success。

这些数字只代表当前本机开发库，不代表生产环境容量。

## 3. 技术架构逻辑

### 3.1 分层架构

```text
千蜂 AI / Hermes Agent Runtime
  |
  | AI 员工调用
  v
Radar MCP
  |
  | HTTP API proxy
  v
Radar API / Task Runtime
  |
  | 创建任务、检查状态、路由 provider
  v
Beeclaw Provider Router
  |
  +-- Platform MCP Gateway
  |     +-- X MCP
  |     +-- 小红书 MCP
  |     +-- 未来平台 MCP
  |
  +-- Local / Direct Backends
        +-- X API
        +-- x-rss
        +-- browser-session
        +-- RSS parser
        +-- Jina Reader
        +-- gh / CLI tools
        +-- upstream feedgrab backend
```

### 3.2 关键技术原则

- AI 员工是用户入口，Radar 不是普通用户入口。
- Radar MCP 是业务工具，X MCP / 小红书 MCP 是后端平台连接器。
- 平台 MCP Manager 统一管理 Secret、endpoint、allowlist 和健康检查。
- Radar 只通过 Gateway 调用已授权 MCP，不保存平台 token。
- Beeclaw provider 负责屏蔽 backend 差异。
- 入库数据必须保留原始内容和原始链接。
- provider 失败必须显式记录，不能静默吞掉。
- 下游整理 AI 员工只读取 Radar 已采集数据，不重新触发采集。

## 4. 用户视角的数据采集流程

### 4.1 单次自然语言采集

用户对 AI 员工说：

```text
帮我采集 X 上 @elonmusk 最近 7 天原创内容，保留图片和视频。
```

实际链路：

1. AI 员工识别这是数据采集任务。
2. AI 员工根据 Radar Skill 调用 `radar_agent_collect`。
3. Radar 解析平台、账号、时间范围、过滤规则、媒体需求。
4. Radar 创建 collection task，并返回 `task_id`。
5. Radar 做 provider health 检查。
6. Beeclaw Router 选择执行 backend，例如优先 `x_mcp`，不可用时降级到 `x_api / x_rss / browser_session`。
7. backend 抓取外部平台内容。
8. Radar 标准化结果，生成统一 raw content。
9. Radar 去重、过滤、保存正文、链接、指标、媒体 metadata、raw payload。
10. Radar 记录失败原因和 backend attempts。
11. Radar 生成 `agent_feedback`。
12. AI 员工把结果回复给用户，例如：保存了多少条、用了哪个 backend、哪些内容 ID、媒体数量、是否有 warning。

### 4.2 关键词采集

用户说：

```text
帮我采集 X 上最近 24 小时关于 AI agent 的高互动帖子。
```

Radar 会把任务解析为：

- `platform=x`
- `source_type=keyword`
- `query=AI agent`
- `date_range=24h`
- `provider=beeclaw:x`
- `mode=auto`

后续流程与账号采集一致，只是 backend 调用变成 search / recent search 类工具。

### 4.3 批量采集

用户可以通过 AI 员工上传 Excel 或给出 URL / 账号列表。

流程是：

1. AI 员工读取附件或列表。
2. 解析平台、账号、关键词、分类、采集策略。
3. 调用 Radar 创建批量 collection task。
4. worker 拆分为多个子任务。
5. 每个子任务独立执行 provider、保存数据、记录失败。
6. 最终返回批量任务报告。

### 4.4 采集后的下游处理

采集完成后，内容整理 AI 员工可以通过 Radar MCP：

- 查询本轮采集的 raw contents。
- 按账号、平台、时间、媒体、互动指标筛选。
- 读取单条内容详情。
- 做翻译、OCR、摘要、分类、质量判断。
- 将整理结果回写或导出到指定系统。

这个阶段不属于 Radar 的采集主链路，但 Radar 是共享数据源。

## 5. 流程图

本项目需要区分两类图，不要混在一起：

- 用户视角图：说明用户如何通过 AI 员工发起任务，数据如何从采集、沉淀、分析到展示。
- 技术视角图：说明 AI 员工、Radar MCP、Radar API、Beeclaw provider、Platform MCP Manager、backend MCP、数据库之间如何调用。

### 5.1 用户视角数据流

源文件：

```text
docs/radar-user-data-flow.svg
```

渲染图片：

```text
docs/radar-user-data-flow.png
```

### 5.2 技术视角调用架构

源文件：

```text
docs/radar-technical-architecture-flow.svg
```

渲染图片：

```text
docs/radar-technical-architecture-flow.png
```

## 6. 当前缺口

要达到大规模生产采集，还需要继续完成：

1. Platform MCP Gateway 在千蜂平台真实接入，并把 X MCP、小红书 MCP 等 backend MCP 统一走网关调用。
2. X MCP 真实生产压测，包括 credits、rate limit、批量账号、失败重试、媒体下载稳定性。
3. 小红书、YouTube、Reddit 等平台的深度 provider 能力补齐。
4. 大任务队列化和 worker 长任务调度，包括暂停、取消、重试、限速、并发控制。
5. media_assets 表的生产化，包括下载状态、重试、对象存储、导出 manifest。
6. Agent feedback 标准化，让 AI 员工能稳定根据结果做下一步判断。

当前项目已新增生产就绪检查入口，用于把上述 6 项拆成可执行状态：

```text
GET /api/production-readiness
MCP tool: radar_check_production_readiness
```

该检查会区分：

- 项目侧已经实现的能力。
- 仍依赖千蜂平台、X credits、对象存储或具体平台账号的外部验收项。
- 每一项的 evidence 和 nextActions，方便 AI 员工或运维按顺序推进。

## 7. 当前结论

当前项目已经具备“AI 员工下发任务 -> Radar 创建采集任务 -> Beeclaw provider 执行抓取 -> 原始数据入库 -> 结果回传给 AI 员工”的闭环。

当前最强可用链路是：

```text
AI 员工 -> Radar MCP -> Radar API -> beeclaw:x -> X MCP / X API / x-rss / browser-session -> source_contents / media_assets -> agent_feedback
```

下一阶段重点不是重新做 UI，而是把生产 backend MCP 接入 Platform MCP Manager，并对 X、小红书、YouTube 等重点平台做真实采集压测和失败恢复。
