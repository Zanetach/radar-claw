#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_PLATFORMS = [
    "x",
    "xhs",
    "wechat",
    "youtube",
    "bilibili",
    "douyin",
    "weibo",
    "zhihu",
    "github",
    "feishu",
    "kdocs",
    "youdao",
    "rss",
    "telegram",
    "reddit",
    "hackernews",
    "medium",
    "linuxdo",
    "idcflare",
    "xiaoyuzhou",
    "ximalaya",
    "web",
]


DEFAULT_CASES: dict[str, dict[str, str]] = {
    "x": {"account": "@elonmusk", "keyword": "AI"},
    "youtube": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "keyword": "AI tools"},
    "github": {"url": "https://github.com/vercel-labs/agent-browser"},
    "rss": {"url": "https://hnrss.org/frontpage"},
    "reddit": {"url": "https://www.reddit.com/r/artificial/", "keyword": "AI tools"},
    "hackernews": {"url": "https://news.ycombinator.com/"},
    "medium": {"url": "https://medium.com/"},
    "web": {"url": "https://example.com"},
}


@dataclass
class SmokeCase:
    platform: str
    source_type: str
    value: str | None


def env_case(platform: str, source_type: str) -> str | None:
    key = f"BEECLAW_SMOKE_{platform.upper()}_{source_type.upper()}"
    return os.getenv(key)


def build_cases(platforms: list[str], types: list[str]) -> list[SmokeCase]:
    cases: list[SmokeCase] = []
    for platform in platforms:
        defaults = DEFAULT_CASES.get(platform, {})
        for source_type in types:
            value = env_case(platform, source_type) or defaults.get(source_type)
            cases.append(SmokeCase(platform=platform, source_type=source_type, value=value))
    return cases


def task_payload(case: SmokeCase, *, limit: int, queue: bool, backend: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"platform": case.platform, "sourceType": case.source_type, "limit": limit}
    if queue:
        body["queue"] = True
    if backend and case.source_type == "url":
        body["backend"] = backend
    if case.source_type == "url":
        body["url"] = case.value
    elif case.source_type == "account":
        body["identifier"] = case.value
        body["mode"] = "auto"
    elif case.source_type == "keyword":
        body["query"] = case.value
        body["maxResults"] = limit
    return body


def request_json(base_url: str, path: str, payload: dict[str, Any], *, timeout: int = 180) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def run_case(base_url: str, case: SmokeCase, *, execute: bool, queue: bool, limit: int, backend: str | None) -> dict[str, Any]:
    if not case.value:
        return {
            "platform": case.platform,
            "type": case.source_type,
            "status": "missing_input",
            "env": f"BEECLAW_SMOKE_{case.platform.upper()}_{case.source_type.upper()}",
        }
    payload = task_payload(case, limit=limit, queue=queue, backend=backend)
    result: dict[str, Any] = {
        "platform": case.platform,
        "type": case.source_type,
        "input": case.value,
        "payload": payload,
        "status": "dry_run",
    }
    if not execute:
        return result
    try:
        response = request_json(base_url, "/api/collection-tasks", payload)
        result.update(
            {
                "status": response.get("status") or ("success" if response.get("saved_count", 0) else "completed"),
                "task_id": response.get("id"),
                "saved_count": response.get("saved_count", response.get("saved", 0)),
                "failure_count": response.get("failure_count", response.get("failures", 0)),
                "execution_backends": ((response.get("agent_feedback") or {}).get("summary") or {}).get("execution_backends"),
                "response": response,
            }
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        result.update({"status": "http_error", "code": exc.code, "error": body[:500]})
    except Exception as exc:
        result.update({"status": "error", "error": str(exc)})
    return result


def parse_csv(value: str, *, defaults: list[str]) -> list[str]:
    if not value or value == "all":
        return defaults
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def render_text(results: list[dict[str, Any]]) -> str:
    lines = ["Beeclaw platform smoke results", ""]
    for item in results:
        label = f"{item['platform']}:{item['type']}"
        if item["status"] == "missing_input":
            lines.append(f"- {label}: missing input, set {item['env']}")
            continue
        saved = item.get("saved_count")
        failures = item.get("failure_count")
        backend = item.get("execution_backends")
        suffix = f", saved={saved}, failures={failures}, backend={backend}" if saved is not None else ""
        lines.append(f"- {label}: {item['status']}{suffix}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Beeclaw URL/account/keyword smoke checks through Radar API.")
    parser.add_argument("--base-url", default=os.getenv("RADAR_BASE_URL", "http://127.0.0.1:8780"))
    parser.add_argument("--platforms", default="all", help="Comma-separated platforms or all")
    parser.add_argument("--types", default="url,account,keyword", help="Comma-separated: url,account,keyword")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--backend", default=None, help="Optional URL backend hint, e.g. agent-browser")
    parser.add_argument("--queue", action="store_true", help="Create queued tasks instead of running immediately")
    parser.add_argument("--execute", action="store_true", help="Actually call Radar API. Default is dry-run.")
    parser.add_argument("--fail-on-missing", action="store_true", help="Return non-zero if any selected case has no configured input.")
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    args = parser.parse_args()

    platforms = parse_csv(args.platforms, defaults=DEFAULT_PLATFORMS)
    types = parse_csv(args.types, defaults=["url", "account", "keyword"])
    cases = build_cases(platforms, types)
    results = [
        run_case(args.base_url, case, execute=args.execute, queue=args.queue, limit=args.limit, backend=args.backend)
        for case in cases
    ]
    payload = {"ok": True, "execute": args.execute, "base_url": args.base_url, "results": results}
    missing = [item for item in results if item["status"] == "missing_input"]
    failed = [item for item in results if item["status"] in {"error", "http_error", "failed"}]
    if missing and args.fail_on_missing:
        payload["ok"] = False
    if failed:
        payload["ok"] = False
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else render_text(results))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
