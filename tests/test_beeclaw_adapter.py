import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crawler.beeclaw_adapter import client as client_module
from crawler.beeclaw_adapter.health import provider_catalog
from crawler.beeclaw_adapter import health as health_module
from crawler.beeclaw_adapter.mapper import unified_content_to_item


class BeeclawAdapterTests(unittest.TestCase):
    def test_beeclaw_adapter_import_and_catalog_are_primary(self):
        from crawler.beeclaw_adapter import provider_catalog as beeclaw_provider_catalog

        providers = beeclaw_provider_catalog()
        self.assertTrue(any(item["provider"] == "beeclaw:x" for item in providers))
        self.assertTrue(any(item["provider"] == "beeclaw:xhs" for item in providers))

    def test_legacy_beegrab_provider_names_normalize_to_beeclaw(self):
        from crawler.beeclaw_adapter.platforms import beeclaw_provider_name, normalize_public_provider_mode

        self.assertEqual(beeclaw_provider_name("beegrab:xhs"), "beeclaw:xhs")
        self.assertEqual(beeclaw_provider_name("feedgrab:xhs"), "beeclaw:xhs")
        self.assertEqual(normalize_public_provider_mode("beegrab:x_rss"), "beeclaw:x_rss")

    def test_legacy_feedgrab_adapter_import_still_works(self):
        from crawler.feedgrab_adapter import provider_catalog as legacy_provider_catalog

        self.assertTrue(any(item["provider"] == "beeclaw:xhs" for item in legacy_provider_catalog()))

    def test_legacy_feedgrab_adapter_submodule_imports_still_work(self):
        from crawler.feedgrab_adapter.health import provider_catalog as legacy_provider_catalog
        from crawler.feedgrab_adapter.mapper import unified_content_to_item as legacy_mapper

        self.assertTrue(any(item["provider"] == "beeclaw:x_mcp" for item in legacy_provider_catalog()))
        self.assertIs(legacy_mapper, unified_content_to_item)

    def test_unified_content_dict_maps_to_content_item(self):
        item = unified_content_to_item(
            {
                "source_type": "twitter",
                "source_name": "OpenAI",
                "title": "Launch",
                "content": "A new model launched.",
                "url": "https://x.com/OpenAI/status/123",
                "id": "abc",
                "extra": {
                    "tweet_id": "123",
                    "created_at": "2026-05-13T00:00:00Z",
                    "views": "1000",
                    "likes": 10,
                    "replies": 2,
                    "retweets": 3,
                    "images": ["https://pbs.twimg.com/media/a.jpg"],
                },
            }
        )

        self.assertEqual(item.platform, "x")
        self.assertEqual(item.original_content_id, "123")
        self.assertEqual(item.view_count, 1000)
        self.assertEqual(item.like_count, 10)
        self.assertEqual(item.comment_count, 2)
        self.assertEqual(item.share_count, 3)
        self.assertEqual(item.media_assets[0]["url"], "https://pbs.twimg.com/media/a.jpg")
        self.assertEqual(item.raw_payload["source"], "beeclaw:universal_reader")

    def test_unified_content_preserves_execution_backend(self):
        item = unified_content_to_item(
            {
                "source_type": "web",
                "source_name": "Jina Reader",
                "title": "Example",
                "content": "Readable page body.",
                "url": "https://example.com/article",
                "id": "example-article",
                "extra": {"provider_backend": "Jina Reader"},
            }
        )

        self.assertEqual(item.raw_payload["provider_backend"], "Jina Reader")

    @patch.object(client_module, "_http_text", return_value="# Example Title\n\nReadable page body.")
    def test_read_url_uses_jina_reader_for_web_urls(self, _http_text):
        content = client_module.read_url("https://example.com/article")

        self.assertEqual(content["source_type"], "web")
        self.assertEqual(content["source_name"], "Jina Reader")
        self.assertEqual(content["title"], "Example Title")
        self.assertEqual(content["extra"]["provider_backend"], "Jina Reader")

    @patch.object(client_module.subprocess, "run")
    @patch.object(client_module.shutil, "which")
    def test_read_url_uses_ytdlp_for_youtube_urls(self, which, run):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name == "yt-dlp" else None
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "id": "abc123",
                    "title": "Launch video",
                    "description": "Video description",
                    "webpage_url": "https://www.youtube.com/watch?v=abc123",
                    "view_count": 1000,
                    "like_count": 20,
                    "comment_count": 3,
                    "thumbnails": [{"url": "https://img.youtube.com/abc123.jpg"}],
                }
            ),
            stderr="",
        )

        content = client_module.read_url("https://www.youtube.com/watch?v=abc123")

        self.assertEqual(content["source_type"], "youtube")
        self.assertEqual(content["source_name"], "yt-dlp")
        self.assertEqual(content["id"], "abc123")
        self.assertEqual(content["extra"]["views"], 1000)
        self.assertEqual(content["extra"]["provider_backend"], "yt-dlp")
        self.assertEqual(content["extra"]["images"], ["https://img.youtube.com/abc123.jpg"])

    @patch.object(client_module.subprocess, "run")
    @patch.object(client_module.shutil, "which")
    def test_read_url_uses_gh_for_github_repo_urls(self, which, run):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name == "gh" else None
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "nameWithOwner": "Zanetach/radar-claw",
                    "description": "Radar data collection tool.",
                    "url": "https://github.com/Zanetach/radar-claw",
                    "stargazerCount": 8,
                    "forkCount": 1,
                    "updatedAt": "2026-05-14T00:00:00Z",
                    "primaryLanguage": {"name": "Python"},
                }
            ),
            stderr="",
        )

        content = client_module.read_url("https://github.com/Zanetach/radar-claw")

        self.assertEqual(content["source_type"], "github")
        self.assertEqual(content["source_name"], "gh")
        self.assertEqual(content["title"], "Zanetach/radar-claw")
        self.assertEqual(content["extra"]["stars"], 8)
        self.assertEqual(content["extra"]["language"], "Python")
        self.assertEqual(content["extra"]["provider_backend"], "gh")

    @patch.object(client_module.subprocess, "run")
    @patch.object(client_module.shutil, "which")
    def test_read_url_uses_xhs_cli_for_xhs_urls(self, which, run):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name == "xhs-cli" else None
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "note_id": "xhs-123",
                    "title": "AI 工具清单",
                    "desc": "这是一篇小红书笔记正文。",
                    "url": "https://www.xiaohongshu.com/explore/xhs-123",
                    "likes": 88,
                    "comments": 9,
                    "images": ["https://sns-img.example/xhs.jpg"],
                }
            ),
            stderr="",
        )

        content = client_module.read_url("https://www.xiaohongshu.com/explore/xhs-123")

        self.assertEqual(content["source_type"], "xhs")
        self.assertEqual(content["source_name"], "xhs-cli")
        self.assertEqual(content["id"], "xhs-123")
        self.assertEqual(content["content"], "这是一篇小红书笔记正文。")
        self.assertEqual(content["extra"]["likes"], 88)
        self.assertEqual(content["extra"]["images"], ["https://sns-img.example/xhs.jpg"])
        self.assertEqual(content["extra"]["provider_backend"], "xhs-cli")
        self.assertEqual(content["extra"]["backend_attempts"], [{"backend": "xhs-cli", "status": "success"}])

    @patch.object(client_module.subprocess, "run")
    @patch.object(client_module.shutil, "which")
    def test_read_url_uses_rdt_cli_for_reddit_urls(self, which, run):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name == "rdt-cli" else None
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "id": "abcde",
                    "title": "AI discussion",
                    "selftext": "A Reddit thread about AI tools.",
                    "permalink": "/r/artificial/comments/abcde/ai_discussion/",
                    "subreddit": "artificial",
                    "score": 128,
                    "num_comments": 34,
                    "url": "https://www.reddit.com/r/artificial/comments/abcde/ai_discussion/",
                }
            ),
            stderr="",
        )

        content = client_module.read_url("https://www.reddit.com/r/artificial/comments/abcde/ai_discussion/")

        self.assertEqual(content["source_type"], "reddit")
        self.assertEqual(content["source_name"], "rdt-cli")
        self.assertEqual(content["id"], "abcde")
        self.assertEqual(content["extra"]["likes"], 128)
        self.assertEqual(content["extra"]["comments"], 34)
        self.assertEqual(content["extra"]["subreddit"], "artificial")
        self.assertEqual(content["extra"]["provider_backend"], "rdt-cli")
        self.assertEqual(content["extra"]["backend_attempts"], [{"backend": "rdt-cli", "status": "success"}])

    @patch.object(
        client_module,
        "_http_text",
        return_value="""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AI Radar Feed</title>
    <link>https://example.com/</link>
    <item>
      <title>New AI Tool</title>
      <link>https://example.com/posts/1</link>
      <guid>post-1</guid>
      <pubDate>Thu, 14 May 2026 08:00:00 GMT</pubDate>
      <description>Tool launch details.</description>
    </item>
    <item>
      <title>Model Update</title>
      <link>https://example.com/posts/2</link>
      <guid>post-2</guid>
    </item>
  </channel>
</rss>""",
    )
    def test_read_url_uses_builtin_rss_parser_for_rss_feeds(self, _http_text):
        content = client_module.read_url("https://example.com/feed.xml")

        self.assertEqual(content["source_type"], "rss")
        self.assertEqual(content["source_name"], "rss_parser")
        self.assertEqual(content["title"], "AI Radar Feed")
        self.assertEqual(content["url"], "https://example.com/feed.xml")
        self.assertIn("New AI Tool", content["content"])
        self.assertEqual(content["extra"]["provider_backend"], "rss_parser")
        self.assertEqual(content["extra"]["backend_attempts"], [{"backend": "rss_parser", "status": "success"}])
        self.assertEqual(content["extra"]["feed_link"], "https://example.com/")
        self.assertEqual(content["extra"]["item_count"], 2)
        self.assertEqual(content["extra"]["items"][0]["id"], "post-1")
        self.assertEqual(content["extra"]["items"][0]["url"], "https://example.com/posts/1")
        self.assertEqual(content["extra"]["items"][0]["published_at"], "Thu, 14 May 2026 08:00:00 GMT")

    @patch.object(
        client_module,
        "_http_text",
        return_value="""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Radar</title>
  <entry>
    <title>Atom Entry</title>
    <id>tag:example.com,2026:entry-1</id>
    <updated>2026-05-14T08:00:00Z</updated>
    <link href="https://example.com/atom/1" />
    <summary>Atom entry summary.</summary>
  </entry>
</feed>""",
    )
    def test_read_url_uses_builtin_rss_parser_for_atom_feeds(self, _http_text):
        content = client_module.read_url("https://example.com/atom")

        self.assertEqual(content["source_type"], "rss")
        self.assertEqual(content["source_name"], "rss_parser")
        self.assertEqual(content["title"], "Atom Radar")
        self.assertEqual(content["extra"]["items"][0]["title"], "Atom Entry")
        self.assertEqual(content["extra"]["items"][0]["url"], "https://example.com/atom/1")

    @patch.object(client_module.shutil, "which", return_value=None)
    def test_read_url_records_fallback_attempts_when_specialized_backend_missing(self, _which):
        async def fake_universal_reader(url):
            return {
                "source_type": "reddit",
                "source_name": "UniversalReader",
                "title": "Fallback thread",
                "content": "Fallback body.",
                "url": url,
                "id": "fallback-thread",
                "extra": {},
            }

        with patch.object(client_module, "_read_url_async", side_effect=fake_universal_reader):
            content = client_module.read_url("https://www.reddit.com/r/artificial/comments/abcde/ai_discussion/")

        self.assertEqual(content["extra"]["provider_backend"], "beeclaw:universal_reader")
        self.assertEqual(content["extra"]["backend_attempts"][0]["backend"], "rdt-cli")
        self.assertEqual(content["extra"]["backend_attempts"][0]["status"], "failed")
        self.assertEqual(content["extra"]["backend_attempts"][1], {"backend": "beeclaw:universal_reader", "status": "success"})

    def test_read_url_falls_back_when_specialized_backend_raises_unexpected_error(self):
        async def fake_universal_reader(url):
            return {
                "source_type": "web",
                "source_name": "UniversalReader",
                "title": "Fallback page",
                "content": "Fallback body.",
                "url": url,
                "id": "fallback-page",
                "extra": {},
            }

        with (
            patch.object(client_module, "_read_url_with_backend", side_effect=RuntimeError("jina disconnected")),
            patch.object(client_module, "_read_url_async", side_effect=fake_universal_reader),
        ):
            content = client_module.read_url("https://example.com/article")

        self.assertEqual(content["extra"]["provider_backend"], "beeclaw:universal_reader")
        self.assertEqual(content["extra"]["backend_attempts"][0], {"backend": "Jina Reader", "status": "failed", "error": "jina disconnected"})
        self.assertEqual(content["extra"]["backend_attempts"][1], {"backend": "beeclaw:universal_reader", "status": "success"})

    def test_provider_catalog_includes_beeclaw_xmcp(self):
        providers = provider_catalog()
        self.assertTrue(any(item["provider"] == "beeclaw:x_mcp" for item in providers))
        x_provider = next(item for item in providers if item["provider"] == "beeclaw:x")
        self.assertEqual(
            x_provider["backends"],
            ["x_mcp", "x_api", "x_rss", "twitter-cli", "browser_session"],
        )

    def test_provider_catalog_lists_beeclaw_url_platforms(self):
        providers = provider_catalog()
        platforms = {item["platform"] for item in providers if str(item["provider"]).startswith("beeclaw:")}

        self.assertTrue(
            {
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
            }.issubset(platforms)
        )

    def test_provider_catalog_exposes_backend_hierarchy_for_key_platforms(self):
        providers = {item["provider"]: item for item in provider_catalog()}

        self.assertEqual(providers["beeclaw:youtube"]["backends"], ["yt-dlp", "youtube_api", "rss"])
        self.assertEqual(providers["beeclaw:xhs"]["backends"], ["xiaohongshu-mcp", "xhs-cli", "universal_reader"])
        self.assertEqual(providers["beeclaw:reddit"]["backends"], ["rdt-cli", "reddit_api", "universal_reader"])
        self.assertEqual(providers["beeclaw:github"]["backends"], ["gh", "github_api", "universal_reader"])
        self.assertEqual(providers["beeclaw:web"]["backends"], ["Jina Reader", "universal_reader"])
        self.assertEqual(providers["beeclaw:rss"]["backends"], ["rss_parser", "universal_reader"])

    @patch.object(health_module, "_http_probe", return_value={"reachable": True, "message": "ok"})
    @patch.object(health_module, "_installed_version", return_value="1.0.0")
    @patch.object(health_module.shutil, "which")
    def test_feedgrab_health_reports_optional_backend_tools(self, which, _version, _probe):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name in {"yt-dlp", "gh"} else None

        health = health_module.feedgrab_health()

        self.assertTrue(health["backend_health"]["yt-dlp"]["installed"])
        self.assertTrue(health["backend_health"]["gh"]["installed"])
        self.assertTrue(health["backend_health"]["rss_parser"]["installed"])
        self.assertFalse(health["backend_health"]["xhs-cli"]["installed"])
        self.assertFalse(health["backend_health"]["rdt-cli"]["installed"])


if __name__ == "__main__":
    unittest.main()
