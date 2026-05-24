# Radar 能力审查与能力描述

更新时间：2026-05-24

## 审查结论

Radar 当前已经具备“AI 员工背后的数据采集执行面”能力。它不是独立前台产品，标准入口是 Hermes / 千蜂 AI 员工通过 Radar MCP 发起采集任务，Radar 负责解析、建任务、调用 Beeclaw provider、保存原始数据和媒体元数据，并通过 `agent_feedback` 把可回复给用户的执行结果交还给 AI 员工。

综合评分：8.0 / 10。

- 能力完整度：8.5 / 10。采集、任务、存储、媒体、反馈、导出和下游 handoff 已形成闭环。
- 工程可验证性：8.0 / 10。当前 146 个 unittest 通过；新增 GitHub Actions 后，push / PR 可以自动跑测试。
- 生产可交付性：7.5 / 10。项目侧能力较完整，生产侧仍依赖 Platform MCP Gateway、X credits、平台账号和第三方 backend 的真实验收。
- 可维护性：7.0 / 10。`crawler/web.py` 过大，后续应拆出 API handler、任务运行、页面/响应模板、provider orchestration 等模块。

## 能力描述

### 1. AI 员工采集入口

Radar 的用户入口是 AI 员工，不是 Radar 自己的 UI。核心 MCP 工具包括：

| 能力 | 工具 / 入口 | 描述 |
| --- | --- | --- |
| 自然语言采集 | `radar_agent_collect` | 接收用户原始需求，解析平台、账号、关键词、URL、时间范围、媒体要求，并返回 `agent_feedback`。 |
| 结构化采集 | `radar_create_collection_task` | 用明确字段创建 account / keyword / URL / batch 采集任务。 |
| 任务查询 | `radar_get_collection_task` | 查询任务状态、保存数量、失败原因、backend attempts 和用户可读反馈。 |
| 任务重试 | `radar_retry_collection_task` | 对失败任务进行同步或队列化重试。 |
| 任务状态更新 | `radar_update_task_status` | 支持 paused / cancelled / failed / success 等状态协作。 |
| 策略管理 | `radar_list_strategies`、`radar_create_strategy` | 保存可复用采集策略，供自然语言入口和定时任务复用。 |

### 2. Beeclaw Provider 路由

Radar 对外暴露稳定 provider namespace：

```text
provider = beeclaw:<platform>
execution_backend = 实际执行 backend
```

这样 AI 员工只需要调用 Radar，不需要直接判断底层走 X MCP、API、RSS、CLI、浏览器还是通用阅读器。

当前 provider catalog 覆盖：

```text
X / Twitter、小红书、微信公众号、YouTube、Bilibili、抖音、微博、知乎、
GitHub、飞书、金山文档、有道云笔记、RSS、Telegram、Reddit、
HackerNews、Medium、LinuxDo、IDCFlare、小宇宙、喜马拉雅、通用 Web URL
```

重点 backend 能力：

- X / Twitter：`x_mcp -> x_api -> twitterapi_io -> x_rss -> browser_session` 自动 fallback。
- YouTube：`yt-dlp / youtube_api / rss`。
- GitHub：`gh / github_api / universal_reader`。
- XHS：`xiaohongshu-mcp / xhs-cli / universal_reader`。
- Reddit：`rdt-cli / reddit_api / universal_reader`。
- RSS：内置 RSS / Atom parser，并按 feed entry 入库。
- Web：Jina Reader、agent-browser、UniversalReader fallback。

### 3. Platform MCP Gateway 集成

Radar 已支持平台 MCP 控制面抽象：

```bash
RADAR_BACKEND_MCP_MODE=platform_gateway
PLATFORM_MCP_GATEWAY_URL=<platform gateway url>
PLATFORM_MCP_WORKSPACE_ID=<workspace id>
PLATFORM_MCP_RUNTIME_TOKEN=<runtime token>
```

生产模式下，Radar 通过 Platform MCP Gateway 调用 X MCP、小红书 MCP 等 backend MCP。平台负责 Secret、endpoint、登录态、tool allowlist 和健康检查；Radar 不保存平台 token，只保存采集结果、失败原因和运行报告。

### 4. 原始数据和媒体资产

Radar 已具备原始数据 source-of-truth 能力：

- 保存 `original_text`、原始 URL、platform、provider、execution backend。
- 保存 metrics、raw payload、发布时间、作者信息。
- 保存媒体资产 metadata，支持图片 / 视频下载状态跟踪。
- 支持媒体资产查询、批量重试、manifest 导出。
- 保留原文，翻译和整理结果写入独立字段，避免覆盖原始采集证据。

### 5. 队列、批量任务和 worker

Radar 支持同步执行和队列化执行：

- 大 URL 批量任务会拆成父任务和 queued 子任务。
- 账号源批量采集可按账号拆子任务。
- worker 轮询 queued task 并执行。
- 支持 retry、attempt count、next attempt、cancelled、paused。
- 父任务聚合子任务成功数、失败数、保存数和 report。

生产 worker 示例：

```bash
python3 -m crawler worker --daemon --limit 0 --poll-interval 5 --idle-limit 0 --retry-delay 60
```

### 6. 下游交接能力

Radar 不把内容整理、翻译、OCR、分析和发布塞进采集主边界，但提供下游 handoff 契约：

| 能力 | 工具 / 入口 | 描述 |
| --- | --- | --- |
| 原始内容列表 | `radar_list_raw_contents` | 给 AI 员工或下游 Agent 选择已采集数据。 |
| 原始内容详情 | `radar_get_raw_content_detail` | 读取原文、媒体、metadata、翻译字段和 Markdown preview。 |
| 原始数据导出 | `radar_export_raw_dataset` | 导出 JSON、JSONL 或 Markdown。 |
| 内容整理交接 | `radar_handoff_to_organizer` | 生成翻译、OCR、摘要、分类、质量评分任务输入。 |
| 整理结果回写 | `radar_save_organized_content` | 保存下游 Agent 输出，不覆盖原文。 |
| 黄金互动窗口 | `radar_handoff_to_interaction_agent`、`radar_save_interaction_candidates` | 保存互动评分、回复建议、引用建议和推送状态。 |

### 7. CLI 和安装能力

Radar 同时支持 Agent runtime 的 MCP 调用和命令型 runtime 的 CLI 调用：

- `npx github:Zanetach/radar-claw install`
- `curl -fsSL https://raw.githubusercontent.com/Zanetach/radar-claw/main/install.sh | bash`
- `./tools/install_beeclaw.sh`
- `./tools/beeclaw chat "..."`
- `./tools/beeclaw collect --url ... --json`
- `./tools/package_beeclaw_release.sh`

CLI 和 MCP 都代理同一套 Radar HTTP API，不绕过任务、存储、去重、fallback 和 report 链路。

## 审查发现

### 优势

1. 产品边界清晰：Radar 是采集执行面，AI 员工是用户入口。
2. Provider 抽象正确：`provider` 和 `execution_backend` 分离，便于生产 fallback 和排障。
3. 数据证据链完整：原文、媒体、指标、raw payload、失败原因和 report 都有落点。
4. MCP 工具保持代理模式，没有把 `crawler.web` 内部状态直接塞进 MCP 进程。
5. 测试覆盖面较广：当前本地 `python3 -m unittest discover -s tests -v` 跑通 146 个测试。
6. X 生产链路相对完整：支持 MCP、API、第三方只读 backend、RSS 和 browser session fallback。

### 风险

1. `crawler/web.py` 已经超过 7000 行，是当前最大维护风险。建议拆分为 API 路由、任务执行、HTML/响应模板、导出、media、interaction 等模块。
2. 生产就绪依赖外部环境。Platform MCP Gateway、X credits、小红书 backend、YouTube API/yt-dlp、第三方限流都必须在目标环境验收。
3. 安装文档里使用 `main` 分支 one-liner，适合快速安装，但正式交付建议增加 tag / release 固定版本安装方式。
4. 项目规则明确要求不要新增独立 Radar UI。后续能力扩展应继续通过 AI Agent、MCP、CLI 和下游 Agent contract 完成。
5. 本地 SQLite 适合开发和单机部署；如果进入多租户或高并发生产，需要迁移到受管数据库并补充迁移策略。

## 验证证据

本次审查在当前工作区运行：

```bash
python3 -m unittest discover -s tests -v
```

结果：

```text
unittest: Ran 146 tests, OK
review: tests_count=11, source_count=56, ratio=19.6%
review: ci_workflow_files=0 before this change
review: FILE SIZE HOTSPOTS flagged crawler/web.py because it is 7000+ lines
```

本次提交新增 GitHub Actions 测试工作流后，后续 push / PR 会自动运行：

```bash
python3 -m unittest discover -s tests -v
```

## 下一步建议

1. 把 `crawler/web.py` 拆成小模块，先从 media assets、interaction candidates、export、workspace HTML/response helpers 开始。
2. 给安装方式增加 tag 固定版本示例，例如 `.../v0.1.0/install.sh`。
3. 在真实千蜂环境跑 `GET /api/production-readiness` 和 X MCP pressure test，形成生产验收记录。
4. 把 Platform MCP Gateway、X MCP、小红书 MCP、TwitterAPI.io 的只读 allowlist 固化为平台配置模板。
5. 保持 Radar 的产品入口为 AI Agent，不把本项目演进成独立用户前台。
