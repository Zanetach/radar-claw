from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .feishu_store import LocalFeishuStore


DEFAULT_WORKSPACE = Path("feishu_workspace")


def json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: str, content_type: str) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def make_handler(store: LocalFeishuStore) -> type[BaseHTTPRequestHandler]:
    class HermesDemoHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            routes = {
                "/": self.index,
                "/api/summary": self.api_summary,
                "/api/accounts": self.api_accounts,
                "/api/contents": self.api_contents,
                "/api/runs": self.api_runs,
                "/api/markdown": self.api_markdown,
                "/api/review": self.api_review,
            }
            handler = routes.get(parsed.path)
            if handler is None:
                json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            handler(parse_qs(parsed.query))

        def index(self, query: dict[str, list[str]]) -> None:
            text_response(self, HTTPStatus.OK, INDEX_HTML, "text/html; charset=utf-8")

        def api_summary(self, query: dict[str, list[str]]) -> None:
            accounts = store.read_table("source_accounts")
            contents = store.read_table("content_index")
            runs = store.read_table("agent_runs")
            by_status: dict[str, int] = {}
            by_category: dict[str, int] = {}
            for row in contents:
                status = row.get("publish_status") or row.get("review_status") or row.get("organize_status") or "unknown"
                by_status[status] = by_status.get(status, 0) + 1
                category = row.get("category") or "未分类"
                by_category[category] = by_category.get(category, 0) + 1
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "accounts": len(accounts),
                    "contents": len(contents),
                    "runs": len(runs),
                    "by_status": by_status,
                    "by_category": by_category,
                },
            )

        def api_accounts(self, query: dict[str, list[str]]) -> None:
            rows = store.read_table("source_accounts")
            platform = first(query, "platform")
            if platform:
                rows = [row for row in rows if row.get("platform") == platform]
            json_response(self, HTTPStatus.OK, rows[:200])

        def api_contents(self, query: dict[str, list[str]]) -> None:
            rows = store.read_table("content_index")
            rows.sort(key=lambda row: row.get("updated_at") or row.get("published_at") or "", reverse=True)
            json_response(self, HTTPStatus.OK, rows[:200])

        def api_runs(self, query: dict[str, list[str]]) -> None:
            rows = store.read_table("agent_runs")
            rows.sort(key=lambda row: row.get("created_at") or row.get("started_at") or "", reverse=True)
            json_response(self, HTTPStatus.OK, rows[:100])

        def api_markdown(self, query: dict[str, list[str]]) -> None:
            path = first(query, "path")
            if not path:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "missing_path"})
                return
            try:
                markdown = store.read_markdown(path)
            except FileNotFoundError:
                json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            json_response(self, HTTPStatus.OK, {"path": path, "markdown": markdown})

        def api_review(self, query: dict[str, list[str]]) -> None:
            unique_key = first(query, "key")
            status = first(query, "status")
            if not unique_key or status not in {"approved", "rejected", "pending"}:
                json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_review_request"})
                return
            rows = store.read_table("content_index")
            for index, row in enumerate(rows):
                if row.get("unique_key") == unique_key:
                    rows[index] = {**row, "review_status": status}
                    store.write_table("content_index", rows)
                    json_response(self, HTTPStatus.OK, rows[index])
                    return
            json_response(self, HTTPStatus.NOT_FOUND, {"error": "content_not_found"})

    return HermesDemoHandler


def first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Radar Hermes Demo</title>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #16202a; background: #f6f7f9; }
    header { padding: 22px 28px; background: #ffffff; border-bottom: 1px solid #dfe4ea; }
    h1 { margin: 0; font-size: 22px; }
    main { padding: 22px 28px; display: grid; gap: 18px; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 12px; }
    .stat, section { background: #fff; border: 1px solid #dfe4ea; border-radius: 8px; }
    .stat { padding: 14px; }
    .label { color: #667485; font-size: 12px; }
    .value { margin-top: 6px; font-size: 24px; font-weight: 650; }
    section { overflow: hidden; }
    section h2 { margin: 0; padding: 14px 16px; font-size: 15px; border-bottom: 1px solid #dfe4ea; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #edf0f3; vertical-align: top; }
    th { color: #566272; font-weight: 600; background: #fbfcfd; }
    tr:hover td { background: #f8fafc; }
    button { border: 1px solid #cfd7df; background: #fff; border-radius: 6px; padding: 6px 10px; cursor: pointer; }
    .markdown-preview { padding: 16px; overflow: auto; line-height: 1.6; max-height: 620px; }
    .markdown-preview h1 { margin: 0 0 14px; font-size: 24px; }
    .markdown-preview h2 { margin: 22px 0 10px; padding: 0; border: 0; font-size: 18px; }
    .markdown-preview h3 { margin: 18px 0 8px; font-size: 15px; }
    .markdown-preview p { margin: 8px 0; }
    .markdown-preview ul, .markdown-preview ol { margin: 8px 0 12px 22px; padding: 0; }
    .markdown-preview li { margin: 5px 0; }
    .markdown-preview a { color: #1f66d1; text-decoration: none; }
    .markdown-preview a:hover { text-decoration: underline; }
    .markdown-preview code { background: #eef2f6; border-radius: 4px; padding: 1px 4px; font-size: 12px; }
    .markdown-preview pre { margin: 12px 0; padding: 12px; overflow: auto; white-space: pre; line-height: 1.5; background: #0e1720; color: #eaf2ff; border-radius: 6px; }
    .frontmatter { border: 1px solid #dfe4ea; background: #fbfcfd; border-radius: 6px; margin-bottom: 16px; overflow: hidden; }
    .frontmatter-title { padding: 10px 12px; color: #566272; font-size: 12px; font-weight: 650; border-bottom: 1px solid #dfe4ea; }
    .frontmatter table { font-size: 12px; }
    .frontmatter th { width: 32%; }
    .empty-preview { color: #667485; }
    .grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 18px; }
    @media (max-width: 900px) { .stats, .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header><h1>Radar Hermes Agent Demo</h1></header>
  <main>
    <div class="stats" id="stats"></div>
    <div class="grid">
      <section>
        <h2>内容索引</h2>
        <table>
          <thead><tr><th>标题</th><th>平台</th><th>状态</th><th>原文</th><th>审核</th><th>Markdown</th></tr></thead>
          <tbody id="contents"></tbody>
        </table>
      </section>
      <section>
        <h2>Markdown 预览</h2>
        <div id="markdown" class="markdown-preview empty-preview">选择一条内容查看 Markdown。</div>
      </section>
    </div>
    <section>
      <h2>Agent 运行记录</h2>
      <table>
        <thead><tr><th>Agent</th><th>类型</th><th>状态</th><th>成功</th><th>失败</th><th>报告</th></tr></thead>
        <tbody id="runs"></tbody>
      </table>
    </section>
  </main>
  <script>
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    async function getJson(url) { const res = await fetch(url); return res.json(); }
    const agentNameMap = {
      content_crawler: "内容抓取",
      content_organizer: "内容整理",
      content_publisher: "内容发布",
    };
    const runTypeMap = {
      crawl: "抓取",
      organize: "整理",
      publish: "发布",
      publish_dry_run: "发布预演",
    };
    function renderInline(text) {
      let value = esc(text);
      value = value.replace(/`([^`]+)`/g, "<code>$1</code>");
      value = value.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
      value = value.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
      value = value.replace(/(^|\\s)(https?:\\/\\/[^\\s<]+)/g, '$1<a href="$2" target="_blank" rel="noreferrer">$2</a>');
      return value;
    }
    function parseFrontmatter(markdown) {
      if (!markdown.startsWith("---\\n")) return { meta: [], body: markdown };
      const end = markdown.indexOf("\\n---", 4);
      if (end < 0) return { meta: [], body: markdown };
      const raw = markdown.slice(4, end).trim();
      const body = markdown.slice(end + 4).replace(/^\\n+/, "");
      const meta = raw.split("\\n").map(line => {
        const index = line.indexOf(":");
        return index > 0 ? [line.slice(0, index).trim(), line.slice(index + 1).trim()] : [line, ""];
      });
      return { meta, body };
    }
    function renderMarkdown(markdown) {
      const { meta, body } = parseFrontmatter(markdown || "");
      const lines = body.split("\\n");
      const html = [];
      let listType = null;
      let paragraph = [];
      let inCode = false;
      let codeLines = [];
      const flushParagraph = () => {
        if (!paragraph.length) return;
        html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
        paragraph = [];
      };
      const closeList = () => {
        if (!listType) return;
        html.push(`</${listType}>`);
        listType = null;
      };
      for (const line of lines) {
        if (line.startsWith("```")) {
          if (inCode) {
            html.push(`<pre><code>${esc(codeLines.join("\\n"))}</code></pre>`);
            codeLines = [];
            inCode = false;
          } else {
            flushParagraph();
            closeList();
            inCode = true;
          }
          continue;
        }
        if (inCode) {
          codeLines.push(line);
          continue;
        }
        if (!line.trim()) {
          flushParagraph();
          closeList();
          continue;
        }
        const heading = line.match(/^(#{1,3})\\s+(.+)$/);
        if (heading) {
          flushParagraph();
          closeList();
          html.push(`<h${heading[1].length}>${renderInline(heading[2])}</h${heading[1].length}>`);
          continue;
        }
        const bullet = line.match(/^[-*]\\s+(.+)$/);
        if (bullet) {
          flushParagraph();
          if (listType !== "ul") {
            closeList();
            listType = "ul";
            html.push("<ul>");
          }
          html.push(`<li>${renderInline(bullet[1])}</li>`);
          continue;
        }
        const ordered = line.match(/^\\d+\\.\\s+(.+)$/);
        if (ordered) {
          flushParagraph();
          if (listType !== "ol") {
            closeList();
            listType = "ol";
            html.push("<ol>");
          }
          html.push(`<li>${renderInline(ordered[1])}</li>`);
          continue;
        }
        closeList();
        paragraph.push(line.trim());
      }
      flushParagraph();
      closeList();
      if (inCode) html.push(`<pre><code>${esc(codeLines.join("\\n"))}</code></pre>`);
      const metaHtml = meta.length
        ? `<div class="frontmatter"><div class="frontmatter-title">Frontmatter</div><table><tbody>${meta.map(([key, value]) => `<tr><th>${esc(key)}</th><td>${renderInline(value)}</td></tr>`).join("")}</tbody></table></div>`
        : "";
      return metaHtml + html.join("");
    }
    async function load() {
      const [summary, contents, runs] = await Promise.all([getJson("/api/summary"), getJson("/api/contents"), getJson("/api/runs")]);
      document.getElementById("stats").innerHTML = [
        ["账号源", summary.accounts],
        ["内容索引", summary.contents],
        ["运行记录", summary.runs],
        ["分类数", Object.keys(summary.by_category || {}).length],
      ].map(([label, value]) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
      document.getElementById("contents").innerHTML = contents.map(row => `
        <tr>
          <td>${esc(row.title)}</td>
          <td>${esc(row.platform)}<br><span class="label">${esc(row.account)}</span></td>
          <td>${esc(row.organize_status)} / ${esc(row.review_status)} / ${esc(row.publish_status)}</td>
          <td>${row.source_url ? `<a href="${esc(row.source_url)}" target="_blank" rel="noreferrer">打开原文</a>` : ""}</td>
          <td>
            <button data-review="${esc(row.unique_key)}" data-status="approved">批准</button>
            <button data-review="${esc(row.unique_key)}" data-status="rejected">拒绝</button>
          </td>
          <td><button data-path="${esc(row.markdown_path)}">查看</button></td>
        </tr>`).join("");
      document.querySelectorAll("button[data-review]").forEach(button => {
        button.addEventListener("click", async () => {
          await getJson(`/api/review?key=${encodeURIComponent(button.dataset.review)}&status=${encodeURIComponent(button.dataset.status)}`);
          await load();
        });
      });
      document.querySelectorAll("button[data-path]").forEach(button => {
        button.addEventListener("click", async () => {
          const payload = await getJson(`/api/markdown?path=${encodeURIComponent(button.dataset.path)}`);
          const preview = document.getElementById("markdown");
          preview.classList.remove("empty-preview");
          preview.innerHTML = renderMarkdown(payload.markdown || JSON.stringify(payload, null, 2));
        });
      });
      document.getElementById("runs").innerHTML = runs.map(row => `
        <tr>
          <td>${esc(agentNameMap[row.agent_name] || row.agent_name)}</td>
          <td>${esc(runTypeMap[row.run_type] || row.run_type)}</td>
          <td>${esc(row.status)}</td>
          <td>${esc(row.success_count)}</td>
          <td>${esc(row.failure_count)}</td>
          <td>${esc(row.report_markdown_path || row.report_json_path)}</td>
        </tr>`).join("");
    }
    load();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Hermes Feishu workspace demo viewer.")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8776)
    args = parser.parse_args()
    store = LocalFeishuStore(args.workspace)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"Hermes demo viewer running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
