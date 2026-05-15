import unittest
import json
import os
import sqlite3
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import urlopen

from crawler.beeclaw_adapter import FeedgrabUnavailable
from crawler.db import init_db, save_fetch_result, upsert_accounts
from crawler.models import ContentItem, FetchResult, SourceAccount
from crawler.providers import ProviderError
from crawler.web import RadarAdminHandler, infer_platform_from_url, parse_chat_prompt
from crawler.worker import process_next_queued_run, process_queued_runs, run_worker_loop
from tests.test_providers import XGO_RSS


def sample_account() -> SourceAccount:
    return SourceAccount(
        category="AI",
        platform="x",
        account_name="OpenAI",
        original_account="X-OpenAI",
        official_identity="OpenAI",
        radar_name="Radar AI",
        radar_persona="AI",
        threshold_views=None,
        threshold_engagement_rate=None,
        average_views=None,
        raw_average_views="",
        raw_threshold="",
        source_row_number=1,
    )


def source_account(name: str, handle: str, *, platform: str = "x", category: str = "AI") -> SourceAccount:
    return SourceAccount(
        category=category,
        platform=platform,
        account_name=name,
        original_account=f"{platform}-{name}",
        official_identity=name,
        radar_name="Radar AI",
        radar_persona="AI",
        threshold_views=None,
        threshold_engagement_rate=None,
        average_views=None,
        raw_average_views="",
        raw_threshold="",
        source_row_number=1,
    )


class WebChatTests(unittest.TestCase):
    @patch("crawler.web.probe_mcp_endpoint")
    def test_mcp_integrations_expose_radar_and_x_backend_without_secret_values(self, probe_mcp_endpoint):
        probe_mcp_endpoint.return_value = {"url": "http://x-mcp:8000/mcp", "reachable": True, "message": "HTTP 200"}
        handler = object.__new__(RadarAdminHandler)

        with patch.dict(
            os.environ,
            {
                "MCP_MANAGER_NAME": "platform-mcp-manager",
                "MCP_MANAGER_DISPLAY_NAME": "Platform MCP Manager",
                "XMCP_SERVER_URL": "http://x-mcp:8000/mcp",
                "X_BEARER_TOKEN": "secret-token",
                "X_API_TOOL_ALLOWLIST": "getUsersByUsername,getUsersPosts",
            },
        ):
            result = handler.api_mcp_integrations({})

        self.assertEqual(result["manager"]["name"], "platform-mcp-manager")
        self.assertEqual(result["manager"]["displayName"], "Platform MCP Manager")
        self.assertEqual(result["manager"]["type"], "control_plane")
        integrations = {item["name"]: item for item in result["items"]}
        self.assertEqual(integrations["radar"]["type"], "agent_tool")
        self.assertTrue(integrations["radar"]["defaultAgentBinding"])
        self.assertEqual(integrations["x-mcp"]["type"], "backend")
        self.assertFalse(integrations["x-mcp"]["defaultAgentBinding"])
        self.assertEqual(integrations["x-mcp"]["status"], "connected")
        self.assertEqual(integrations["x-mcp"]["endpoint"], "http://x-mcp:8000/mcp")
        self.assertEqual(integrations["x-mcp"]["toolAllowlist"], ["getUsersByUsername", "getUsersPosts"])
        self.assertTrue(integrations["x-mcp"]["secretStatus"]["X_BEARER_TOKEN"])
        self.assertEqual(integrations["xiaohongshu-mcp"]["type"], "backend")
        self.assertFalse(integrations["xiaohongshu-mcp"]["defaultAgentBinding"])
        self.assertNotIn("secret-token", json.dumps(result))

    @patch("crawler.web.probe_mcp_endpoint")
    def test_mcp_integrations_can_filter_backend_type(self, probe_mcp_endpoint):
        probe_mcp_endpoint.return_value = {"url": "http://x-mcp:8000/mcp", "reachable": False, "message": "offline"}
        handler = object.__new__(RadarAdminHandler)

        result = handler.api_mcp_integrations({"type": ["backend"]})

        self.assertEqual([item["name"] for item in result["items"]], ["x-mcp", "xiaohongshu-mcp"])

    @patch("crawler.web.probe_mcp_endpoint")
    def test_mcp_integrations_support_platform_gateway_mode_without_exposing_runtime_token(self, probe_mcp_endpoint):
        probe_mcp_endpoint.return_value = {"url": "unused", "reachable": False, "message": "not used"}
        handler = object.__new__(RadarAdminHandler)

        with patch.dict(
            os.environ,
            {
                "RADAR_BACKEND_MCP_MODE": "platform_gateway",
                "PLATFORM_MCP_GATEWAY_URL": "http://gateway.local/mcp",
                "PLATFORM_MCP_RUNTIME_TOKEN": "secret-runtime-token",
                "MCP_MANAGER_NAME": "tenant-mcp-manager",
                "MCP_MANAGER_DISPLAY_NAME": "Tenant MCP Manager",
                "MCP_MANAGER_MANAGED_BY": "tenant_platform",
            },
        ):
            result = handler.api_mcp_integrations({"type": ["backend"]})

        integrations = {item["name"]: item for item in result["items"]}
        self.assertEqual(integrations["x-mcp"]["invocationMode"], "platform_gateway")
        self.assertEqual(integrations["x-mcp"]["endpoint"], "platform://mcp/x-mcp")
        self.assertEqual(integrations["x-mcp"]["message"], "managed_by_tenant_mcp_manager")
        self.assertEqual(integrations["x-mcp"]["managedBy"], "tenant_platform")
        self.assertEqual(result["manager"]["name"], "tenant-mcp-manager")
        self.assertEqual(result["manager"]["status"], "connected")
        self.assertTrue(integrations["x-mcp"]["gateway"]["urlConfigured"])
        self.assertEqual(integrations["xiaohongshu-mcp"]["endpoint"], "platform://mcp/xiaohongshu-mcp")
        self.assertNotIn("secret-runtime-token", json.dumps(result))

    @patch("crawler.web.probe_mcp_endpoint")
    def test_production_readiness_reports_all_production_gaps_without_secrets(self, probe_mcp_endpoint):
        probe_mcp_endpoint.return_value = {"url": "http://x-mcp:8000/mcp", "reachable": True, "message": "HTTP 200"}
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            with patch.dict(os.environ, {"X_BEARER_TOKEN": "secret-token"}, clear=False):
                result = handler.api_production_readiness({})

        self.assertEqual(result["summary"]["totalChecks"], 6)
        check_ids = {item["id"] for item in result["checks"]}
        self.assertEqual(
            check_ids,
            {
                "platform_mcp_gateway",
                "x_mcp_production_pressure",
                "deep_platform_providers",
                "large_task_queue_worker",
                "media_assets_production",
                "agent_feedback_standardization",
            },
        )
        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual(checks["large_task_queue_worker"]["projectSide"], "implemented")
        self.assertEqual(checks["agent_feedback_standardization"]["status"], "implemented")
        self.assertIn("radar_xmcp_pressure_test", " ".join(checks["x_mcp_production_pressure"]["nextActions"]))
        self.assertNotIn("secret-token", json.dumps(result))

    def test_root_is_api_metadata_not_web_ui(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"

            class TestHandler(RadarAdminHandler):
                pass

            TestHandler.db_path = db_path
            server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
                    content_type = response.headers.get("Content-Type", "")
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertIn("application/json", content_type)
            self.assertEqual(payload["service"], "radar-api")
            self.assertEqual(payload["entrypoint"], "ai-agent")
            self.assertNotIn("html", json.dumps(payload).lower())

    def test_chrome_session_prompt_sets_mode(self):
        task = parse_chat_prompt("使用 chrome-session 抓取 @elonmusk 最近7天原创推文，下载图片和视频，不要转发")
        self.assertEqual(task["platform"], "x")
        self.assertEqual(task["identifier"], "elonmusk")
        self.assertEqual(task["mode"], "chrome-session")
        self.assertEqual(task["dateRange"], "7d")
        self.assertFalse(task["includeRetweets"])

    def test_free_prompt_uses_beeclaw_x_rss(self):
        task = parse_chat_prompt("免费抓取 @OpenAI 最近7天原创推文，保留图片")
        self.assertEqual(task["mode"], "beeclaw:x_rss")
        self.assertEqual(task["identifier"], "OpenAI")

    def test_default_x_prompt_uses_auto_to_allow_fallback(self):
        task = parse_chat_prompt("抓取 @OpenAI 最近7天原创推文，保留图片和视频")
        self.assertEqual(task["platform"], "x")
        self.assertEqual(task["mode"], "auto")
        self.assertEqual(task["sourceType"], "account")

    def test_url_prompt_infers_facebook_url_collection(self):
        task = parse_chat_prompt("采集 Facebook 这个页面 https://www.facebook.com/openai/posts/123")
        self.assertEqual(task["platform"], "facebook")
        self.assertEqual(task["sourceType"], "url")
        self.assertEqual(task["url"], "https://www.facebook.com/openai/posts/123")
        self.assertEqual(task["mode"], "beeclaw")

    def test_beeclaw_platform_url_inference_covers_supported_media(self):
        cases = {
            "https://www.bilibili.com/video/BV1xx": "bilibili",
            "https://v.douyin.com/iabc/": "douyin",
            "https://mp.weixin.qq.com/s/example": "wechat",
            "https://m.weibo.cn/status/123": "weibo",
            "https://www.zhihu.com/question/123/answer/456": "zhihu",
            "https://github.com/iBigQiang/feedgrab": "github",
            "https://zane.feishu.cn/docx/example": "feishu",
            "https://www.kdocs.cn/l/example": "kdocs",
            "https://note.youdao.com/s/example": "youdao",
            "https://t.me/example/123": "telegram",
            "https://www.reddit.com/r/LocalLLaMA/comments/abc/post/": "reddit",
            "https://news.ycombinator.com/item?id=1": "hackernews",
            "https://medium.com/@author/post": "medium",
            "https://linux.do/t/topic/123": "linuxdo",
            "https://idcflare.com/post/example": "idcflare",
            "https://www.xiaoyuzhoufm.com/episode/123": "xiaoyuzhou",
            "https://www.ximalaya.com/sound/123": "ximalaya",
            "https://example.com/feed.xml": "rss",
        }
        for url, platform in cases.items():
            with self.subTest(url=url):
                self.assertEqual(infer_platform_from_url(url), platform)

    def test_xhs_keyword_prompt_creates_keyword_collection_task(self):
        task = parse_chat_prompt("采集小红书上关于 AI 工具 的热门笔记，保留图片")
        self.assertEqual(task["platform"], "xhs")
        self.assertEqual(task["sourceType"], "keyword")
        self.assertEqual(task["query"], "AI 工具")
        self.assertEqual(task["mode"], "beeclaw")

    def test_agent_chat_non_x_without_url_requests_url_without_failed_run(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            result = handler.api_agent_chat({"message": "抓取微博上雷军最近 10 条内容", "execute": True})

            self.assertIsNone(result["run"])
            self.assertEqual(result["task"]["platform"], "weibo")
            self.assertIn("请提供", result["reply"])
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM crawl_runs").fetchone()["count"], 0)

    def test_agent_chat_scheduled_request_returns_runtime_schedule_without_run(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            result = handler.api_agent_chat({"message": "每天 10 点抓取 @OpenAI 最近 24 小时推文", "execute": True})

            self.assertIsNone(result["run"])
            self.assertEqual(result["agent_feedback"]["status"], "requires_runtime_schedule")
            schedule_request = result["agent_feedback"]["runtime_schedule"]
            self.assertEqual(schedule_request["owner"], "hermes_agent_runtime")
            self.assertFalse(schedule_request["radar_executes_schedule"])
            self.assertEqual(schedule_request["execution_tool"], "radar_create_collection_task")
            self.assertEqual(schedule_request["execution_payload"]["identifier"], "OpenAI")
            self.assertEqual(schedule_request["execution_payload"]["date_range"], "24h")
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM crawl_runs").fetchone()["count"], 0)

    def test_save_organized_content_preserves_original_and_writes_translation(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            upsert_accounts(conn, [sample_account()])
            account_id = conn.execute("SELECT id FROM source_accounts").fetchone()["id"]
            save_fetch_result(
                conn,
                FetchResult(
                    account_id=account_id,
                    platform="x",
                    items=[
                        ContentItem(
                            platform="x",
                            original_content_id="post-1",
                            title="AI launch",
                            text="A new model was launched today.",
                            published_at="2026-05-12T00:00:00Z",
                            url="https://x.com/OpenAI/status/post-1",
                            view_count=None,
                            like_count=None,
                            comment_count=None,
                            share_count=None,
                            media_type="text",
                            language="en",
                            raw_payload={"id": "post-1"},
                        )
                    ],
                ),
            )
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            content_id = conn.execute("SELECT id FROM source_contents").fetchone()["id"]

            result = handler.api_save_organized_content(
                {
                    "contentId": content_id,
                    "organizedTitle": "AI 发布",
                    "organizedSummary": "OpenAI 发布了新模型。",
                    "translatedTextZh": "今天发布了一个新模型。",
                    "qualityScore": 0.9,
                    "qualityReason": "有明确事件和来源。",
                    "contentCategory": "AI",
                }
            )

            self.assertEqual(result["original_text"], "A new model was launched today.")
            self.assertEqual(result["translated_text_zh"], "今天发布了一个新模型。")
            self.assertEqual(result["translation_status"], "translated")
            self.assertIn("## 原文", result["organized_markdown"])
            self.assertIn("## 中文翻译", result["organized_markdown"])

    @patch("crawler.web.read_url")
    def test_collection_task_url_uses_beeclaw_and_saves_raw_content(self, read_url):
        read_url.return_value = {
            "source_type": "twitter",
            "source_name": "OpenAI",
            "title": "Launch",
            "content": "A new model launched.",
            "url": "https://x.com/OpenAI/status/123",
            "id": "abc",
            "extra": {"tweet_id": "123", "views": 100},
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://x.com/OpenAI/status/123"})

            self.assertEqual(run["saved_count"], 1)
            row = conn.execute("SELECT platform, provider, original_content_id, original_text FROM source_contents").fetchone()
            self.assertEqual(row["platform"], "x")
            self.assertEqual(row["provider"], "beeclaw:universal_reader")
            self.assertEqual(row["original_content_id"], "123")
            self.assertEqual(row["original_text"], "A new model launched.")
            links = conn.execute("SELECT * FROM crawl_run_contents WHERE run_id = ?", (run["id"],)).fetchall()
            self.assertEqual(len(links), 1)
            self.assertEqual(run["contents"][0]["original_content_id"], "123")
            feedback = run["agent_feedback"]
            self.assertEqual(feedback["audience"], "ai_employee")
            self.assertIn("保存 1 条", feedback["message"])
            self.assertEqual(feedback["content_ids"], [run["contents"][0]["id"]])
            self.assertTrue(any(action["tool"] == "radar_handoff_to_organizer" for action in feedback["next_actions"]))
            self.assertIn("crawl-", feedback["report_markdown"])

    @patch("crawler.web.read_url")
    def test_collection_task_url_feedback_includes_beeclaw_backend_attempts(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "Jina Reader",
            "title": "Readable Page",
            "content": "Readable page body.",
            "url": "https://example.com/readable",
            "id": "readable-page",
            "extra": {
                "provider_backend": "Jina Reader",
                "backend_attempts": [{"backend": "Jina Reader", "status": "success"}],
            },
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://example.com/readable"})

            self.assertEqual(run["agent_feedback"]["summary"]["execution_backends"], ["Jina Reader"])
            self.assertEqual(run["agent_feedback"]["backend_attempts"], [{"backend": "Jina Reader", "status": "success"}])
            self.assertEqual(run["agent_feedback"]["top_contents"][0]["execution_backend"], "Jina Reader")

    @patch("crawler.web.read_url")
    def test_collection_task_url_failure_finishes_run_with_agent_feedback(self, read_url):
        read_url.side_effect = RuntimeError("reader connection closed")
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://example.com/broken", "platform": "web"})

            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["failure_count"], 1)
            self.assertEqual(run["saved_count"], 0)
            self.assertEqual(run["agent_feedback"]["status"], "failed")
            self.assertEqual(run["agent_feedback"]["errors"][0]["error"], "RuntimeError")
            self.assertIn("reader connection closed", run["agent_feedback"]["errors"][0]["message"])

    @patch("crawler.web.read_url")
    def test_rss_url_collection_saves_each_feed_entry_as_raw_content(self, read_url):
        read_url.return_value = {
            "source_type": "rss",
            "source_name": "rss_parser",
            "title": "Radar Feed",
            "content": "- Entry 1\n  https://example.com/1\n- Entry 2\n  https://example.com/2",
            "url": "https://example.com/feed.xml",
            "id": "feed-id",
            "extra": {
                "provider_backend": "rss_parser",
                "backend_attempts": [{"backend": "rss_parser", "status": "success"}],
                "feed_url": "https://example.com/feed.xml",
                "feed_link": "https://example.com/",
                "items": [
                    {
                        "id": "entry-1",
                        "title": "Entry 1",
                        "url": "https://example.com/1",
                        "published_at": "2026-05-14T10:00:00Z",
                        "summary": "First item.",
                        "media_assets": [{"type": "image", "url": "https://example.com/1.jpg"}],
                    },
                    {
                        "id": "entry-2",
                        "title": "Entry 2",
                        "url": "https://example.com/2",
                        "published_at": "2026-05-14T11:00:00Z",
                        "summary": "Second item.",
                        "media_assets": [],
                    },
                ],
            },
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://example.com/feed.xml", "platform": "rss"})

            self.assertEqual(run["saved_count"], 2)
            self.assertEqual(run["agent_feedback"]["summary"]["execution_backends"], ["rss_parser"])
            rows = conn.execute(
                "SELECT platform, provider, original_content_id, title, url, media_type, raw_payload_json FROM source_contents ORDER BY original_content_id"
            ).fetchall()
            self.assertEqual([row["original_content_id"] for row in rows], ["entry-1", "entry-2"])
            self.assertEqual([row["url"] for row in rows], ["https://example.com/1", "https://example.com/2"])
            self.assertEqual(rows[0]["platform"], "rss")
            self.assertEqual(rows[0]["provider"], "beeclaw:rss")
            self.assertEqual(rows[0]["media_type"], "image")
            self.assertIn('"feed_url": "https://example.com/feed.xml"', rows[0]["raw_payload_json"])
            self.assertIn('"rss_entry"', rows[0]["raw_payload_json"])
            media_rows = conn.execute("SELECT media_type, url FROM media_assets").fetchall()
            self.assertEqual(len(media_rows), 1)
            self.assertEqual(media_rows[0]["url"], "https://example.com/1.jpg")

    @patch("crawler.web.read_url")
    def test_agent_chat_facebook_url_collects_via_beeclaw_and_saves_raw_content(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "Facebook Page",
            "title": "AI tools post",
            "content": "A public Facebook post about AI tools.",
            "url": "https://www.facebook.com/openai/posts/123",
            "id": "fb-123",
            "extra": {"images": ["https://example.com/fb.jpg"]},
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            result = handler.api_agent_chat(
                {
                    "message": "采集 Facebook 这个页面 https://www.facebook.com/openai/posts/123，保留图片",
                    "execute": True,
                }
            )

            self.assertIn("保存 1 条", result["reply"])
            row = conn.execute("SELECT platform, provider, original_text FROM source_contents").fetchone()
            self.assertEqual(row["platform"], "facebook")
            self.assertEqual(row["provider"], "beeclaw:universal_reader")
            self.assertEqual(row["original_text"], "A public Facebook post about AI tools.")

    @patch("crawler.web.read_url")
    def test_collection_task_bilibili_url_is_saved_as_bilibili_raw_content(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "Bilibili",
            "title": "AI video",
            "content": "A Bilibili video about AI.",
            "url": "https://www.bilibili.com/video/BV1xx",
            "id": "bv-1",
            "extra": {"videos": [{"url": "https://example.com/video.mp4"}]},
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://www.bilibili.com/video/BV1xx"})

            self.assertEqual(run["saved_count"], 1)
            self.assertEqual(run["agent_feedback"]["top_contents"][0]["provider"], "beeclaw:bilibili")
            self.assertEqual(run["agent_feedback"]["top_contents"][0]["execution_backend"], "beeclaw:universal_reader")
            row = conn.execute("SELECT platform, provider, media_type, media_assets_json FROM source_contents").fetchone()
            self.assertEqual(row["platform"], "bilibili")
            self.assertEqual(row["provider"], "beeclaw:bilibili")
            self.assertEqual(row["media_type"], "video")
            self.assertIn("video.mp4", row["media_assets_json"])
            media_rows = conn.execute("SELECT media_type, url, download_status FROM media_assets").fetchall()
            self.assertEqual(len(media_rows), 1)
            self.assertEqual(media_rows[0]["media_type"], "video")
            self.assertIn("video.mp4", media_rows[0]["url"])
            self.assertEqual(media_rows[0]["download_status"], "pending")

    @patch("crawler.web.read_url")
    def test_media_assets_api_lists_assets_for_content(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "Bilibili",
            "title": "AI video",
            "content": "A Bilibili video about AI.",
            "url": "https://www.bilibili.com/video/BV1xx",
            "id": "bv-1",
            "extra": {"videos": [{"url": "https://example.com/video.mp4"}]},
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://www.bilibili.com/video/BV1xx"})
            content_id = run["contents"][0]["id"]
            assets = handler.api_media_assets({"contentId": [str(content_id)]})

            self.assertEqual(assets["count"], 1)
            self.assertEqual(assets["items"][0]["provider"], "beeclaw:bilibili")
            self.assertEqual(assets["items"][0]["download_status"], "pending")

    @patch("crawler.web.read_url")
    def test_media_assets_bulk_retry_and_export_manifest(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "Bilibili",
            "title": "AI video",
            "content": "A Bilibili video about AI.",
            "url": "https://www.bilibili.com/video/BV1xx",
            "id": "bv-1",
            "extra": {"videos": [{"url": "https://example.com/video.mp4"}]},
        }
        with TemporaryDirectory() as tmp, patch("crawler.web.download_media_url") as download:
            download.return_value = {
                "local_path": "data/media/bilibili/1/asset-1.mp4",
                "local_url": "/data/media/bilibili/1/asset-1.mp4",
                "content_type": "video/mp4",
                "bytes": 123,
            }
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task({"url": "https://www.bilibili.com/video/BV1xx"})
            content_id = run["contents"][0]["id"]
            retry = handler.api_media_assets_retry({"contentId": content_id, "status": "pending"})
            export = handler.api_export_media_assets({"contentId": [str(content_id)], "format": ["jsonl"]})

            self.assertEqual(retry["attempted"], 1)
            self.assertEqual(retry["downloaded"], 1)
            self.assertEqual(export["count"], 1)
            self.assertIn("video.mp4", export["dataset_jsonl"])
            self.assertIn("data/media/bilibili", export["dataset_jsonl"])

    @patch("crawler.web.read_url")
    def test_queued_collection_task_is_executed_by_worker(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "GitHub",
            "title": "Radar",
            "content": "Radar repository.",
            "url": "https://github.com/Zanetach/radar-claw",
            "id": "repo-1",
            "extra": {},
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            queued = handler.api_create_collection_task(
                {"url": "https://github.com/Zanetach/radar-claw", "queue": True}
            )

            self.assertEqual(queued["status"], "queued")
            self.assertEqual(queued["saved_count"], 0)
            self.assertEqual(queued["agent_feedback"]["status"], "queued")
            processed = process_next_queued_run(db_path)
            self.assertEqual(processed["processed"], 1)
            self.assertEqual(processed["run"]["id"], queued["id"])
            self.assertEqual(processed["run"]["status"], "success")
            self.assertEqual(processed["run"]["agent_feedback"]["content_ids"], [processed["run"]["contents"][0]["id"]])

    @patch("crawler.web.read_url")
    def test_worker_retries_failed_queued_task_until_success(self, read_url):
        read_url.side_effect = [
            FeedgrabUnavailable("temporary feedgrab outage"),
            {
                "source_type": "web",
                "source_name": "GitHub",
                "title": "Radar",
                "content": "Radar repository.",
                "url": "https://github.com/Zanetach/radar-claw",
                "id": "repo-retry",
                "extra": {},
            },
        ]
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            queued = handler.api_create_collection_task(
                {"url": "https://github.com/Zanetach/radar-claw", "queue": True, "maxAttempts": 2}
            )
            first = process_queued_runs(db_path, limit=1, retry_delay_seconds=0)
            self.assertEqual(first["processed"], 1)
            first_row = conn.execute("SELECT status, attempt_count FROM crawl_runs WHERE id = ?", (queued["id"],)).fetchone()
            self.assertEqual(first_row["status"], "queued")
            self.assertEqual(first_row["attempt_count"], 1)

            second = process_queued_runs(db_path, limit=1, retry_delay_seconds=0)

            self.assertEqual(second["processed"], 1)
            final = handler.api_run_detail(queued["id"])
            self.assertEqual(final["status"], "success")
            self.assertEqual(final["saved_count"], 1)
            self.assertEqual(final["attempt_count"], 2)

    @patch("crawler.web.read_url")
    def test_worker_loop_polls_until_queued_task_arrives_or_limit_reached(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "GitHub",
            "title": "Radar",
            "content": "Radar repository.",
            "url": "https://github.com/Zanetach/radar-claw",
            "id": "repo-loop",
            "extra": {},
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            queued = handler.api_create_collection_task(
                {"url": "https://github.com/Zanetach/radar-claw", "queue": True}
            )

            result = run_worker_loop(db_path, limit=1, poll_interval_seconds=0, idle_limit=1)

            self.assertEqual(result["processed"], 1)
            self.assertEqual(handler.api_run_detail(queued["id"])["status"], "success")

    @patch("crawler.web.read_url")
    def test_run_retry_api_requeues_existing_failed_task(self, read_url):
        read_url.side_effect = [
            FeedgrabUnavailable("temporary feedgrab outage"),
            {
                "source_type": "web",
                "source_name": "GitHub",
                "title": "Radar",
                "content": "Radar repository.",
                "url": "https://github.com/Zanetach/radar-claw",
                "id": "repo-manual-retry",
                "extra": {},
            },
        ]
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            queued = handler.api_create_collection_task(
                {"url": "https://github.com/Zanetach/radar-claw", "queue": True}
            )
            process_queued_runs(db_path, limit=1)
            self.assertEqual(handler.api_run_detail(queued["id"])["status"], "failed")

            retry = handler.api_run_retry(queued["id"], {"queue": True})
            self.assertEqual(retry["status"], "queued")
            process_queued_runs(db_path, limit=1)

            self.assertEqual(handler.api_run_detail(queued["id"])["status"], "success")

    @patch("crawler.web.read_url")
    def test_batch_url_collection_creates_child_tasks_and_worker_updates_parent(self, read_url):
        def fake_read_url(url):
            return {
                "source_type": "web",
                "source_name": "GitHub",
                "title": f"Page {url[-1]}",
                "content": f"Content from {url}",
                "url": url,
                "id": f"page-{url[-1]}",
                "extra": {},
            }

        read_url.side_effect = fake_read_url
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            parent = handler.api_create_collection_task(
                {
                    "urls": [
                        "https://example.com/page1",
                        "https://example.com/page2",
                    ],
                    "platform": "web",
                    "queue": True,
                }
            )

            self.assertEqual(parent["source_type"], "batch")
            self.assertEqual(parent["status"], "queued")
            self.assertEqual(len(parent["children"]), 2)
            self.assertEqual({child["status"] for child in parent["children"]}, {"queued"})

            processed = process_queued_runs(db_path, limit=5)

            self.assertEqual(processed["processed"], 2)
            refreshed_parent = handler.api_run_detail(parent["id"])
            self.assertEqual(refreshed_parent["status"], "success")
            self.assertEqual(refreshed_parent["saved_count"], 2)
            self.assertEqual(len(refreshed_parent["children"]), 2)
            self.assertEqual({child["status"] for child in refreshed_parent["children"]}, {"success"})
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS count FROM source_contents").fetchone()["count"],
                2,
            )

    def test_cancel_batch_collection_marks_queued_children_cancelled(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            parent = handler.api_create_collection_task(
                {
                    "urls": [
                        "https://example.com/page1",
                        "https://example.com/page2",
                    ],
                    "platform": "web",
                    "queue": True,
                }
            )
            updated = handler.api_update_run_status(parent["id"], {"status": "cancelled"})

            self.assertEqual(updated["status"], "cancelled")
            self.assertEqual({child["status"] for child in updated["children"]}, {"cancelled"})
            processed = process_queued_runs(db_path, limit=5)
            self.assertEqual(processed["processed"], 0)

    def test_account_source_queue_splits_imported_accounts_into_child_tasks(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            upsert_accounts(
                conn,
                [
                    source_account("OpenAI", "OpenAI"),
                    source_account("Anthropic", "Anthropic"),
                ],
            )
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            parent = handler.api_create_collection_task(
                {
                    "platform": "x",
                    "category": "AI",
                    "mode": "beeclaw:x_rss",
                    "queue": True,
                    "limit": 2,
                }
            )

            self.assertEqual(parent["source_type"], "batch")
            self.assertEqual(parent["status"], "queued")
            self.assertEqual(len(parent["children"]), 2)
            self.assertEqual({child["source_type"] for child in parent["children"]}, {"account"})
            child_params = [child["params"] for child in parent["children"]]
            self.assertEqual({params["accountId"] for params in child_params}, {1, 2})

    def test_xmcp_pressure_test_creates_bounded_batch_task(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            result = handler.api_xmcp_pressure_test(
                {
                    "handles": ["@OpenAI", "@Anthropic", "@elonmusk"],
                    "maxAccounts": 2,
                    "maxResults": 3,
                    "queue": True,
                    "execute": True,
                }
            )

            self.assertEqual(result["mode"], "beeclaw:x_mcp")
            self.assertEqual(result["maxAccounts"], 2)
            self.assertEqual(result["maxResults"], 3)
            self.assertEqual(result["estimatedApiCalls"], 4)
            self.assertEqual(result["run"]["source_type"], "batch")
            self.assertEqual(len(result["run"]["children"]), 2)
            self.assertEqual({child["params"]["mode"] for child in result["run"]["children"]}, {"beeclaw:x_mcp"})

    @patch("crawler.web.backend_mcp_call_tool")
    def test_x_keyword_collection_uses_xmcp_recent_search(self, backend_mcp_call_tool):
        backend_mcp_call_tool.return_value = {
            "data": [
                {
                    "id": "x-search-1",
                    "text": "AI tools launch",
                    "created_at": "2026-05-14T00:00:00Z",
                    "lang": "en",
                    "public_metrics": {"impression_count": 100, "like_count": 10, "reply_count": 2, "retweet_count": 1},
                }
            ]
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task(
                {"platform": "x", "query": "AI tools", "mode": "beeclaw:x_mcp", "maxResults": 5}
            )

            self.assertEqual(run["saved_count"], 1)
            self.assertEqual(run["contents"][0]["provider"], "beeclaw:x")
            self.assertEqual(run["agent_feedback"]["summary"]["execution_backends"], ["x_mcp"])
            self.assertEqual(run["agent_feedback"]["summary"]["providers"], ["beeclaw:x"])
            backend_mcp_call_tool.assert_called_once()
            self.assertEqual(backend_mcp_call_tool.call_args.kwargs["integration"], "x-mcp")
            self.assertEqual(backend_mcp_call_tool.call_args.kwargs["tool_name"], "searchPostsRecent")
            self.assertEqual(backend_mcp_call_tool.call_args.kwargs["arguments"]["query"], "AI tools")

    @patch("crawler.web.read_url", side_effect=AssertionError("x profile account task must not use URL reader"))
    @patch("crawler.web.build_provider")
    def test_x_profile_url_account_task_uses_account_provider_not_url_reader(self, build_provider, read_url):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            class Provider:
                def fetch(self, account, *, max_results):
                    self.account = dict(account)
                    return FetchResult(
                        account_id=account["id"],
                        platform="x",
                        items=[
                            ContentItem(
                                platform="x",
                                original_content_id="profile-url-1",
                                title=None,
                                text="profile url routed through account provider",
                                published_at=None,
                                url="https://x.com/elonmusk/status/profile-url-1",
                                view_count=None,
                                like_count=None,
                                comment_count=None,
                                share_count=None,
                                media_type="post",
                                language=None,
                                raw_payload={"source": "beeclaw:x_mcp", "provider_backend": "feedgrab:x_mcp"},
                            )
                        ],
                    )

            provider = Provider()
            build_provider.return_value = provider
            run = handler.api_create_collection_task(
                {
                    "sourceType": "account",
                    "platform": "x",
                    "identifier": "https://www.x.com/elonmusk",
                    "url": "https://www.x.com/elonmusk",
                    "mode": "beeclaw:x_mcp",
                    "maxResults": 5,
                }
            )

            read_url.assert_not_called()
            build_provider.assert_called_once_with("x", mode="beeclaw:x_mcp")
            self.assertEqual(run["source_type"], "account")
            self.assertEqual(run["saved_count"], 1)
            self.assertEqual(provider.account["account_handle"], "elonmusk")
            self.assertEqual(run["contents"][0]["provider"], "beeclaw:x")

    @patch("crawler.web.read_url", side_effect=AssertionError("x profile url must be normalized to account task"))
    @patch("crawler.web.build_provider")
    def test_x_profile_url_only_task_is_normalized_to_account_provider(self, build_provider, read_url):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            class Provider:
                def fetch(self, account, *, max_results):
                    return FetchResult(
                        account_id=account["id"],
                        platform="x",
                        items=[
                            ContentItem(
                                platform="x",
                                original_content_id="profile-url-only-1",
                                title=None,
                                text="profile url only routed through account provider",
                                published_at=None,
                                url="https://x.com/elonmusk/status/profile-url-only-1",
                                view_count=None,
                                like_count=None,
                                comment_count=None,
                                share_count=None,
                                media_type="post",
                                language=None,
                                raw_payload={"source": "beeclaw:x_mcp", "provider_backend": "feedgrab:x_mcp"},
                            )
                        ],
                    )

            build_provider.return_value = Provider()
            run = handler.api_create_collection_task(
                {
                    "platform": "x",
                    "url": "https://www.x.com/elonmusk",
                    "mode": "beeclaw:x_mcp",
                    "maxResults": 5,
                }
            )

            read_url.assert_not_called()
            self.assertEqual(run["source_type"], "account")
            self.assertEqual(run["saved_count"], 1)
            self.assertEqual(run["contents"][0]["provider"], "beeclaw:x")

    @patch("crawler.web.build_provider")
    def test_running_cancel_stops_account_loop_and_finish_does_not_override(self, build_provider):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            upsert_accounts(conn, [source_account("OpenAI", "OpenAI"), source_account("Anthropic", "Anthropic")])
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            rows = conn.execute("SELECT * FROM source_accounts ORDER BY id").fetchall()
            run_id = handler.create_run(
                conn,
                body={"platform": "x", "mode": "beeclaw:x_rss"},
                source_type="file",
                input_label="cancel-test",
            )
            calls = []

            class CancellingProvider:
                def fetch(self, account, *, max_results):
                    calls.append(account["account_name"])
                    handler.api_update_run_status(run_id, {"status": "cancelled", "message": "manual stop"})
                    return FetchResult(
                        account_id=account["id"],
                        platform="x",
                        items=[
                            ContentItem(
                                platform="x",
                                original_content_id="cancel-one",
                                title=None,
                                text="first",
                                published_at=None,
                                url="https://x.com/OpenAI/status/cancel-one",
                                view_count=None,
                                like_count=None,
                                comment_count=None,
                                share_count=None,
                                media_type="post",
                                language=None,
                                raw_payload={"source": "beeclaw:x_rss"},
                            )
                        ],
                    )

            build_provider.return_value = CancellingProvider()
            report = handler.run_accounts(conn, rows=rows, body={"mode": "beeclaw:x_rss"}, run_id=run_id)
            handler.finish_run(conn, run_id, report)

            detail = handler.api_run_detail(run_id)
            self.assertEqual(detail["status"], "cancelled")
            self.assertEqual(report["successes"], 1)
            self.assertEqual(calls, ["OpenAI"])

    def test_filter_run_result_removes_browser_reposts_when_retweets_excluded(self):
        handler = object.__new__(RadarAdminHandler)
        result = FetchResult(
            account_id=1,
            platform="x",
            items=[
                ContentItem(
                    platform="x",
                    original_content_id="repost-1",
                    title=None,
                    text="Grok 4.3 is next level.",
                    published_at=None,
                    url="https://x.com/AdamLowisz/status/repost-1",
                    view_count=None,
                    like_count=None,
                    comment_count=None,
                    share_count=None,
                    media_type="post",
                    language=None,
                    raw_payload={
                        "source": "x_browser_session",
                        "author_username": "AdamLowisz",
                        "requested_handle": "elonmusk",
                        "referenced_tweets": [{"type": "retweeted", "id": "repost-1"}],
                    },
                ),
                ContentItem(
                    platform="x",
                    original_content_id="own-1",
                    title=None,
                    text="Mars update",
                    published_at=None,
                    url="https://x.com/elonmusk/status/own-1",
                    view_count=None,
                    like_count=None,
                    comment_count=None,
                    share_count=None,
                    media_type="post",
                    language=None,
                    raw_payload={"source": "x_browser_session", "referenced_tweets": []},
                ),
            ],
        )

        filtered = handler.filter_run_result(result, {"includeRetweets": False, "includeOriginal": True})

        self.assertEqual([item.original_content_id for item in filtered.items], ["own-1"])

    @patch("crawler.web.search_beeclaw_xhs_keyword")
    def test_agent_chat_xhs_keyword_collects_search_results(self, search_xhs_keyword):
        search_xhs_keyword.return_value = {
            "total": 1,
            "query": "AI 工具",
            "notes": [
                {
                    "id": "xhs-note-1",
                    "title": "AI 工具清单",
                    "content": "这是一条小红书 AI 工具笔记。",
                    "url": "https://www.xiaohongshu.com/explore/xhs-note-1",
                    "author": "小红书作者",
                    "likes": 120,
                    "comments": 8,
                    "images": ["https://example.com/xhs.jpg"],
                    "date": "2026-05-13",
                }
            ],
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            result = handler.api_agent_chat(
                {
                    "message": "采集小红书上关于 AI 工具 的热门笔记，保留图片",
                    "execute": True,
                }
            )

            self.assertIn("保存 1 条", result["reply"])
            row = conn.execute("SELECT platform, provider, title, original_text, like_count, raw_payload_json FROM source_contents").fetchone()
            self.assertEqual(row["platform"], "xhs")
            self.assertEqual(row["provider"], "beeclaw:xhs")
            self.assertIn('"provider_backend": "feedgrab:xhs_search"', row["raw_payload_json"])
            self.assertEqual(row["title"], "AI 工具清单")
            self.assertEqual(row["original_text"], "这是一条小红书 AI 工具笔记。")
            self.assertEqual(row["like_count"], 120)

    @patch("crawler.providers.http_text", return_value=XGO_RSS)
    def test_collection_task_x_rss_handle_collects_without_token(self, http_text):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_create_collection_task(
                {
                    "identifier": "@OpenAI",
                    "platform": "x",
                    "mode": "feedgrab:x_rss",
                    "maxResults": 5,
                }
            )

            http_text.assert_called_once_with("https://api.xgo.ing/rss/user/OpenAI")
            self.assertEqual(run["saved_count"], 1)
            self.assertEqual(run["contents"][0]["provider"], "beeclaw:x")
            self.assertEqual(run["contents"][0]["original_content_id"], "2052845770056073216")
            self.assertEqual(run["agent_feedback"]["content_ids"], [run["contents"][0]["id"]])
            self.assertEqual(run["agent_feedback"]["summary"]["providers"], ["beeclaw:x"])
            self.assertEqual(run["agent_feedback"]["summary"]["execution_backends"], ["x_rss"])
            self.assertIn("metrics_incomplete", run["agent_feedback"]["warnings"])

    @patch("crawler.web.search_feedgrab_xhs_keyword", side_effect=AssertionError("feedgrab fallback should not be used"))
    @patch("crawler.web.backend_mcp_call_tool")
    def test_xhs_keyword_collection_uses_platform_gateway_mcp(self, backend_mcp_call_tool, _feedgrab_search):
        backend_mcp_call_tool.return_value = {
            "notes": [
                {
                    "id": "xhs-gateway-1",
                    "title": "AI 工具清单",
                    "content": "来自平台 MCP Gateway 的小红书笔记。",
                    "url": "https://www.xiaohongshu.com/explore/xhs-gateway-1",
                    "likes": 99,
                    "images": ["https://example.com/xhs.jpg"],
                }
            ]
        }
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            with patch.dict(
                os.environ,
                {
                    "RADAR_BACKEND_MCP_MODE": "platform_gateway",
                    "PLATFORM_MCP_GATEWAY_URL": "http://gateway.local/mcp",
                },
            ):
                run = handler.api_create_collection_task(
                    {
                        "platform": "xhs",
                        "query": "AI 工具",
                        "mode": "beeclaw",
                        "maxResults": 5,
                    }
                )

            self.assertEqual(run["saved_count"], 1)
            self.assertEqual(run["contents"][0]["provider"], "beeclaw:xhs")
            self.assertEqual(run["agent_feedback"]["summary"]["execution_backends"], ["xiaohongshu-mcp:search_notes"])
            backend_mcp_call_tool.assert_called_once()
            self.assertEqual(backend_mcp_call_tool.call_args.kwargs["integration"], "xiaohongshu-mcp")
            self.assertEqual(backend_mcp_call_tool.call_args.kwargs["tool_name"], "search_notes")
            self.assertEqual(backend_mcp_call_tool.call_args.kwargs["arguments"]["query"], "AI 工具")

    def test_agent_feedback_exposes_x_backend_attempts_and_completeness(self):
        handler = object.__new__(RadarAdminHandler)
        feedback = handler.agent_feedback_for_run(
            {
                "id": "run-x-auto",
                "status": "success",
                "platform": "x",
                "mode": "auto",
                "input_label": "@OpenAI",
                "saved_count": 1,
                "failure_count": 0,
                "media_downloaded": 0,
                "media_failed": 0,
                "params": {"downloadVideos": True},
                "report": {"details": []},
                "contents": [
                    {
                        "id": 1,
                        "title": None,
                        "original_text": "Hello",
                        "text": "Hello",
                        "url": "https://x.com/OpenAI/status/1",
                        "provider": "beeclaw:x",
                        "raw_payload_json": json.dumps(
                            {
                                "source": "beeclaw:x",
                                "provider_backend": "x_rss",
                                "selection_reason": "X MCP/API 不可用，降级到免费 RSS；指标和视频可能不完整。",
                                "backend_attempts": [
                                    {"backend": "x_mcp", "status": "failed", "error": "credits_depleted"},
                                    {"backend": "x_rss", "status": "success"},
                                ],
                                "metrics_complete": False,
                                "media_complete": False,
                            },
                            ensure_ascii=False,
                        ),
                        "media_assets_json": "[]",
                        "view_count": None,
                        "like_count": None,
                        "comment_count": None,
                        "share_count": None,
                    }
                ],
            }
        )

        self.assertEqual(feedback["backend_attempts"][0]["backend"], "x_mcp")
        self.assertEqual(feedback["summary"]["execution_backends"], ["x_rss"])
        self.assertFalse(feedback["summary"]["metrics_complete"])
        self.assertFalse(feedback["summary"]["media_complete"])
        self.assertIn("metrics_incomplete", feedback["warnings"])
        self.assertIn("video_metadata_incomplete", feedback["warnings"])

    def test_agent_feedback_deduplicates_backend_attempts_across_contents(self):
        handler = object.__new__(RadarAdminHandler)
        attempts = [
            {"backend": "x_mcp", "status": "failed", "error": "credits_depleted", "status_code": 402},
            {"backend": "x_rss", "status": "success"},
        ]
        contents = []
        for content_id in [1, 2]:
            contents.append(
                {
                    "id": content_id,
                    "title": f"Post {content_id}",
                    "original_text": f"Post body {content_id}",
                    "text": f"Post body {content_id}",
                    "url": f"https://x.com/OpenAI/status/{content_id}",
                    "provider": "beeclaw:x",
                    "raw_payload_json": json.dumps(
                        {
                            "source": "beeclaw:x",
                            "provider_backend": "x_rss",
                            "backend_attempts": attempts,
                        }
                    ),
                    "media_assets_json": "[]",
                    "view_count": None,
                    "like_count": None,
                    "comment_count": None,
                    "share_count": None,
                }
            )

        feedback = handler.agent_feedback_for_run(
            {
                "id": "run-x-auto",
                "status": "success",
                "platform": "x",
                "mode": "auto",
                "input_label": "@OpenAI",
                "saved_count": 2,
                "failure_count": 0,
                "media_downloaded": 0,
                "media_failed": 0,
                "params": {},
                "report": {"details": []},
                "contents": contents,
            }
        )

        self.assertEqual(feedback["backend_attempts"], attempts)

    @patch("crawler.providers.http_text", return_value=XGO_RSS)
    def test_agent_chat_returns_feedback_for_ai_employee(self, _http_text):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            result = handler.api_agent_chat({"message": "免费抓取 @OpenAI 最近7天原创推文", "execute": True})

            self.assertIn("agent_feedback", result)
            self.assertEqual(result["agent_feedback"]["run_id"], result["run"]["id"])
            self.assertEqual(result["reply"], result["agent_feedback"]["message"])
            self.assertIn("保存 1 条", result["reply"])

    def test_handoff_to_organizer_returns_raw_payload_contract(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            upsert_accounts(conn, [sample_account()])
            account_id = conn.execute("SELECT id FROM source_accounts").fetchone()["id"]
            save_fetch_result(
                conn,
                FetchResult(
                    account_id=account_id,
                    platform="x",
                    items=[
                        ContentItem(
                            platform="x",
                            original_content_id="post-2",
                            title="AI update",
                            text="Original text",
                            published_at="2026-05-12T00:00:00Z",
                            url="https://x.com/OpenAI/status/post-2",
                            view_count=100,
                            like_count=10,
                            comment_count=2,
                            share_count=1,
                            media_type="text",
                            language="en",
                            raw_payload={"source": "feedgrab:x_mcp", "id": "post-2"},
                        )
                    ],
                ),
            )
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            content_id = conn.execute("SELECT id FROM source_contents").fetchone()["id"]

            result = handler.api_handoff_to_organizer({"contentIds": [content_id]})

            handoff = result["handoff"]
            self.assertEqual(handoff["handoff_type"], "raw_content_for_organization")
            self.assertEqual(handoff["content_ids"], [content_id])
            self.assertEqual(handoff["items"][0]["provider"], "beeclaw:x")
            self.assertEqual(handoff["items"][0]["original_text"], "Original text")
            organizer_task = result["organizer_task"]
            self.assertEqual(organizer_task["agent"], "内容整理 Agent")
            self.assertEqual(organizer_task["handoff"]["content_ids"], [content_id])
            self.assertEqual(organizer_task["writeback_tool"], "radar_save_organized_content")
            self.assertIn("translated_text_zh", organizer_task["expected_output_per_item"])
            self.assertEqual(result["beemax_task"]["agent"], "内容整理 Agent")

            exported = handler.api_export_raw_dataset({"contentIds": [str(content_id)], "format": ["jsonl"]})
            self.assertEqual(exported["count"], 1)
            self.assertIn('"provider": "beeclaw:x"', exported["dataset_jsonl"])

            markdown = handler.api_export_raw_dataset({"contentIds": [str(content_id)], "format": ["markdown"]})
            self.assertIn("### 原文", markdown["dataset_markdown"])
            self.assertIn("Original text", markdown["dataset_markdown"])

    def test_handoff_to_interaction_agent_returns_raw_payload_contract(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            upsert_accounts(conn, [sample_account()])
            account_id = conn.execute("SELECT id FROM source_accounts").fetchone()["id"]
            save_fetch_result(
                conn,
                FetchResult(
                    account_id=account_id,
                    platform="x",
                    items=[
                        ContentItem(
                            platform="x",
                            original_content_id="post-window-1",
                            title="AI update",
                            text="New model launch with unusually fast replies.",
                            published_at="2026-05-15T08:00:00Z",
                            url="https://x.com/OpenAI/status/post-window-1",
                            view_count=12000,
                            like_count=900,
                            comment_count=180,
                            share_count=70,
                            media_type="text",
                            language="en",
                            raw_payload={"source": "beeclaw:x", "provider_backend": "x_mcp"},
                        )
                    ],
                ),
            )
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            content_id = conn.execute("SELECT id FROM source_contents").fetchone()["id"]

            result = handler.api_handoff_to_interaction_agent(
                {"contentIds": [content_id], "targetChannel": "feishu_table"}
            )

            self.assertEqual(result["interaction_task"]["agent"], "互动建议 Agent")
            handoff = result["handoff"]
            self.assertEqual(handoff["handoff_type"], "raw_content_for_interaction_window")
            self.assertEqual(handoff["content_ids"], [content_id])
            self.assertEqual(handoff["target_channel"], "feishu_table")
            self.assertEqual(handoff["requirements"]["golden_window_score"], True)
            self.assertEqual(handoff["requirements"]["generate_reply"], True)
            self.assertEqual(handoff["items"][0]["metrics"]["comments"], 180)
            self.assertEqual(handoff["items"][0]["source_url"], "https://x.com/OpenAI/status/post-window-1")

    def test_save_list_and_export_interaction_candidates(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            upsert_accounts(conn, [sample_account()])
            account_id = conn.execute("SELECT id FROM source_accounts").fetchone()["id"]
            save_fetch_result(
                conn,
                FetchResult(
                    account_id=account_id,
                    platform="x",
                    items=[
                        ContentItem(
                            platform="x",
                            original_content_id="post-window-1",
                            title="Launch",
                            text="New model launch with unusually fast replies.",
                            published_at="2026-05-15T08:00:00Z",
                            url="https://x.com/OpenAI/status/post-window-1",
                            view_count=12000,
                            like_count=900,
                            comment_count=180,
                            share_count=70,
                            media_type="text",
                            language="en",
                            raw_payload={"source": "beeclaw:x", "provider_backend": "x_mcp"},
                        )
                    ],
                ),
            )
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path
            content_id = conn.execute("SELECT id FROM source_contents").fetchone()["id"]

            saved = handler.api_save_interaction_candidates(
                {
                    "candidates": [
                        {
                            "contentId": content_id,
                            "windowScore": 86,
                            "scoreReason": "发布后评论密度高，适合 2 小时内回复。",
                            "actionType": "reply",
                            "suggestedReply": "这个点值得跟进：真正的窗口不是发布时，而是评论开始分叉时。",
                            "suggestedQuote": "这类发布最适合观察评论区真实需求。",
                            "targetChannel": "feishu_table",
                        }
                    ]
                }
            )

            self.assertEqual(saved["saved"], 1)
            listed = handler.api_interaction_candidates({"status": ["pending"]})
            self.assertEqual(len(listed["items"]), 1)
            candidate = listed["items"][0]
            self.assertEqual(candidate["content_id"], content_id)
            self.assertEqual(candidate["window_score"], 86)
            self.assertEqual(candidate["source_url"], "https://x.com/OpenAI/status/post-window-1")
            self.assertEqual(candidate["target_channel"], "feishu_table")
            self.assertEqual(candidate["status"], "pending")

            exported = handler.api_export_interaction_candidates({"format": ["markdown"]})
            self.assertIn("黄金互动窗口候选", exported["dataset_markdown"])
            self.assertIn("https://x.com/OpenAI/status/post-window-1", exported["dataset_markdown"])
            self.assertIn("真正的窗口不是发布时", exported["dataset_markdown"])

    @patch("crawler.web.build_provider")
    def test_provider_failure_details_include_message_for_agent_feedback(self, build_provider):
        class FailingProvider:
            def fetch(self, account, *, max_results):
                raise ProviderError(
                    "Using SOCKS proxy, but the 'socksio' package is not installed.",
                    error_type="xmcp_error",
                )

        build_provider.return_value = FailingProvider()
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_run_crawl(
                {
                    "sourceType": "account",
                    "identifier": "@OpenAI",
                    "platform": "x",
                    "mode": "feedgrab:x_mcp",
                    "maxResults": 5,
                }
            )

            detail = run["report"]["details"][0]
            self.assertEqual(detail["error"], "xmcp_error")
            self.assertIn("socksio", detail["message"])
            self.assertIn("socksio", run["agent_feedback"]["errors"][0]["message"])

    @patch("crawler.web.build_provider")
    def test_credits_depleted_feedback_is_specific(self, build_provider):
        class FailingProvider:
            def fetch(self, account, *, max_results):
                raise ProviderError(
                    "CreditsDepleted: account does not have any credits.",
                    error_type="credits_depleted",
                    status_code=402,
                )

        build_provider.return_value = FailingProvider()
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "radar.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            init_db(conn)
            handler = object.__new__(RadarAdminHandler)
            handler.db_path = db_path

            run = handler.api_run_crawl(
                {
                    "sourceType": "account",
                    "identifier": "@OpenAI",
                    "platform": "x",
                    "mode": "feedgrab:x_mcp",
                    "maxResults": 5,
                }
            )

            self.assertIn("X API credits 不足", run["agent_feedback"]["message"])
            self.assertEqual(run["agent_feedback"]["errors"][0]["status_code"], 402)


if __name__ == "__main__":
    unittest.main()
