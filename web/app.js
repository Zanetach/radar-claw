const state = {
  accounts: [],
  contents: [],
  media: [],
  failures: [],
  runs: [],
  selectedAccounts: new Set(),
  selectedRawContents: new Set(),
  selectedOrganizedContents: new Set(),
  selectedPublishableContents: new Set(),
  activeAgent: "crawler",
  organized: [],
  publishable: [],
  strategies: [],
  diagnostics: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok || body.error) {
    throw new Error(body.error || `HTTP ${response.status}`);
  }
  return body;
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  return value;
}

function fmtNum(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return number.toLocaleString("zh-CN");
}

function shortDate(value) {
  if (!value) return "-";
  return String(value).replace("T", " ").replace("+00:00", "");
}

function pill(label, kind = "") {
  return `<span class="pill ${kind}">${esc(label)}</span>`;
}

function statusPill(status) {
  const map = {
    success: ["完成", "ok"],
    partial_success: ["部分成功", "warn"],
    failed: ["失败", "danger"],
    running: ["运行中", "active"],
    scheduled: ["已定时", "active"],
    qualified: ["达标", "ok"],
    metrics_pending: ["指标待补", "warn"],
    below_threshold: ["未达标", "danger"],
  };
  const [label, kind] = map[status] || [status || "-", ""];
  return pill(label, kind);
}

function parseMediaAssets(item) {
  if (Array.isArray(item.media_assets)) return item.media_assets;
  if (!item.media_assets_json) return [];
  try {
    const parsed = JSON.parse(item.media_assets_json);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function formPayload(form, sourceType) {
  const data = new FormData(form);
  const bools = [
    "includeOriginal",
    "includeQuotes",
    "includeReplies",
    "includeRetweets",
    "downloadImages",
    "downloadVideos",
    "mediaOnly",
    "translateAfterCrawl",
    "ocrImages",
  ];
  const payload = {
    sourceType,
    platform: data.get("platform") || "",
    mode: data.get("mode") || "xmcp",
    identifier: data.get("identifier") || "",
    accountName: data.get("accountName") || "",
    category: data.get("category") || "",
    dateRange: data.get("dateRange") || "7d",
    language: data.get("language") || "all",
    limit: Number(data.get("limit") || 0) || undefined,
    maxResults: Number(data.get("maxResults") || 20),
    minViews: Number(data.get("minViews") || 0) || undefined,
  };
  bools.forEach((key) => {
    payload[key] = data.get(key) === "on";
  });
  payload.downloadMedia = payload.downloadImages || payload.downloadVideos;
  return payload;
}

function appendChat(role, title, html) {
  const node = document.createElement("div");
  node.className = `chat-message ${role}`;
  node.innerHTML = `<strong>${esc(title)}</strong><div>${html}</div>`;
  $("#chatLog").appendChild(node);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
}

function activeRuleCount() {
  return $$(".rule-chip.active").length;
}

function updateActiveRuleCount() {
  const node = $("#activeRuleCount");
  if (node) node.textContent = String(activeRuleCount());
}

function activeRulesText() {
  return $$(".rule-chip.active")
    .map((button) => button.dataset.ruleText)
    .filter(Boolean)
    .join("，");
}

function uploadSummaryHtml(result) {
  if (result.type === "xlsx") {
    const platforms = Object.entries(result.platforms || {})
      .map(([key, value]) => `${key} ${value}`)
      .join(" · ");
    return `
      <p>${esc(result.message)}</p>
      <div class="task-summary">
        ${pill(`账号 ${result.accounts}`)}
        ${pill(`导入 ${result.imported}`, "ok")}
        ${pill(`问题 ${result.qualityIssues}`, result.qualityIssues ? "warn" : "ok")}
        ${platforms ? pill(platforms) : ""}
      </div>
    `;
  }
  if (["txt", "md", "csv"].includes(result.type)) {
    return `
      <p>${esc(result.message)}</p>
      <pre class="upload-preview">${esc(result.preview || "")}</pre>
      <div class="task-summary">${pill(`账号线索 ${result.handles?.length || 0}`)}</div>
    `;
  }
  return `<p>${esc(result.message || "附件已上传。")}</p>`;
}

const agentCopy = {
  crawler: {
    name: "小艾 · 数据采集",
    title: "我们要在 Radar 中采集什么？",
    subtitle: "选择规则后直接描述目标账号、文件或定时要求，Agent 会生成员工任务。",
    placeholder: "可输入：抓取 @OpenAI 的 X 平台数据；或 上传 Excel 后按账号源采集；或 每天上午 10 点定时抓取",
    context: "radar",
    ruleLabel: "采集规则",
    helpTitle: "小艾 · 数据采集",
    helpText: "告诉我要抓取什么。例如：抓取 @OpenAI 最近 7 天原创推文，下载图片和视频，不要转发，英文内容翻译成中文。",
    submitText: "发布员工任务",
    pendingText: "正在解析并发布员工任务...",
    suggestions: [
      ["抓取 @OpenAI 最近 7 天原创内容", "抓取 @OpenAI 最近7天原创推文，下载图片和视频，不要转发，需要翻译和图片OCR"],
      ["用 Chrome 登录态采集", "使用 chrome-session 抓取 @elonmusk 最近7天原创推文，下载图片和视频，不要转发"],
      ["创建每天 10 点的定时采集", "每天上午10点抓取 @AnthropicAI 最近7天原创推文，下载图片和视频，不要转发，需要翻译"],
      ["导入 Excel 并生成批量任务", "导入客户 Excel，解析里面的账号，按 X 平台批量采集最近7天内容，只保留原创和带媒体内容"],
      ["跑 AI 情报源免费采集", "抓取 AI情报源 中的账号，使用 x-rss 免费模式，保留图片，进入待审核队列"],
    ],
  },
  organizer: {
    name: "小蜂 · 内容整理",
    title: "要整理哪些采集结果？",
    subtitle: "从已采集的原始数据里筛选内容，整理 Agent 只做质量建议、翻译、OCR、摘要、分类和归档，不重新采集。",
    placeholder: "可输入：从原始数据里筛选最近 20 条，给质量评分，翻译中文，图片 OCR，按 AI/商业/科技分类，整理后归档",
    context: "整理上下文",
    ruleLabel: "整理规则",
    helpTitle: "小蜂 · 内容整理",
    helpText: "告诉我要整理哪批已采集数据。例如：整理最近采集的 20 条原始内容，给质量建议，翻译中文，图片 OCR，整理后进入归档。",
    submitText: "发布整理任务",
    pendingText: "正在读取原始数据并生成整理任务...",
    suggestions: [
      ["整理最近 20 条原始数据", "整理最近采集的20条原始数据，给质量评分和发布建议，翻译中文，图片OCR"],
      ["只整理带媒体内容", "从原始数据中筛选带图片或视频的内容，下载媒体，翻译中文，并整理归档"],
      ["按分类生成整理稿", "把已采集内容按 AI、商业、科技分类，生成中文摘要和发布建议"],
      ["查看低质量内容原因", "检查待整理内容，列出不建议发布的原因和风险点"],
    ],
  },
  publisher: {
    name: "小智 · 内容发布",
    title: "要把整理稿发布到哪里？",
    subtitle: "只从整理归档后的内容里选择发布对象，发布 Agent 生成发布 payload 并回写发布状态。",
    placeholder: "可输入：把待发布的 AI 分类内容发布到雷达号 APP，目标渠道是小红书也可以",
    context: "发布上下文",
    ruleLabel: "发布规则",
    helpTitle: "小智 · 内容发布",
    helpText: "告诉我要发布哪批归档内容和目标渠道。例如：发布整理库里 AI 分类的 5 条内容到雷达号 APP，失败项保留重试。",
    submitText: "发布内容",
    pendingText: "正在读取整理库并生成发布任务...",
    suggestions: [
      ["发布 AI 分类到雷达号", "把整理库中 AI 分类且审核通过的内容发布到雷达号 APP"],
      ["发布到小红书草稿", "选择整理归档中的商业内容，生成小红书发布草稿"],
      ["只发布已审批内容", "只发布整理库里审核通过、发布状态为待发布的内容"],
      ["生成发布预览", "读取待发布内容，先生成 payload 预览，不真实发布"],
    ],
  },
};

function setActiveAgent(agent) {
  state.activeAgent = agent;
  $$(".agent-tab").forEach((button) => button.classList.toggle("active", button.dataset.agent === agent));
  const copy = agentCopy[agent] || agentCopy.crawler;
  $("#agentHeroTitle").textContent = copy.title;
  $("#agentHeroSubtitle").textContent = copy.subtitle;
  $("#agentChatForm textarea").placeholder = copy.placeholder;
  $("#attachmentStatus").textContent = copy.context;
  $("#ruleReviewLabel").innerHTML = `已启用 <strong id="activeRuleCount">${activeRuleCount()}</strong> 条${copy.ruleLabel}`;
  $("#agentHelpTitle").textContent = copy.helpTitle;
  $("#agentHelpText").textContent = copy.helpText;
  $("#agentSubmitBtn").textContent = copy.submitText;
  $("#agentSubmitBtn").setAttribute("aria-label", copy.submitText);
  $("#promptSuggestions").innerHTML = copy.suggestions
    .map(([label, prompt]) => `<button type="button" data-prompt="${esc(prompt)}">${esc(label)}</button>`)
    .join("");
}

function showToast(text) {
  const toast = $("#toast");
  toast.textContent = text;
  toast.hidden = false;
  setTimeout(() => {
    toast.hidden = true;
  }, 2600);
}

function switchView(view) {
  $$(".nav").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".panel").forEach((item) => item.classList.toggle("active", item.id === `${view}View`));
}

function renderSetupChecklist(data) {
  state.diagnostics = data;
  const checks = [
    ["Hermes 已安装", data.hermes?.installed, "本机 Hermes 环境"],
    ["Radar MCP 已挂载", data.hermes?.radarMcpConfigured, "hermes mcp test radar"],
    ["Radar Skill 已启用", data.hermes?.skillInstalled, "radar-data-collection"],
    ["feedgrab 已安装", data.feedgrab?.feedgrab?.installed, data.feedgrab?.feedgrab?.version || "pip install feedgrab[mcp]"],
    ["X MCP 可连接", data.xmcp?.reachable, data.xmcp?.message || ""],
    ["X Token 已配置", data.tokens?.xBearerToken && data.tokens?.xApiKey && data.tokens?.xApiSecret, "Bearer / API Key / Secret"],
    ["媒体目录可写", data.media?.writable, data.media?.path || ""],
    ["飞书镜像可写", data.feishu?.writable, data.feishu?.path || ""],
  ];
  const passed = checks.filter(([, ok]) => ok).length;
  const score = `${passed}/${checks.length}`;
  const scoreNode = $("#readinessScore");
  if (scoreNode) {
    scoreNode.textContent = score;
    scoreNode.className = passed === checks.length ? "ok" : passed >= 5 ? "warn" : "danger";
  }
  const list = $("#setupChecklist");
  if (!list) return;
  list.innerHTML = checks
    .map(([label, ok, note]) => `
      <div class="setup-item ${ok ? "ok" : "warn"}">
        <span>${ok ? "已就绪" : "待处理"}</span>
        <div>
          <strong>${esc(label)}</strong>
          <p>${esc(note || "")}</p>
        </div>
      </div>
    `)
    .join("");
}

function renderStatusBar(summary, config) {
  const latestRun = summary.latestRun;
  const xToken = config.tokens?.x;
  const chromeSession = config.chromeSession || config.webbridge || {};
  const feedgrabReady = config.feedgrab?.feedgrab?.installed;
  const webbridge = chromeSession.reachable;
  const runLabel = latestRun ? `${latestRun.status} · ${latestRun.saved_count} 条` : "暂无任务";
  $("#statusBar").innerHTML = `
    ${pill(`feedgrab ${feedgrabReady ? "已安装" : "未安装"}`, feedgrabReady ? "ok" : "warn")}
    ${pill(`X Token ${xToken ? "已配置" : "未配置"}`, xToken ? "ok" : "warn")}
    ${pill(`Chrome Session ${webbridge ? "可用" : "不可用"}`, webbridge ? "ok" : "warn")}
    ${pill("飞书 本地镜像", "active")}
    ${pill(`当前任务 ${runLabel}`, latestRun?.status === "failed" ? "danger" : "active")}
  `;
}

function renderConversationReport(summary, config) {
  const latestRun = summary.latestRun || {};
  const latestSaved = Number(latestRun.saved_count ?? 0) || 0;
  const contentCount = latestSaved > 0 ? latestSaved : Number(summary.contents ?? 0) || 0;
  const highInteractionCount = Math.max(0, Number(latestRun.success_count ?? 0) || Math.min(12, Math.ceil(contentCount * 0.12)));
  const topicCount = Math.min(5, Math.max(1, Math.ceil(contentCount / 18))) || 0;
  const status = latestRun.status || "ready";
  const statusLabel = {
    running: "任务进行中",
    scheduled: "任务已定时",
    success: "采集已完成",
    partial_success: "部分完成",
    failed: "等待新任务",
    ready: "准备就绪",
  }[status] || "准备就绪";
  const reportContentCount = $("#reportContentCount");
  const reportInteractionCount = $("#reportInteractionCount");
  const reportTopicCount = $("#reportTopicCount");
  const statusText = $("#conversationStatusText");
  if (reportContentCount) reportContentCount.textContent = fmtNum(contentCount);
  if (reportInteractionCount) reportInteractionCount.textContent = fmtNum(highInteractionCount);
  if (reportTopicCount) reportTopicCount.textContent = fmtNum(topicCount);
  if (statusText) statusText.textContent = statusLabel;

  const topics = [
    "# AI工具推荐",
    "# AI绘图",
    "# 生产力提升",
    "# 效率神器",
    "# AI写作神器",
  ];
  const topicList = $("#reportTopicList");
  if (topicList) {
    topicList.innerHTML = topics.slice(0, Math.max(3, topicCount || 5)).map((topic) => `<span>${esc(topic)}</span>`).join("");
  }

  const stepState = status === "failed" ? "warn" : status === "running" ? "active" : "done";
  const steps = [
    ["平台识别", "done"],
    ["采集执行", status === "ready" ? "active" : stepState],
    ["内容去重", contentCount ? "done" : "active"],
    ["媒体保存", latestRun.media_downloaded ? "done" : contentCount ? "active" : ""],
    ["报告生成", contentCount ? "done" : ""],
  ];
  const progress = $("#reportProgressSteps");
  if (progress) {
    if (progress.classList.contains("task-flow")) {
      const compactSteps = [
        ["平台识别", "已完成", "done"],
        ["采集执行", status === "ready" ? "待开始" : statusLabel, status === "failed" ? "" : "active"],
        ["报告生成", contentCount ? "已完成" : "待开始", contentCount ? "done" : ""],
      ];
      progress.innerHTML = compactSteps
        .map(([label, note, kind]) => `<div class="task-flow-step ${kind}"><span></span><strong>${esc(label)}</strong><small>${esc(note)}</small></div>`)
        .join("");
    } else {
      progress.innerHTML = steps
        .map(([label, kind]) => `<div class="pipeline-step ${kind}"><span></span><strong>${esc(label)}</strong></div>`)
        .join("");
    }
  }

  const dot = $("#conversationStatusDot");
  if (dot) {
    dot.style.background = status === "failed" ? "#f79009" : status === "running" ? "#31c48d" : "#31c48d";
  }
}

async function loadSummaryAndConfig() {
  const [summary, config] = await Promise.all([api("/api/summary"), api("/api/config")]);
  const metrics = [
    ["账号源", summary.accounts],
    ["启用账号", summary.enabledAccounts],
    ["采集内容", summary.contents],
    ["指标待补", summary.pendingContents],
    ["异常记录", summary.failures],
    ["最近任务", summary.latestRun ? summary.latestRun.status : "无"],
  ];
  $("#summaryGrid").innerHTML = metrics
    .map(([label, value]) => `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${esc(fmtNum(value))}</div></div>`)
    .join("");
  renderStatusBar(summary, config);
  renderConversationReport(summary, config);
  renderTokenGrid(config);
}

function accountQuery() {
  const params = new URLSearchParams();
  const platform = $("#accountPlatformFilter").value;
  const status = $("#accountStatusFilter").value;
  const search = $("#accountSearch").value.trim();
  if (platform) params.set("platform", platform);
  if (status) params.set("status", status);
  if (search) params.set("search", search);
  params.set("limit", "300");
  return params.toString();
}

async function loadAccounts() {
  const data = await api(`/api/accounts?${accountQuery()}`);
  state.accounts = data.items;
  renderAccounts();
}

function renderAccounts() {
  $("#accountsTable").innerHTML = state.accounts
    .map((item) => {
      const checked = state.selectedAccounts.has(String(item.id)) ? "checked" : "";
      const issue = item.data_quality_issue ? pill(item.data_quality_issue, "warn") : "";
      const lastStatus = item.last_success_at
        ? pill(`成功 ${shortDate(item.last_success_at)}`, "ok")
        : item.last_failure_at
          ? pill(`失败 ${shortDate(item.last_failure_at)}`, "danger")
          : pill("未采集");
      return `
        <tr>
          <td><input type="checkbox" ${checked} data-account-select="${item.id}" /></td>
          <td>${pill(item.platform)}</td>
          <td>${esc(fmt(item.category))}</td>
          <td>
            <strong>${esc(fmt(item.account_name))}</strong>
            <div class="muted">${esc(fmt(item.radar_name))}</div>
          </td>
          <td>
            <div class="inline-edit">
              <input value="${esc(item.account_handle || "")}" placeholder="handle / channelId / URN" data-account-field="${item.id}:account_handle" />
              <input value="${esc(item.account_url || "")}" placeholder="账号 URL" data-account-field="${item.id}:account_url" />
            </div>
          </td>
          <td>
            <div>阅读 ≥ ${fmtNum(item.threshold_views)}</div>
            <div class="muted">互动率 ≥ ${item.threshold_engagement_rate ? `${(item.threshold_engagement_rate * 100).toFixed(1)}%` : "-"}</div>
          </td>
          <td>${lastStatus}${issue}</td>
          <td><input type="checkbox" ${item.enabled ? "checked" : ""} data-account-toggle="${item.id}" /></td>
        </tr>
      `;
    })
    .join("");
  updateSelectedCount();
}

function updateSelectedCount() {
  $("#selectedCount").textContent = `已选 ${state.selectedAccounts.size} 个`;
}

async function saveAccountField(id, field, value) {
  await api(`/api/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ [field]: value }),
  });
}

async function setSelectedEnabled(enabled) {
  const ids = Array.from(state.selectedAccounts);
  await Promise.all(ids.map((id) => saveAccountField(id, "enabled", enabled)));
  showToast(`已${enabled ? "启用" : "停用"} ${ids.length} 个账号`);
  state.selectedAccounts.clear();
  await Promise.all([loadAccounts(), loadSummaryAndConfig()]);
}

function contentQuery() {
  const params = new URLSearchParams();
  const platform = $("#contentPlatformFilter").value;
  const qualification = $("#contentStatusFilter").value;
  const hasMedia = $("#contentMediaFilter").value;
  if (platform) params.set("platform", platform);
  if (qualification) params.set("qualification", qualification);
  if (hasMedia) params.set("hasMedia", hasMedia);
  params.set("limit", "100");
  return params.toString();
}

async function loadContents() {
  const data = await api(`/api/contents?${contentQuery()}`);
  state.contents = data.items;
  renderContents();
}

async function loadOrganized() {
  const data = await api("/api/organized?limit=100");
  state.organized = data.items;
  renderOrganized();
}

async function loadPublishable() {
  const data = await api("/api/publishable?limit=100");
  state.publishable = data.items;
  renderPublishable();
}

async function loadStrategies() {
  const data = await api("/api/strategies");
  state.strategies = data.items || [];
  renderStrategies();
}

function renderStrategies() {
  const select = $("#chatStrategySelect");
  if (select) {
    select.innerHTML =
      `<option value="">自动选择</option>` +
      state.strategies
        .map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`)
        .join("");
  }
  const list = $("#strategyList");
  if (!list) return;
  list.innerHTML =
    state.strategies
      .map((item) => `
        <article class="strategy-card">
          <div>
            <strong>${esc(item.name)}</strong>
            <p>${esc(item.description || "-")}</p>
          </div>
          <div class="content-meta">
            ${pill(item.platform)}
            ${pill(item.mode)}
            ${pill(item.date_range)}
            ${item.media_only ? pill("仅媒体", "warn") : ""}
            ${item.download_images ? pill("图片", "ok") : ""}
            ${item.download_videos ? pill("视频", "ok") : ""}
            ${item.translate_after_crawl ? pill("翻译", "warn") : ""}
            ${item.ocr_images ? pill("OCR", "warn") : ""}
          </div>
        </article>
      `)
      .join("") || `<div class="empty">暂无采集策略</div>`;
}

function renderMediaAssets(item) {
  const assets = parseMediaAssets(item).filter((asset) => asset && (asset.url || asset.thumbnail_url || asset.local_url));
  if (!assets.length) return "";
  return `
    <div class="media-strip">
      ${assets
        .slice(0, 6)
        .map((asset) => {
          const type = String(asset.type || item.media_type || "media").toLowerCase();
          const url = asset.local_url || asset.url || asset.thumbnail_url || asset.download_url;
          const thumb = asset.local_url || asset.thumbnail_url || asset.url;
          const label = type.includes("video") ? "视频" : "图片";
          return `
            <a class="media-tile ${type.includes("video") ? "video" : ""}" href="${esc(url)}" target="_blank" rel="noreferrer">
              ${thumb ? `<img src="${esc(thumb)}" alt="${esc(label)}" loading="lazy" />` : `<span>${esc(label)}</span>`}
              ${type.includes("video") ? `<span>视频</span>` : ""}
            </a>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderContents() {
  const visibleIds = new Set(state.contents.map((item) => String(item.id)));
  state.selectedRawContents.forEach((id) => {
    if (!visibleIds.has(id)) state.selectedRawContents.delete(id);
  });
  $("#contentList").innerHTML =
    state.contents
      .map((item) => {
        const title = item.title || item.text || item.original_content_id;
        const text = item.text && item.text !== title ? item.text : "";
        const checked = state.selectedRawContents.has(String(item.id)) ? "checked" : "";
        return `
          <article class="content-item" data-content-id="${item.id}">
            <label class="content-select">
              <input type="checkbox" data-raw-content-select="${item.id}" ${checked} />
              <span>选择整理</span>
            </label>
            <div class="content-main">
              <h3>${esc(fmt(title))}</h3>
              <div class="content-meta">
                ${pill(item.platform)}
                <span>${esc(fmt(item.category))}</span>
                <span>${esc(fmt(item.account_name))}</span>
                <span>${esc(shortDate(item.published_at))}</span>
                <span>阅读 ${fmtNum(item.view_count)}</span>
                <span>赞 ${fmtNum(item.like_count)}</span>
                <span>评 ${fmtNum(item.comment_count)}</span>
                <span>转 ${fmtNum(item.share_count)}</span>
                ${statusPill(item.qualification_status)}
                ${pill(item.organize_status || "待整理", "warn")}
                ${pill(item.translation_status || "翻译待处理", item.translation_status === "translated" ? "ok" : "warn")}
              </div>
              <p>${esc(fmt(text || title))}</p>
              ${renderMediaAssets(item)}
            </div>
            <div class="content-actions">
              ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">原文链接</a>` : ""}
              <button type="button" data-organize-one="${item.id}">整理</button>
              <button type="button" data-open-content="${item.id}">详情</button>
            </div>
          </article>
        `;
      })
      .join("") || `<div class="empty">暂无采集结果</div>`;
  updateContentSelectionLabels();
}

function renderOrganized() {
  const visibleIds = new Set(state.organized.map((item) => String(item.id)));
  state.selectedOrganizedContents.forEach((id) => {
    if (!visibleIds.has(id)) state.selectedOrganizedContents.delete(id);
  });
  $("#organizedList").innerHTML =
    state.organized
      .map((item) => {
        const checked = state.selectedOrganizedContents.has(String(item.id)) ? "checked" : "";
        return `
        <article class="content-item" data-organized-id="${item.id}">
          <label class="content-select">
            <input type="checkbox" data-organized-content-select="${item.id}" ${checked} />
            <span>选择发布</span>
          </label>
          <div class="content-main">
            <h3>${esc(item.organized_title || item.title || item.original_content_id)}</h3>
            <div class="content-meta">
              ${pill(item.platform)}
              <span>${esc(fmt(item.category))}</span>
              <span>${esc(fmt(item.account_name))}</span>
              ${pill(item.review_status || "pending_review", item.review_status === "approved" ? "ok" : "warn")}
              ${pill(item.publish_status || "pending")}
              ${pill(item.translation_status || "pending", item.translation_status === "translated" ? "ok" : "warn")}
            </div>
            <p>${esc(item.organized_summary || item.text || "-")}</p>
          </div>
          <div class="content-actions">
            ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">原文</a>` : ""}
            <button type="button" data-publish-organized-one="${item.id}">发布</button>
            <button type="button" data-open-content="${item.id}">详情</button>
          </div>
        </article>
      `;
      })
      .join("") || `<div class="empty">暂无整理内容</div>`;
  updateContentSelectionLabels();
}

function renderPublishable() {
  const visibleIds = new Set(state.publishable.map((item) => String(item.id)));
  state.selectedPublishableContents.forEach((id) => {
    if (!visibleIds.has(id)) state.selectedPublishableContents.delete(id);
  });
  $("#publishList").innerHTML =
    state.publishable
      .map((item) => {
        const checked = state.selectedPublishableContents.has(String(item.id)) ? "checked" : "";
        return `
        <article class="content-item" data-publishable-id="${item.id}">
          <label class="content-select">
            <input type="checkbox" data-publishable-content-select="${item.id}" ${checked} />
            <span>选择发布</span>
          </label>
          <div class="content-main">
            <h3>${esc(item.organized_title || item.title || item.original_content_id)}</h3>
            <div class="content-meta">
              ${pill(item.platform)}
              <span>${esc(fmt(item.category))}</span>
              <span>${esc(fmt(item.account_name))}</span>
              ${pill(item.publish_status || "pending", item.publish_status === "failed" ? "danger" : "warn")}
            </div>
            <p>${esc(item.organized_summary || item.text || "-")}</p>
          </div>
          <div class="content-actions">
            <button type="button" data-publish-one="${item.id}">发布</button>
            <button type="button" data-open-content="${item.id}">详情</button>
          </div>
        </article>
      `;
      })
      .join("") || `<div class="empty">暂无待发布内容</div>`;
  updateContentSelectionLabels();
}

function updateContentSelectionLabels() {
  const rawCount = state.selectedRawContents.size;
  const organizedCount = state.selectedOrganizedContents.size;
  const publishableCount = state.selectedPublishableContents.size;
  const organizeSelectedBtn = $("#organizeSelectedBtn");
  if (organizeSelectedBtn) organizeSelectedBtn.textContent = rawCount ? `整理已选原始数据 (${rawCount})` : "整理已选原始数据";
  const publishOrganizedBtn = $("#publishSelectedOrganizedBtn");
  if (publishOrganizedBtn) publishOrganizedBtn.textContent = organizedCount ? `发布已选整理稿 (${organizedCount})` : "发布已选整理稿";
  const publishSelectedBtn = $("#publishSelectedBtn");
  if (publishSelectedBtn) publishSelectedBtn.textContent = publishableCount ? `发布已选 (${publishableCount})` : "发布已选";
}

function markdownPreview(item) {
  const assets = parseMediaAssets(item);
  const mediaLines = assets.map((asset, index) => `- 媒体 ${index + 1}: ${asset.local_path || asset.url || asset.thumbnail_url || "-"}`).join("\n");
  return `---\nid: ${item.platform}:${item.original_content_id}\nplatform: ${item.platform}\naccount: ${item.account_name}\nsource_url: ${item.url || ""}\ntranslation_status: ${item.translation_status || "pending"}\norganize_status: ${item.organize_status || "pending"}\npublish_status: ${item.publish_status || "pending"}\n---\n\n# ${item.organized_title || item.title || item.original_content_id}\n\n## 原文\n${item.original_text || item.text || ""}\n\n## 中文翻译\n${item.translated_text_zh || "待 Hermes 内容整理 Agent 翻译。"}\n\n## 图片 OCR 原文\n${item.ocr_text_original || "待 OCR。"}\n\n## 图片 OCR 中文\n${item.ocr_text_zh || "待 Hermes 内容整理 Agent 翻译。"}\n\n## 媒体\n${mediaLines || "- 无"}\n\n## 质量建议\n${item.quality_reason || "待 Hermes 内容整理 Agent 评估。"}`;
}

async function openDrawer(id) {
  const allItems = [...state.contents, ...state.organized, ...state.publishable];
  let item = allItems.find((entry) => String(entry.id) === String(id));
  if (!item) return;
  try {
    item = await api(`/api/contents/${id}`);
  } catch {
    // Fall back to the list item if the detail endpoint is unavailable.
  }
  $("#drawerTitle").textContent = item.title || item.original_content_id;
  $("#drawerMeta").textContent = `${item.platform} · ${item.account_name || "-"} · ${shortDate(item.published_at)}`;
  let rawPayload = item.raw_payload || item.raw_payload_json || {};
  if (typeof rawPayload === "string") {
    try {
      rawPayload = JSON.parse(rawPayload);
    } catch {
      rawPayload = { raw: rawPayload };
    }
  }
  $("#drawerBody").innerHTML = `
    <section class="drawer-section">
      <h3>采集来源</h3>
      <div class="state-row">${pill(item.provider || rawPayload.source || "unknown", "active")}${pill(item.platform || "-")}${pill(item.original_content_id || "-")}</div>
    </section>
    <section class="drawer-section">
      <h3>原文</h3>
      <p>${esc(item.original_text || item.text || item.title || "-")}</p>
      ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">打开原文</a>` : ""}
    </section>
    <section class="drawer-section">
      <h3>中文翻译</h3>
      <p>${esc(item.translated_text_zh || "待 Hermes 内容整理 Agent 翻译。")}</p>
      <div class="state-row">${pill(item.translation_status || "pending", item.translation_status === "translated" ? "ok" : "warn")}${pill(item.translation_provider || "hermes-agent")}</div>
    </section>
    <section class="drawer-section">
      <h3>图片 OCR</h3>
      <p><strong>原文：</strong>${esc(item.ocr_text_original || "待 OCR。")}</p>
      <p><strong>中文：</strong>${esc(item.ocr_text_zh || "待 Hermes 内容整理 Agent 翻译。")}</p>
    </section>
    <section class="drawer-section">
      <h3>媒体</h3>
      ${renderMediaAssets(item) || `<div class="empty">无媒体</div>`}
    </section>
    <section class="drawer-section">
      <h3>整理状态</h3>
      <div class="state-row">${pill(item.organize_status || "待整理", "warn")}${pill("OCR 待处理")}${pill(item.publish_status || "待发布")}</div>
    </section>
    <section class="drawer-section">
      <h3>Markdown 预览</h3>
      <pre class="markdown-preview">${esc(item.markdown_preview || item.organized_markdown || markdownPreview(item))}</pre>
    </section>
    <section class="drawer-section">
      <h3>Raw Payload 摘要</h3>
      <pre class="markdown-preview">${esc(JSON.stringify(rawPayload, null, 2).slice(0, 3000))}</pre>
    </section>
  `;
  $("#detailDrawer").classList.add("open");
  $("#detailDrawer").setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  $("#detailDrawer").classList.remove("open");
  $("#detailDrawer").setAttribute("aria-hidden", "true");
}

function mediaQuery() {
  const params = new URLSearchParams();
  const platform = $("#mediaPlatformFilter").value;
  const mediaType = $("#mediaTypeFilter").value;
  const account = $("#mediaAccountSearch").value.trim();
  if (platform) params.set("platform", platform);
  if (mediaType) params.set("mediaType", mediaType);
  if (account) params.set("account", account);
  params.set("limit", "120");
  return params.toString();
}

async function loadMedia() {
  const data = await api(`/api/media?${mediaQuery()}`);
  state.media = data.items;
  renderMedia();
}

function renderMedia() {
  $("#mediaGrid").innerHTML =
    state.media
      .map((item) => `
        <article class="asset-card">
          <a class="asset-preview" href="${esc(item.url || item.source_url)}" target="_blank" rel="noreferrer">
            ${item.thumbnail_url ? `<img src="${esc(item.thumbnail_url)}" alt="${esc(item.media_type)}" loading="lazy" />` : `<span>${esc(item.media_type)}</span>`}
            ${String(item.media_type).includes("video") ? `<b>视频</b>` : ""}
          </a>
          <div class="asset-body">
            <strong>${esc(fmt(item.account_name))}</strong>
            <span>${esc(fmt(item.title)).slice(0, 90)}</span>
            <div class="content-meta">
              ${pill(item.platform)}
              ${pill(item.download_status, item.download_status === "downloaded" ? "ok" : "warn")}
              ${pill(item.ocr_status)}
            </div>
            <a href="${esc(item.source_url)}" target="_blank" rel="noreferrer">原文</a>
          </div>
        </article>
      `)
      .join("") || `<div class="empty">暂无媒体</div>`;
}

async function loadFailures() {
  const data = await api("/api/failures?limit=150");
  state.failures = data.items;
  $("#failuresTable").innerHTML = state.failures
    .map((item) => `
      <tr>
        <td>${esc(shortDate(item.occurred_at))}</td>
        <td>${pill(item.platform)}</td>
        <td>${esc(fmt(item.account_name))}</td>
        <td>${pill(item.error_type, "danger")}</td>
        <td>${esc(fmt(item.error_message))}</td>
      </tr>
    `)
    .join("");
}

async function loadRuns() {
  const data = await api("/api/runs?limit=12");
  state.runs = data.items;
  renderRuns();
}

function renderRuns() {
  $("#runList").innerHTML =
    state.runs
      .map((run) => `
        <article class="run-card">
          <div>
            <strong>${esc(run.input_label || run.id)}</strong>
            <div class="muted">${esc(run.id)}</div>
          </div>
          <div class="run-stats">
            ${pill(run.agent_type || "crawler", "active")}
            ${statusPill(run.status)}
            <span>模式 ${esc(run.mode)}</span>
            <span>账号 ${fmtNum(run.total_accounts)}</span>
            <span>成功 ${fmtNum(run.success_count)}</span>
            <span>失败 ${fmtNum(run.failure_count)}</span>
            <span>内容 ${fmtNum(run.saved_count)}</span>
            <span>媒体 ${fmtNum(run.media_downloaded)}</span>
          </div>
          <div class="run-actions">
            <button type="button" data-open-run="${esc(run.id)}">报告</button>
            <button type="button" data-retry-run="${esc(run.id)}">重跑</button>
          </div>
        </article>
      `)
      .join("") || `<div class="empty">暂无任务</div>`;
}

function renderTokenGrid(config) {
  const xmcpInput = document.querySelector('[name="XMCP_SERVER_URL"]');
  if (xmcpInput && !xmcpInput.value) {
    xmcpInput.value = config.xmcp?.serverUrl || "http://127.0.0.1:8000/mcp";
  }
  const tokenCards = Object.entries(config.tokens || {})
    .map(([platform, ok]) => `<div class="metric"><div class="label">${esc(platform)} token</div><div class="value">${ok ? "已配置" : "未配置"}</div></div>`)
    .join("");
  const chromeSession = config.chromeSession || config.webbridge || {};
  $("#tokenGrid").innerHTML = tokenCards + `<div class="metric"><div class="label">Chrome Session</div><div class="value">${chromeSession.reachable ? "可用" : "不可用"}</div></div>`;
}

async function loadDiagnostics() {
  const data = await api("/api/config/diagnostics");
  renderSetupChecklist(data);
  const cards = [
    ["feedgrab", data.feedgrab?.feedgrab?.installed ? "已安装" : "未安装", data.feedgrab?.feedgrab?.version || data.feedgrab?.feedgrab?.pinnedSource, data.feedgrab?.feedgrab?.installed ? "ok" : "warn"],
    ["X MCP", data.xmcp?.reachable ? "可连" : "不可连", data.xmcp?.message, data.xmcp?.reachable ? "ok" : "warn"],
    ["X Credits", data.credits?.status || "unknown", data.credits?.message, "warn"],
    ["Hermes MCP", data.hermes?.radarMcpConfigured ? "已配置" : "未配置", data.hermes?.runCommand, data.hermes?.radarMcpConfigured ? "ok" : "danger"],
    ["Chrome Session", data.chromeSession?.reachable ? "可用" : "不可用", data.chromeSession?.error || data.chromeSession?.url || data.webbridge?.error || data.webbridge?.url, data.chromeSession?.reachable ? "ok" : "warn"],
    ["飞书存储", data.feishu?.writable ? "可写" : "不可写", data.feishu?.path, data.feishu?.writable ? "ok" : "danger"],
    ["媒体目录", data.media?.writable ? "可写" : "不可写", data.media?.path, data.media?.writable ? "ok" : "danger"],
  ];
  $("#diagnosticsGrid").innerHTML = cards
    .map(([label, value, note, kind]) => `
      <div class="diagnostic ${kind}">
        <div class="label">${esc(label)}</div>
        <div class="value">${esc(value)}</div>
        <p>${esc(note || "")}</p>
      </div>
    `)
    .join("");
}

async function refreshAll() {
  await Promise.all([
    loadSummaryAndConfig(),
    loadAccounts(),
    loadContents(),
    loadOrganized(),
    loadPublishable(),
    loadMedia(),
    loadFailures(),
    loadRuns(),
    loadStrategies(),
    loadDiagnostics(),
  ]);
}

async function submitRun(form, sourceType) {
  const payload = formPayload(form, sourceType);
  $("#runResult").textContent = "任务运行中...";
  const result = await api("/api/runs/crawl", { method: "POST", body: JSON.stringify(payload) });
  $("#runResult").textContent = JSON.stringify(result, null, 2);
  showToast(`任务完成：保存 ${result.saved_count || 0} 条，失败 ${result.failure_count || 0} 个`);
  await refreshAll();
}

async function runOrganizer(contentIds = []) {
  $("#runResult").textContent = "整理任务运行中...";
  const result = await api("/api/organize", {
    method: "POST",
    body: JSON.stringify({ contentIds, translate: true, ocrImages: true, downloadMedia: true }),
  });
  $("#runResult").textContent = JSON.stringify(result, null, 2);
  showToast(`整理完成：${result.success_count || 0} 条`);
  contentIds.forEach((id) => state.selectedRawContents.delete(String(id)));
  await refreshAll();
  return result;
}

async function runPublisher(contentIds = []) {
  const target = $("#targetChannelInput")?.value || "雷达号 APP";
  $("#runResult").textContent = "发布任务运行中...";
  const result = await api("/api/publish", {
    method: "POST",
    body: JSON.stringify({ contentIds, targetChannel: target }),
  });
  $("#runResult").textContent = JSON.stringify(result, null, 2);
  showToast(`发布完成：${result.success_count || 0} 条`);
  contentIds.forEach((id) => {
    state.selectedOrganizedContents.delete(String(id));
    state.selectedPublishableContents.delete(String(id));
  });
  await refreshAll();
  return result;
}

async function exportRawDataset({ format = "jsonl", selectedOnly = false } = {}) {
  const ids = selectedOnly ? Array.from(state.selectedRawContents) : state.contents.map((item) => item.id);
  if (!ids.length) {
    showToast(selectedOnly ? "请先勾选要导出的原始数据" : "当前筛选没有可导出的原始数据");
    return;
  }
  const params = new URLSearchParams();
  params.set("format", format);
  params.set("contentIds", ids.join(","));
  const data = await api(`/api/raw-contents/export?${params.toString()}`);
  const markdown = data.dataset_markdown;
  const jsonl = data.dataset_jsonl;
  const content = format === "markdown" || format === "md"
    ? markdown
    : format === "jsonl"
      ? jsonl
      : JSON.stringify(data.items || [], null, 2);
  const extension = format === "markdown" || format === "md" ? "md" : format === "jsonl" ? "jsonl" : "json";
  const blob = new Blob([content || ""], { type: extension === "md" ? "text/markdown;charset=utf-8" : "application/json;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `radar-raw-dataset-${new Date().toISOString().slice(0, 10)}.${extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  showToast(`已导出 ${data.count || ids.length} 条原始数据`);
}

function bindEvents() {
  $$(".nav").forEach((button) => {
    button.addEventListener("click", () => {
      switchView(button.dataset.view);
    });
  });
  document.addEventListener("click", (event) => {
    const jump = event.target.closest("[data-jump-view]");
    if (jump) {
      switchView(jump.dataset.jumpView);
      return;
    }
    const agentJump = event.target.closest("[data-agent-jump]");
    if (agentJump) {
      setActiveAgent(agentJump.dataset.agentJump);
      switchView("chat");
    }
  });

  $("#refreshBtn").addEventListener("click", refreshAll);
  $("#reloadRunsBtn").addEventListener("click", loadRuns);
  $("#reloadFailuresBtn").addEventListener("click", loadFailures);
  $("#diagnosticsBtn").addEventListener("click", loadDiagnostics);
  $("#settingsDiagnosticsShortcut")?.addEventListener("click", loadDiagnostics);
  $("#closeDrawerBtn").addEventListener("click", closeDrawer);
  $$(".agent-tab").forEach((button) => {
    button.addEventListener("click", () => setActiveAgent(button.dataset.agent));
  });
  $("#toggleRulePanelBtn").addEventListener("click", () => {
    $("#rulePanel").classList.toggle("collapsed");
  });
  $("#rulePanel").addEventListener("click", (event) => {
    const button = event.target.closest(".rule-chip");
    if (!button) return;
    button.classList.toggle("active");
    updateActiveRuleCount();
  });
  $("#promptSuggestions").addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (!button) return;
    const textarea = $("#agentChatForm textarea");
    textarea.value = button.dataset.prompt;
    textarea.focus();
  });
  $("#chatFileInput").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    $("#attachmentStatus").textContent = `解析中：${file.name}`;
    appendChat("user", "我", `<p>上传附件：${esc(file.name)}</p>`);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch("/api/agent/upload", { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
      appendChat("assistant", (agentCopy[state.activeAgent] || agentCopy.crawler).name, uploadSummaryHtml(result));
      if (result.suggestedPrompt) {
        const textarea = $("#agentChatForm textarea");
        textarea.value = result.suggestedPrompt;
        textarea.focus();
      }
      $("#attachmentStatus").textContent = `已解析：${file.name}`;
      await Promise.all([loadAccounts(), loadSummaryAndConfig()]);
    } catch (error) {
      appendChat("assistant", (agentCopy[state.activeAgent] || agentCopy.crawler).name, `<p class="danger-text">附件解析失败：${esc(error.message)}</p>`);
      $("#attachmentStatus").textContent = "附件解析失败";
    } finally {
      event.target.value = "";
    }
  });
  $("#xmcpConfigForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {};
    ["XMCP_SERVER_URL", "X_BEARER_TOKEN", "X_API_KEY", "X_API_SECRET"].forEach((key) => {
      const value = String(form.get(key) || "").trim();
      if (value) payload[key] = value;
    });
    const result = await api("/api/config/xmcp", { method: "POST", body: JSON.stringify(payload) });
    ["X_BEARER_TOKEN", "X_API_KEY", "X_API_SECRET"].forEach((key) => {
      const input = document.querySelector(`[name="${key}"]`);
      if (input) input.value = "";
    });
    showToast(`MCP 配置已保存：更新 ${result.updated} 项`);
    await Promise.all([loadSummaryAndConfig(), loadDiagnostics()]);
  });

  const accountRunForm = $("#accountRunForm");
  if (accountRunForm) {
    accountRunForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitRun(event.currentTarget, "account");
    });
  }
  const fileRunForm = $("#fileRunForm");
  if (fileRunForm) {
    fileRunForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitRun(event.currentTarget, "file");
    });
  }
  $("#agentChatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const textarea = event.currentTarget.querySelector("textarea");
    const message = textarea.value.trim();
    if (!message) return;
    const copy = agentCopy[state.activeAgent] || agentCopy.crawler;
    const strategyId = $("#chatStrategySelect")?.value || "";
    const strategy = state.strategies.find((item) => item.id === strategyId);
    const rules = activeRulesText();
    const finalMessage = rules ? `${message}。${copy.ruleLabel}：${rules}` : message;
    appendChat("user", "我", `<p>${esc(message)}</p>${rules || strategy ? `<div class="task-summary">${strategy ? pill(`策略 ${strategy.name}`, "active") : ""}${rules ? rules.split("，").map((item) => pill(item)).join("") : ""}</div>` : ""}`);
    textarea.value = "";
    appendChat("assistant", copy.name, `<p>${esc(copy.pendingText)}</p>`);
    try {
      let result;
      if (state.activeAgent === "organizer") {
        const ids = state.selectedRawContents.size ? Array.from(state.selectedRawContents) : state.contents.map((item) => item.id);
        result = { reply: `已交给整理 Agent 处理 ${ids.length} 条原始数据。`, task: { platform: "contents", mode: "organize", identifier: `${ids.length} 条原始数据` }, run: await runOrganizer(ids) };
      } else if (state.activeAgent === "publisher") {
        const ids = state.selectedPublishableContents.size
          ? Array.from(state.selectedPublishableContents)
          : state.selectedOrganizedContents.size
            ? Array.from(state.selectedOrganizedContents)
            : state.publishable.map((item) => item.id);
        result = { reply: `已交给发布 Agent 处理 ${ids.length} 条整理稿。`, task: { platform: "contents", mode: "publish", identifier: `${ids.length} 条整理稿` }, run: await runPublisher(ids) };
      } else {
        result = await api("/api/agent/chat", {
          method: "POST",
          body: JSON.stringify({ message: finalMessage, strategyId }),
        });
      }
      const task = result.task || {};
      appendChat(
        "assistant",
        copy.name,
        `
          <p>${esc(result.reply || "任务已处理。")}</p>
          <div class="task-summary">
            ${pill(`平台 ${task.platform || "-"}`)}
            ${pill(`模式 ${task.mode || "-"}`)}
            ${pill(`账号 ${task.identifier || "文件/账号源"}`)}
            ${pill(`时间 ${task.dateRange || "-"}`)}
            ${task.strategyId ? pill(`策略 ${task.strategyId}`, "active") : ""}
            ${task.schedule ? pill(task.schedule, "active") : ""}
            ${task.translateAfterCrawl ? pill("翻译", "warn") : ""}
            ${task.ocrImages ? pill("OCR", "warn") : ""}
          </div>
        `,
      );
      $("#runResult").textContent = JSON.stringify(result, null, 2);
      await Promise.all([loadRuns(), loadContents(), loadOrganized(), loadPublishable(), loadMedia(), loadSummaryAndConfig()]);
    } catch (error) {
      appendChat("assistant", copy.name, `<p class="danger-text">${esc(error.message)}</p>`);
    }
  });

  const importExcelBtn = $("#importExcelBtn");
  if (importExcelBtn) {
    importExcelBtn.addEventListener("click", async () => {
      const result = await api("/api/import-excel", { method: "POST", body: "{}" });
      showToast(`导入 ${result.imported} 条，问题 ${result.qualityIssues} 条`);
      await refreshAll();
    });
  }
  const importXIntelBtn = $("#importXIntelBtn");
  if (importXIntelBtn) {
    importXIntelBtn.addEventListener("click", async () => {
      const result = await api("/api/import-x-intel", { method: "POST", body: JSON.stringify({ category: "AI情报源" }) });
      showToast(`导入 AI 情报源 ${result.imported} 条`);
      await refreshAll();
    });
  }
  const enrichAccountsBtn = $("#enrichAccountsBtn");
  if (enrichAccountsBtn) {
    enrichAccountsBtn.addEventListener("click", async () => {
      const result = await api("/api/enrich-accounts", { method: "POST", body: JSON.stringify({ overwrite: false }) });
      showToast(`补全 ${result.updated} 条，跳过 ${result.skipped} 条`);
      await refreshAll();
    });
  }

  ["accountPlatformFilter", "accountStatusFilter"].forEach((id) => $(`#${id}`).addEventListener("change", loadAccounts));
  $("#accountSearch").addEventListener("input", () => {
    window.clearTimeout(window.__accountSearchTimer);
    window.__accountSearchTimer = window.setTimeout(loadAccounts, 240);
  });
  $("#accountsTable").addEventListener("change", async (event) => {
    const target = event.target;
    if (target.matches("[data-account-select]")) {
      const id = target.dataset.accountSelect;
      if (target.checked) state.selectedAccounts.add(id);
      else state.selectedAccounts.delete(id);
      updateSelectedCount();
    }
    if (target.matches("[data-account-toggle]")) {
      await saveAccountField(target.dataset.accountToggle, "enabled", target.checked);
      showToast("账号状态已保存");
      await Promise.all([loadAccounts(), loadSummaryAndConfig()]);
    }
    if (target.matches("[data-account-field]")) {
      const [id, field] = target.dataset.accountField.split(":");
      await saveAccountField(id, field, target.value.trim());
      showToast("账号配置已保存");
    }
  });
  $("#selectAllAccounts").addEventListener("change", (event) => {
    state.selectedAccounts.clear();
    if (event.target.checked) {
      state.accounts.forEach((item) => state.selectedAccounts.add(String(item.id)));
    }
    renderAccounts();
  });
  $("#enableSelectedBtn").addEventListener("click", () => setSelectedEnabled(true));
  $("#disableSelectedBtn").addEventListener("click", () => setSelectedEnabled(false));

  ["contentPlatformFilter", "contentStatusFilter", "contentMediaFilter"].forEach((id) => $(`#${id}`).addEventListener("change", loadContents));
  $("#organizeSelectedBtn").addEventListener("click", async () => {
    const ids = Array.from(state.selectedRawContents);
    if (!ids.length) {
      showToast("请先在原始数据中勾选要整理的内容");
      return;
    }
    await runOrganizer(ids);
  });
  $("#organizeVisibleBtn").addEventListener("click", async () => {
    await runOrganizer(state.contents.map((item) => item.id));
  });
  $("#exportSelectedJsonlBtn").addEventListener("click", () => exportRawDataset({ format: "jsonl", selectedOnly: true }));
  $("#exportVisibleMarkdownBtn").addEventListener("click", () => exportRawDataset({ format: "markdown", selectedOnly: false }));
  $("#contentList").addEventListener("click", (event) => {
    const checkbox = event.target.closest("[data-raw-content-select]");
    if (checkbox) {
      const id = String(checkbox.dataset.rawContentSelect);
      if (checkbox.checked) state.selectedRawContents.add(id);
      else state.selectedRawContents.delete(id);
      updateContentSelectionLabels();
      return;
    }
    const organizeButton = event.target.closest("[data-organize-one]");
    if (organizeButton) {
      runOrganizer([organizeButton.dataset.organizeOne]);
      return;
    }
    const button = event.target.closest("[data-open-content]");
    if (button) openDrawer(button.dataset.openContent);
  });
  $("#loadOrganizedBtn").addEventListener("click", loadOrganized);
  $("#organizedList").addEventListener("click", (event) => {
    const checkbox = event.target.closest("[data-organized-content-select]");
    if (checkbox) {
      const id = String(checkbox.dataset.organizedContentSelect);
      if (checkbox.checked) state.selectedOrganizedContents.add(id);
      else state.selectedOrganizedContents.delete(id);
      updateContentSelectionLabels();
      return;
    }
    const publishButton = event.target.closest("[data-publish-organized-one]");
    if (publishButton) {
      runPublisher([publishButton.dataset.publishOrganizedOne]);
      return;
    }
    const button = event.target.closest("[data-open-content]");
    if (button) openDrawer(button.dataset.openContent);
  });
  $("#publishSelectedOrganizedBtn").addEventListener("click", async () => {
    const ids = Array.from(state.selectedOrganizedContents);
    if (!ids.length) {
      showToast("请先在整理库中勾选要发布的整理稿");
      return;
    }
    await runPublisher(ids);
  });
  $("#publishSelectedBtn").addEventListener("click", async () => {
    const ids = Array.from(state.selectedPublishableContents);
    if (!ids.length) {
      showToast("请先在发布中心勾选要发布的内容");
      return;
    }
    await runPublisher(ids);
  });
  $("#publishVisibleBtn").addEventListener("click", async () => {
    await runPublisher(state.publishable.map((item) => item.id));
  });
  $("#publishList").addEventListener("click", async (event) => {
    const checkbox = event.target.closest("[data-publishable-content-select]");
    if (checkbox) {
      const id = String(checkbox.dataset.publishableContentSelect);
      if (checkbox.checked) state.selectedPublishableContents.add(id);
      else state.selectedPublishableContents.delete(id);
      updateContentSelectionLabels();
      return;
    }
    const publishButton = event.target.closest("[data-publish-one]");
    const openButton = event.target.closest("[data-open-content]");
    if (publishButton) await runPublisher([publishButton.dataset.publishOne]);
    if (openButton) openDrawer(openButton.dataset.openContent);
  });

  ["mediaPlatformFilter", "mediaTypeFilter"].forEach((id) => $(`#${id}`).addEventListener("change", loadMedia));
  $("#mediaAccountSearch").addEventListener("input", () => {
    window.clearTimeout(window.__mediaSearchTimer);
    window.__mediaSearchTimer = window.setTimeout(loadMedia, 240);
  });

  $("#runList").addEventListener("click", async (event) => {
    const openButton = event.target.closest("[data-open-run]");
    const retryButton = event.target.closest("[data-retry-run]");
    if (openButton) {
      const result = await api(`/api/runs/${openButton.dataset.openRun}`);
      $("#runResult").textContent = JSON.stringify(result, null, 2);
    }
    if (retryButton) {
      $("#runResult").textContent = "重跑任务中...";
      const result = await api(`/api/runs/${retryButton.dataset.retryRun}/retry`, { method: "POST", body: "{}" });
      $("#runResult").textContent = JSON.stringify(result, null, 2);
      await refreshAll();
    }
  });
}

bindEvents();
updateActiveRuleCount();
refreshAll().catch((error) => showToast(error.message));
