import unittest
import json
import sqlite3
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import urlopen

from crawler.db import init_db, save_fetch_result, upsert_accounts
from crawler.models import ContentItem, FetchResult, SourceAccount
from crawler.providers import ProviderError
from crawler.web import RadarAdminHandler, infer_platform_from_url, parse_chat_prompt
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


class WebChatTests(unittest.TestCase):
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

    def test_free_prompt_uses_feedgrab_x_rss(self):
        task = parse_chat_prompt("免费抓取 @OpenAI 最近7天原创推文，保留图片")
        self.assertEqual(task["mode"], "feedgrab:x_rss")
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
        self.assertEqual(task["mode"], "feedgrab")

    def test_feedgrab_platform_url_inference_covers_supported_media(self):
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
        self.assertEqual(task["mode"], "feedgrab")

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
    def test_collection_task_url_uses_feedgrab_and_saves_raw_content(self, read_url):
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
            self.assertEqual(row["provider"], "feedgrab:universal_reader")
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
    def test_agent_chat_facebook_url_collects_via_feedgrab_and_saves_raw_content(self, read_url):
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
            self.assertEqual(row["provider"], "feedgrab:universal_reader")
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
            self.assertEqual(run["agent_feedback"]["top_contents"][0]["provider"], "feedgrab:bilibili")
            self.assertEqual(run["agent_feedback"]["top_contents"][0]["execution_backend"], "feedgrab:universal_reader")
            row = conn.execute("SELECT platform, provider, media_type, media_assets_json FROM source_contents").fetchone()
            self.assertEqual(row["platform"], "bilibili")
            self.assertEqual(row["provider"], "feedgrab:bilibili")
            self.assertEqual(row["media_type"], "video")
            self.assertIn("video.mp4", row["media_assets_json"])

    @patch("crawler.web.search_feedgrab_xhs_keyword")
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
            row = conn.execute("SELECT platform, title, original_text, like_count FROM source_contents").fetchone()
            self.assertEqual(row["platform"], "xhs")
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
            self.assertEqual(run["contents"][0]["provider"], "xgo_rss")
            self.assertEqual(run["contents"][0]["original_content_id"], "2052845770056073216")
            self.assertEqual(run["agent_feedback"]["content_ids"], [run["contents"][0]["id"]])

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
            self.assertEqual(handoff["items"][0]["provider"], "feedgrab:x_mcp")
            self.assertEqual(handoff["items"][0]["original_text"], "Original text")
            organizer_task = result["organizer_task"]
            self.assertEqual(organizer_task["agent"], "内容整理 Agent")
            self.assertEqual(organizer_task["handoff"]["content_ids"], [content_id])
            self.assertEqual(organizer_task["writeback_tool"], "radar_save_organized_content")
            self.assertIn("translated_text_zh", organizer_task["expected_output_per_item"])
            self.assertEqual(result["beemax_task"]["agent"], "内容整理 Agent")

            exported = handler.api_export_raw_dataset({"contentIds": [str(content_id)], "format": ["jsonl"]})
            self.assertEqual(exported["count"], 1)
            self.assertIn('"provider": "feedgrab:x_mcp"', exported["dataset_jsonl"])

            markdown = handler.api_export_raw_dataset({"contentIds": [str(content_id)], "format": ["markdown"]})
            self.assertIn("### 原文", markdown["dataset_markdown"])
            self.assertIn("Original text", markdown["dataset_markdown"])

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
