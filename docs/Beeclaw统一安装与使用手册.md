# Beeclaw Radar 统一安装与使用手册

本文档面向交付、运维和研发。Radar/Beeclaw 是数据采集工具执行层，用户入口是千蜂 AI / Hermes AI 员工；Radar 不作为普通用户界面。

## 1. 交付内容

一个完整交付包应包含：

- `crawler/`：Radar API、任务、provider、入库逻辑。
- `tools/radar_mcp_server.py`：AI 员工调用的 Radar MCP。
- `tools/hermes_skills/`：Hermes / 千蜂 AI 员工使用的采集 Skill。
- `tools/beeclaw`：Agent CLI，本地/脚本入口。
- `tools/install_beeclaw.sh`：统一安装、检查、启动入口。
- `tools/package_beeclaw_release.sh`：生成可交付压缩包。
- `tools/beeclaw-bin/`：项目内置 CLI backend wrappers。
- `.env.example`：运行配置模板，不包含真实密钥。
- `docs/`：PRD、架构、测试、安装文档。

## 2. 一键安装

### 2.1 NPX 安装

如果环境已经有 Node.js / npm，可以直接通过 GitHub npx 安装：

```bash
npx github:Zanetach/radar-claw install
```

该命令会自动完成安装并启动 Radar API 服务。

默认安装目录：

```text
~/.beeclaw-radar
```

检查安装：

```bash
npx github:Zanetach/radar-claw doctor
```

启动 API：

```bash
npx github:Zanetach/radar-claw start-api
```

如果只安装不启动服务：

```bash
npx github:Zanetach/radar-claw install --no-start
```

### 2.2 Curl 一键安装

适合给 AI Agent 的最短安装指令：

```bash
curl -fsSL https://raw.githubusercontent.com/Zanetach/radar-claw/main/install.sh | bash
```

该命令内部调用：

```bash
npx github:Zanetach/radar-claw install
```

所以默认同样会自动安装并启动 Radar API。

指定安装目录：

```bash
npx github:Zanetach/radar-claw install --dir /opt/beeclaw-radar
```

如果后续发布到 npm registry，命令可以缩短为：

```bash
npx beeclaw-radar install
```

### 2.3 本地脚本安装

在项目根目录执行：

```bash
./tools/install_beeclaw.sh
```

默认会执行：

1. 创建或复用 Python 3.11 venv。
2. 安装 `requirements.txt`。
3. 安装 Beeclaw CLI backend wrappers。
4. 安装 Hermes Radar Skill 和 Radar MCP 配置。
5. 自动后台启动 Radar API。
6. 执行本地 doctor 检查。

如果只安装依赖：

```bash
./tools/install_beeclaw.sh install-deps
```

如果只安装 Hermes Skill / MCP：

```bash
./tools/install_beeclaw.sh install-hermes
```

如果只检查环境：

```bash
./tools/install_beeclaw.sh doctor
```

## 3. 启动 Radar API

本地启动：

```bash
./tools/install_beeclaw.sh start-api
```

默认地址：

```text
http://127.0.0.1:8780
```

健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8780/api/summary
curl --noproxy '*' http://127.0.0.1:8780/api/providers/health
```

## 4. AI 员工调用方式

生产推荐链路：

```text
用户
  -> 千蜂 AI / Hermes AI 员工
  -> Radar MCP
  -> Radar collection task
  -> Beeclaw provider 自动路由
  -> 平台 MCP / API / RSS / 浏览器 backend
  -> 原始内容入库
  -> agent_feedback 返回给 AI 员工
```

用户只需要表达目标，例如：

```text
采集 @elonmusk 最近 7 天 X 内容，保留图片和视频
```

AI 员工调用 `radar_agent_collect`，Radar 内部决定走：

```text
x_mcp -> x_api -> twitterapi_io -> x_rss -> cloud/headless/local browser-session
```

## 5. Agent CLI 使用

CLI 走 Radar HTTP API，不直连数据库，不绕过任务状态机。

自然语言采集：

```bash
./tools/beeclaw chat "采集 @OpenAI 最近 7 天 X 内容，保留图片和视频" --json
```

结构化采集：

```bash
./tools/beeclaw collect --platform x --identifier @OpenAI --date-range 7d --limit 20 --json
```

查看任务：

```bash
./tools/beeclaw task list
./tools/beeclaw task get <task_id> --json
```

查看 provider：

```bash
./tools/beeclaw provider list --json
./tools/beeclaw provider health --json
```

## 6. 云浏览器 / 无头浏览器配置

### 6.1 Cloud Browser / Browserbase 类服务

适合生产部署、账号隔离、并发扩展。本地不打开浏览器。

```bash
BEECLAW_X_BROWSER_SESSION_MODE=cloud
BEECLAW_X_BROWSER_ENDPOINT=https://browser-worker.example.com/x/profile-posts
BEECLAW_X_BROWSER_API_KEY=xxx
BEECLAW_X_BROWSER_PROVIDER=browserbase
```

### 6.2 自建 headless worker

适合云服务器无桌面环境。命令必须输出 JSON。

```bash
BEECLAW_X_BROWSER_SESSION_MODE=headless
BEECLAW_X_BROWSER_CMD="/opt/beeclaw/x-browser --json {handle} {max_results}"
BEECLAW_X_BROWSER_PROFILE_DIR=/srv/beeclaw/x-profile
```

### 6.3 本地 WebBridge

适合调试已有本地登录态。

```bash
BEECLAW_X_BROWSER_SESSION_MODE=local
WEBBRIDGE_URL=http://127.0.0.1:10086
```

## 7. 配置模板

复制模板后按环境填写：

```bash
cp .env.example .env
```

不要提交 `.env`。

关键配置：

- `RADAR_BASE_URL`：Radar API 地址。
- `X_BEARER_TOKEN`：X 官方 API token，可选。
- `TWITTERAPI_IO_KEY`：twitterapi.io key，可选。
- `XMCP_SERVER_URL`：X MCP 地址，可选。
- `RADAR_BACKEND_MCP_MODE=platform_gateway`：走千蜂平台 MCP Gateway 时启用。
- `BEECLAW_X_BROWSER_*`：云浏览器或无头浏览器配置。

## 8. 生成交付包

生成压缩包：

```bash
./tools/package_beeclaw_release.sh
```

输出：

```text
dist/beeclaw-radar-YYYYmmdd-HHMMSS.tar.gz
```

压缩包不包含：

- `.env`
- `tools/xmcp/.env`
- `.git/`
- `data/`
- `feishu_workspace/`
- `reports/`
- `output/`
- 浏览器 profile 和缓存

## 9. 验收命令

本地验收：

```bash
./tools/install_beeclaw.sh doctor
/Users/zane/.radar-venv/bin/python -m unittest discover -s tests -v
./tools/beeclaw provider health --json
```

Hermes 中验收：

```text
/reload-mcp
```

然后向数据采集 AI 员工输入：

```text
用 Radar 采集 @elonmusk 最近 7 天 X 内容，图片和视频也保留
```

期望返回：

- 任务 ID。
- 保存条数。
- 媒体数量。
- 实际 backend。
- 失败 backend 和 fallback 原因。
- 可交给内容整理 Agent 的 content IDs。

## 10. 生产边界

Radar/Beeclaw 只负责采集、标准化、存储、媒体索引和结构化反馈。

以下能力不内置在 Radar v1：

- 翻译。
- OCR。
- 摘要。
- 分类。
- 质量判断。
- 发布。

这些能力由同一个 AI 员工的整理能力，或单独的内容整理 / 发布 AI 员工处理。
