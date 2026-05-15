from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8780"
START_API_COMMAND = "./tools/run_radar_api.sh"


class ApiUnavailable(RuntimeError):
    """Raised when the Radar API is not reachable."""


def _base_url(value: str | None = None) -> str:
    return (value or os.getenv("RADAR_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _request(method: str, path: str, payload: dict[str, Any] | None = None, *, base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    body = None
    headers = {"Accept": "application/json"}
    api_token = os.getenv("RADAR_API_TOKEN", "").strip()
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Radar API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiUnavailable(str(exc.reason)) from exc
    return json.loads(data) if data else {}


def _query(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "", [], False)}
    if not clean:
        return path
    return f"{path}?{urllib.parse.urlencode(clean, doseq=True)}"


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _summary_lines(result: dict[str, Any]) -> list[str]:
    feedback = result.get("agent_feedback") if isinstance(result.get("agent_feedback"), dict) else {}
    summary = feedback.get("summary") if isinstance(feedback.get("summary"), dict) else {}
    lines: list[str] = []
    message = result.get("reply") or feedback.get("message")
    if message:
        lines.append(str(message))
    task_id = result.get("id") or result.get("task_id")
    if task_id:
        lines.append(f"任务: {task_id}")
    if result.get("status"):
        lines.append(f"状态: {result['status']}")
    if result.get("saved_count") is not None:
        lines.append(f"保存: {result.get('saved_count')} 失败: {result.get('failure_count', 0)}")
    content_ids = feedback.get("content_ids") or result.get("content_ids")
    if content_ids:
        lines.append(f"内容 IDs: {', '.join(str(item) for item in content_ids)}")
    execution_backends = summary.get("execution_backends") or result.get("execution_backends")
    if execution_backends:
        lines.append(f"执行后端: {', '.join(str(item) for item in execution_backends)}")
    top_contents = feedback.get("top_contents") or result.get("top_contents") or []
    if isinstance(top_contents, list) and top_contents:
        lines.append("Top 内容:")
        for item in top_contents[:5]:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("original_content_id") or item.get("content_id")
            url = item.get("source_url") or item.get("url")
            provider = item.get("provider")
            backend = item.get("execution_backend")
            detail = " / ".join(str(value) for value in (provider, backend) if value)
            suffix = f" ({detail})" if detail else ""
            lines.append(f"- {title or '-'}{suffix}")
            if url:
                lines.append(f"  {url}")
    if not lines:
        lines.append(_json(result))
    return lines


def render_result(result: dict[str, Any], *, json_output: bool = False) -> str:
    if json_output:
        return _json(result)
    return "\n".join(_summary_lines(result))


def render_error(error: Exception, *, json_output: bool, base_url: str) -> str:
    if isinstance(error, ApiUnavailable):
        payload = {
            "ok": False,
            "error": {
                "code": "radar_api_unavailable",
                "message": f"Radar API unavailable at {base_url}: {error}",
                "fix": START_API_COMMAND,
            },
        }
        if json_output:
            return _json(payload)
        return f"{payload['error']['message']}\n修复: {START_API_COMMAND}"
    payload = {"ok": False, "error": {"code": type(error).__name__, "message": str(error)}}
    return _json(payload) if json_output else payload["error"]["message"]


def read_urls_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def handle_chat(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    instruction = " ".join(args.instruction).strip()
    return _request(
        "POST",
        "/api/agent/chat",
        {"message": instruction, "execute": not args.dry_run},
        base_url=base_url,
    )


def collect_payload(args: argparse.Namespace) -> dict[str, Any]:
    urls = args.urls or ""
    if args.urls_file:
        urls = read_urls_file(args.urls_file)
    source_type = "url" if (args.url or urls) else ("keyword" if args.query else ("account" if args.identifier else "file"))
    return {
        "sourceType": source_type,
        "identifier": args.identifier or "",
        "url": args.url or "",
        "urls": urls,
        "query": args.query or "",
        "platform": args.platform,
        "mode": args.mode,
        "category": args.category,
        "dateRange": args.date_range,
        "limit": args.limit,
        "maxResults": args.limit,
        "includeOriginal": args.include_original,
        "includeReplies": args.include_replies,
        "includeRetweets": args.include_retweets,
        "includeQuotes": args.include_quotes,
        "downloadImages": args.download_images,
        "downloadVideos": args.download_videos,
        "downloadMedia": args.download_images or args.download_videos,
        "mediaOnly": args.media_only,
        "queue": args.queue,
    }


def handle_collect(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    return _request("POST", "/api/collection-tasks", collect_payload(args), base_url=base_url)


def handle_task(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    if args.task_command == "list":
        return _request("GET", _query("/api/collection-tasks", {"limit": args.limit}), None, base_url=base_url)
    if args.task_command == "get":
        return _request("GET", f"/api/collection-tasks/{urllib.parse.quote(args.task_id)}", None, base_url=base_url)
    if args.task_command == "retry":
        return _request("POST", f"/api/runs/{urllib.parse.quote(args.task_id)}/retry", {"queue": args.queue}, base_url=base_url)
    if args.task_command == "cancel":
        return _request(
            "POST",
            f"/api/runs/{urllib.parse.quote(args.task_id)}/status",
            {"status": "cancelled", "message": args.message or "cancelled by beeclaw cli"},
            base_url=base_url,
        )
    raise RuntimeError("unsupported task command")


def handle_content(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    if args.content_command == "list":
        return _request(
            "GET",
            _query(
                "/api/raw-contents",
                {
                    "platform": args.platform,
                    "runId": args.run_id,
                    "hasMedia": "1" if args.has_media else "",
                    "limit": args.limit,
                },
            ),
            None,
            base_url=base_url,
        )
    if args.content_command == "get":
        return _request("GET", f"/api/raw-contents/{args.content_id}", None, base_url=base_url)
    if args.content_command == "export":
        return _request(
            "GET",
            _query(
                "/api/raw-contents/export",
                {
                    "platform": args.platform,
                    "runId": args.run_id,
                    "contentIds": args.content_ids,
                    "hasMedia": "1" if args.has_media else "",
                    "limit": args.limit,
                    "format": args.format,
                },
            ),
            None,
            base_url=base_url,
        )
    raise RuntimeError("unsupported content command")


def handle_media(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    if args.media_command == "list":
        return _request(
            "GET",
            _query(
                "/api/media-assets",
                {
                    "contentId": args.content_id or "",
                    "runId": args.run_id,
                    "status": args.status,
                    "limit": args.limit,
                },
            ),
            None,
            base_url=base_url,
        )
    if args.media_command == "retry":
        if args.media_id:
            return _request("POST", f"/api/media-assets/{args.media_id}/retry", {}, base_url=base_url)
        return _request(
            "POST",
            "/api/media-assets/retry",
            {"contentId": args.content_id, "runId": args.run_id, "status": args.status, "limit": args.limit},
            base_url=base_url,
        )
    if args.media_command == "export":
        return _request(
            "GET",
            _query(
                "/api/media-assets/export",
                {
                    "contentId": args.content_id or "",
                    "runId": args.run_id,
                    "status": args.status,
                    "limit": args.limit,
                    "format": args.format,
                },
            ),
            None,
            base_url=base_url,
        )
    raise RuntimeError("unsupported media command")


def handle_provider(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    if args.provider_command == "list":
        return _request("GET", _query("/api/providers", {"platform": args.platform}), None, base_url=base_url)
    if args.provider_command == "health":
        return _request("GET", "/api/providers/health", None, base_url=base_url)
    raise RuntimeError("unsupported provider command")


def handle_worker(args: argparse.Namespace, _base_url: str) -> dict[str, Any]:
    from .worker import process_queued_runs, run_worker_loop

    if args.worker_command != "run":
        raise RuntimeError("unsupported worker command")
    if args.daemon:
        return run_worker_loop(
            Path(args.db),
            limit=args.limit,
            poll_interval_seconds=args.poll_interval,
            idle_limit=args.idle_limit,
            retry_delay_seconds=args.retry_delay,
        )
    return process_queued_runs(Path(args.db), limit=args.limit, retry_delay_seconds=args.retry_delay)


def handle_config(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    if args.config_command == "show":
        return {"base_url": base_url, "start_api_command": START_API_COMMAND}
    raise RuntimeError("unsupported config command")


def add_common_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--identifier", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--urls", default="")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--platform", default="x")
    parser.add_argument("--mode", default="auto")
    parser.add_argument("--category", default="Chat采集")
    parser.add_argument("--date-range", default="7d")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--include-original", action="store_true", default=True)
    parser.add_argument("--include-replies", action="store_true", default=False)
    parser.add_argument("--include-retweets", action="store_true", default=False)
    parser.add_argument("--include-quotes", action="store_true", default=True)
    parser.add_argument("--download-images", action="store_true", default=True)
    parser.add_argument("--download-videos", action="store_true", default=True)
    parser.add_argument("--media-only", action="store_true", default=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beeclaw", description="Beeclaw Agent CLI for Radar data collection.")
    parser.add_argument("--base-url", default=None, help="Radar API base URL. Defaults to RADAR_BASE_URL or http://127.0.0.1:8780")
    parser.add_argument("--json", action="store_true", dest="json_output", help="print raw JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat = subparsers.add_parser("chat", help="send a natural-language collection instruction")
    chat.add_argument("instruction", nargs="+")
    chat.add_argument("--dry-run", action="store_true", help="parse instruction without executing collection")
    chat.set_defaults(handler=handle_chat)

    collect = subparsers.add_parser("collect", help="create a structured collection task")
    add_common_collect_args(collect)
    collect.set_defaults(handler=handle_collect)

    task = subparsers.add_parser("task", help="manage collection tasks")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_list = task_sub.add_parser("list")
    task_list.add_argument("--limit", type=int, default=50)
    task_list.set_defaults(handler=handle_task)
    task_get = task_sub.add_parser("get")
    task_get.add_argument("task_id")
    task_get.set_defaults(handler=handle_task)
    task_retry = task_sub.add_parser("retry")
    task_retry.add_argument("task_id")
    task_retry.add_argument("--queue", action="store_true", default=True)
    task_retry.set_defaults(handler=handle_task)
    task_cancel = task_sub.add_parser("cancel")
    task_cancel.add_argument("task_id")
    task_cancel.add_argument("--message", default="")
    task_cancel.set_defaults(handler=handle_task)

    content = subparsers.add_parser("content", help="list, inspect, or export raw contents")
    content_sub = content.add_subparsers(dest="content_command", required=True)
    content_list = content_sub.add_parser("list")
    content_list.add_argument("--platform", default="")
    content_list.add_argument("--run-id", default="")
    content_list.add_argument("--has-media", action="store_true")
    content_list.add_argument("--limit", type=int, default=50)
    content_list.set_defaults(handler=handle_content)
    content_get = content_sub.add_parser("get")
    content_get.add_argument("content_id", type=int)
    content_get.set_defaults(handler=handle_content)
    content_export = content_sub.add_parser("export")
    content_export.add_argument("--platform", default="")
    content_export.add_argument("--run-id", default="")
    content_export.add_argument("--content-ids", default="")
    content_export.add_argument("--has-media", action="store_true")
    content_export.add_argument("--limit", type=int, default=100)
    content_export.add_argument("--format", default="json", choices=["json", "jsonl", "md", "markdown"])
    content_export.set_defaults(handler=handle_content)

    media = subparsers.add_parser("media", help="list, retry, or export media assets")
    media_sub = media.add_subparsers(dest="media_command", required=True)
    media_list = media_sub.add_parser("list")
    media_list.add_argument("--content-id", type=int, default=0)
    media_list.add_argument("--run-id", default="")
    media_list.add_argument("--status", default="")
    media_list.add_argument("--limit", type=int, default=100)
    media_list.set_defaults(handler=handle_media)
    media_retry = media_sub.add_parser("retry")
    media_retry.add_argument("--media-id", type=int, default=0)
    media_retry.add_argument("--content-id", type=int, default=0)
    media_retry.add_argument("--run-id", default="")
    media_retry.add_argument("--status", default="failed")
    media_retry.add_argument("--limit", type=int, default=100)
    media_retry.set_defaults(handler=handle_media)
    media_export = media_sub.add_parser("export")
    media_export.add_argument("--content-id", type=int, default=0)
    media_export.add_argument("--run-id", default="")
    media_export.add_argument("--status", default="")
    media_export.add_argument("--limit", type=int, default=100)
    media_export.add_argument("--format", default="json", choices=["json", "jsonl", "md", "markdown"])
    media_export.set_defaults(handler=handle_media)

    provider = subparsers.add_parser("provider", help="inspect Beeclaw providers")
    provider_sub = provider.add_subparsers(dest="provider_command", required=True)
    provider_list = provider_sub.add_parser("list")
    provider_list.add_argument("--platform", default="")
    provider_list.set_defaults(handler=handle_provider)
    provider_health = provider_sub.add_parser("health")
    provider_health.set_defaults(handler=handle_provider)

    worker = subparsers.add_parser("worker", help="process queued tasks")
    worker_sub = worker.add_subparsers(dest="worker_command", required=True)
    worker_run = worker_sub.add_parser("run")
    worker_run.add_argument("--db", default="data/radar_sources.sqlite3")
    worker_run.add_argument("--limit", type=int, default=1)
    worker_run.add_argument("--daemon", action="store_true")
    worker_run.add_argument("--poll-interval", type=float, default=5.0)
    worker_run.add_argument("--idle-limit", type=int, default=1)
    worker_run.add_argument("--retry-delay", type=int, default=60)
    worker_run.set_defaults(handler=handle_worker)

    config = subparsers.add_parser("config", help="show CLI configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show")
    config_show.set_defaults(handler=handle_config)
    return parser


def normalize_argv(argv: list[str] | None) -> list[str] | None:
    if argv is None:
        return None
    normalized = list(argv)
    if "--json" in normalized:
        normalized = [item for item in normalized if item != "--json"]
        normalized.insert(0, "--json")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_argv(argv))
    base_url = _base_url(args.base_url)
    try:
        result = args.handler(args, base_url)
        print(render_result(result, json_output=args.json_output))
        return 0
    except Exception as exc:
        print(render_error(exc, json_output=args.json_output, base_url=base_url))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
