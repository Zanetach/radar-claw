# Beeclaw agent-browser 与真实平台测试

本文说明两个交付点：

1. `agent-browser` 作为 `beeclaw:web` 的可选 backend。
2. 云服务器 headless / cloud browser 配置，以及各平台 URL、账号、关键词三类真实 smoke test。

## 1. agent-browser backend 边界

`agent-browser` 只负责页面渲染后的内容提取，适合普通 HTTP/Jina/UniversalReader 无法稳定读取的页面。它已经进入 Beeclaw URL 自动路由，不需要用户手动指定。

对外仍是 Beeclaw provider：

```json
{
  "platform": "web",
  "provider": "beeclaw:web",
  "backend": "agent-browser",
  "url": "https://example.com/app"
}
```

入库后记录：

```text
provider=beeclaw:web
execution_backend=agent-browser
```

它不会替代 X MCP、小红书 MCP、YouTube API 等平台级 provider。平台有官方 API/MCP 时，仍优先走平台 provider；`agent-browser` 是页面级兜底。

## 2. 本地与云端配置

Radar 支持三种方式调用 `agent-browser`。

### 方案 A：直接命令

适合单机部署，命令必须输出 JSON。

```bash
export BEECLAW_AGENT_BROWSER_CMD='/opt/agent-browser/extract --json {url}'
export BEECLAW_AGENT_BROWSER_TIMEOUT=120
```

返回 JSON 建议结构：

```json
{
  "id": "stable-id",
  "title": "Page title",
  "content": "Rendered page markdown or text",
  "url": "https://example.com/final",
  "images": ["https://example.com/a.png"],
  "videos": ["https://example.com/a.mp4"]
}
```

### 方案 B：云端 browser worker

适合云服务器没有可视化桌面的场景。Radar 调一个浏览器 worker HTTP endpoint，浏览器运行在 worker 内部。

```bash
export BEECLAW_AGENT_BROWSER_ENDPOINT='https://browser-worker.example.com/extract'
export AGENT_BROWSER_MODE=headless
export AGENT_BROWSER_HEADLESS=true
export AGENT_BROWSER_PROVIDER=browserbase
export AGENT_BROWSER_API_KEY='<secret>'
```

请求体：

```json
{
  "url": "https://example.com/app",
  "mode": "headless",
  "headless": true,
  "provider": "browserbase"
}
```

Radar 不保存浏览器平台密钥，密钥来自环境变量或平台 Secret。

## 3. X browser-session 的云端/无头支持

X 账号级采集的 `browser_session` 不再只等于本地 Chrome。Radar 会在
`beeclaw:x` 自动路由末尾使用 browser-session，并按配置选择：

```text
cloud_browser_session -> headless_browser_session -> local_browser_session
```

### 方案 A：Cloud Browser / Browserbase / 自建 Playwright Worker

```bash
export BEECLAW_X_BROWSER_SESSION_MODE=cloud
export BEECLAW_X_BROWSER_ENDPOINT='https://browser-worker.example.com/x/profile-posts'
export BEECLAW_X_BROWSER_API_KEY='<secret>'
export BEECLAW_X_BROWSER_PROVIDER=browserbase
export BEECLAW_X_BROWSER_STORAGE_STATE='/secret/x-storage-state.json'
```

Radar 请求体示例：

```json
{
  "platform": "x",
  "task": "profile_posts",
  "handle": "elonmusk",
  "url": "https://x.com/elonmusk",
  "maxResults": 20,
  "includeMetrics": true,
  "includeMedia": true,
  "mode": "cloud",
  "headless": true,
  "provider": "browserbase",
  "storageState": "/secret/x-storage-state.json"
}
```

### 方案 B：同机 Headless Browser 命令

```bash
export BEECLAW_X_BROWSER_SESSION_MODE=headless
export BEECLAW_X_BROWSER_CMD='/opt/beeclaw/x-browser --json {handle} {max_results}'
export BEECLAW_X_BROWSER_PROFILE_DIR='/srv/beeclaw/x-profile'
```

命令必须输出 JSON：

```json
{
  "items": [
    {
      "id": "2055294612751991090",
      "text": "The goal of the X algorithm is simple...",
      "url": "https://x.com/elonmusk/status/2055294612751991090",
      "published_at": "2026-05-15T14:29:00Z",
      "view_count": 238,
      "like_count": 449,
      "reply_count": 238,
      "retweet_count": 65,
      "media_assets": [
        {"type": "image", "url": "https://pbs.twimg.com/media/example.jpg"}
      ]
    }
  ]
}
```

### 方案 C：本地 WebBridge

```bash
export BEECLAW_X_BROWSER_SESSION_MODE=local
export WEBBRIDGE_URL='http://127.0.0.1:10086'
```

本地模式适合调试；云端生产建议使用方案 A 或 B。三种模式都会在
`agent_feedback.backend_attempts` 和 raw payload 中记录实际
`execution_backend`，分别是 `cloud_browser_session`、
`headless_browser_session` 或 `browser_session`。

## 4. 项目内置兼容 wrapper

`tools/beeclaw-bin/agent-browser` 是开发/测试用 wrapper：

- 优先调用 `BEECLAW_AGENT_BROWSER_EXEC` 或 `AGENT_BROWSER_EXEC`
- 其次调用 `BEECLAW_AGENT_BROWSER_ENDPOINT` 或 `AGENT_BROWSER_ENDPOINT`
- 都没有配置时，降级到 Jina Reader

这个 wrapper 可用于验证 Radar 链路，但生产渲染能力应接真实 headless/cloud browser。

## 3. API 使用

```bash
curl --noproxy '*' -X POST http://127.0.0.1:8780/api/collection-tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "sourceType": "url",
    "platform": "web",
    "url": "https://example.com",
    "backend": "agent-browser"
  }'
```

AI 员工通过 Radar MCP 调用时，默认不需要传 `backend`。Radar 会按平台自动选择可用 backend；只有调试或强制指定时才需要把 `backend=agent-browser` 放到任务 payload 中。

自动顺序：

```text
YouTube URL: yt-dlp -> Jina Reader -> agent-browser -> universal_reader
GitHub URL: gh -> Jina Reader -> agent-browser -> universal_reader
XHS URL: xhs-cli -> Jina Reader -> agent-browser -> universal_reader
Reddit URL: rdt-cli -> Jina Reader -> agent-browser -> universal_reader
RSS/Atom URL: rss_parser -> Jina Reader -> agent-browser -> universal_reader
Other platform URL: Jina Reader -> agent-browser -> universal_reader
```

每次尝试都会写入 `backend_attempts`，最终成功的 backend 会体现在 `execution_backend`。

## 4. 真实平台 smoke test

工具：

```bash
./tools/beeclaw_platform_smoke.py
```

默认是 dry-run，不消耗平台额度：

```bash
./tools/beeclaw_platform_smoke.py --platforms all --types url,account,keyword
```

执行安全 URL 子集：

```bash
./tools/beeclaw_platform_smoke.py --execute \
  --platforms web,rss,github,youtube,reddit \
  --types url \
  --limit 2
```

执行 X 账号和关键词测试：

```bash
./tools/beeclaw_platform_smoke.py --execute \
  --platforms x \
  --types account,keyword \
  --limit 3
```

执行 agent-browser URL 测试：

```bash
./tools/beeclaw_platform_smoke.py --execute \
  --platforms web \
  --types url \
  --backend agent-browser
```

为没有默认样例的平台提供真实输入：

```bash
export BEECLAW_SMOKE_XHS_URL='https://www.xiaohongshu.com/explore/<note-id>'
export BEECLAW_SMOKE_WECHAT_URL='https://mp.weixin.qq.com/s/<article-id>'
export BEECLAW_SMOKE_BILIBILI_URL='https://www.bilibili.com/video/<bv-id>'
export BEECLAW_SMOKE_DOUYIN_URL='https://www.douyin.com/video/<id>'
export BEECLAW_SMOKE_WEIBO_URL='https://weibo.com/<uid>/<post-id>'
export BEECLAW_SMOKE_ZHIHU_URL='https://www.zhihu.com/question/<id>/answer/<id>'
```

带 `--json` 输出完整报告，便于 CI 或 Agent runtime 读取。

## 5. 生产验收口径

验收不看“接口是否返回 200”，要看每个平台每种入口的结果：

- URL：是否保存原文、原始链接、媒体 metadata、raw payload。
- 账号：是否按账号增量获取，是否有去重、失败记录和限速策略。
- 关键词：是否返回相关内容，是否有 provider backend 和失败原因。
- 媒体：图片/视频是否有 `media_assets` 记录，下载失败是否可重试。
- 反馈：`agent_feedback` 是否包含 `saved_count`、`execution_backend`、`backend_attempts` 和下一步建议。

当前脚本会把缺少真实输入的平台标记为 `missing_input`。生产压测前必须补齐对应环境变量或接入平台 MCP/API。
