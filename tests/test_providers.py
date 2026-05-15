import os
import unittest
from unittest.mock import Mock, patch

from crawler.models import ContentItem, FetchResult
from crawler.providers import (
    ProviderError,
    WebBridgeClient,
    XApiProvider,
    XBrowserSessionProvider,
    XMcpXProvider,
    XRssProvider,
    YouTubeRssProvider,
    build_provider,
    normalize_provider_mode,
    provider_mode_capabilities,
)
from crawler.x_intel import parse_bestblogs_opml


YOUTUBE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>abc123</yt:videoId>
    <title>Example video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
    <published>2026-05-03T00:00:00+00:00</published>
    <media:group>
      <media:description>Example description</media:description>
      <media:thumbnail url="https://img.youtube.com/vi/abc123/hqdefault.jpg"/>
    </media:group>
  </entry>
</feed>
"""

XGO_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>OpenAI(@OpenAI)</title>
    <item>
      <title>Example tweet</title>
      <link>https://x.com/OpenAI/status/2052845770056073216</link>
      <guid>https://x.com/OpenAI/status/2052845770056073216</guid>
      <pubDate>Sat, 09 May 2026 08:54:41 GMT</pubDate>
      <description>&lt;div&gt;Hello&lt;br/&gt;world&lt;img src=&quot;https://pbs.twimg.com/media/test.jpg&quot;/&gt;&lt;/div&gt;&lt;span&gt;💬&lt;/span&gt;&lt;span&gt;17&lt;/span&gt;&lt;span&gt;🔄&lt;/span&gt;&lt;span&gt;4&lt;/span&gt;&lt;span&gt;❤️&lt;/span&gt;&lt;span&gt;111&lt;/span&gt;&lt;span&gt;👀&lt;/span&gt;&lt;span&gt;47397&lt;/span&gt;</description>
    </item>
  </channel>
</rss>
"""

XGO_VIDEO_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>OpenAI(@OpenAI)</title>
    <item>
      <title>Example video tweet</title>
      <link>https://x.com/OpenAI/status/2053939706468139481</link>
      <guid>2053939706468139481</guid>
      <pubDate>Mon, 11 May 2026 20:46:01 GMT</pubDate>
      <description>&lt;div&gt;Video post&lt;video controls&gt;&lt;source src='https://video.twimg.com/amplify_video/abc/vid/avc1/high.mp4?tag=27' type='video/mp4'&gt;&lt;/video&gt;&lt;img src='https://pbs.twimg.com/media/cover.jpg' /&gt;&lt;/div&gt;</description>
    </item>
  </channel>
</rss>
"""


class ProviderTests(unittest.TestCase):
    @patch("crawler.providers.http_text", return_value=YOUTUBE_RSS)
    def test_youtube_rss_provider_without_token(self, _http_text):
        provider = YouTubeRssProvider()
        result = provider.fetch(
            {"id": 1, "account_name": "Example", "account_handle": "UC123"},
            max_results=10,
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].original_content_id, "abc123")
        self.assertIsNone(result.items[0].view_count)
        self.assertEqual(result.items[0].raw_payload["source"], "youtube_rss")
        self.assertEqual(result.items[0].media_assets[0]["thumbnail_url"], "https://img.youtube.com/vi/abc123/hqdefault.jpg")

    @patch(
        "crawler.providers.http_text",
        return_value='{"channelId":"UC1234567890123456789012"}',
    )
    def test_youtube_handle_resolves_to_channel_id(self, _http_text):
        provider = YouTubeRssProvider()
        with patch("crawler.providers.http_text", side_effect=['{"channelId":"UC1234567890123456789012"}', YOUTUBE_RSS]):
            result = provider.fetch(
                {"id": 1, "account_name": "Example", "account_handle": "@Example"},
                max_results=10,
            )
        self.assertEqual(len(result.items), 1)

    @patch("crawler.providers.http_text", return_value=XGO_RSS)
    def test_no_token_x_generates_xgo_rss_url_from_handle(self, http_text):
        provider = build_provider("x", mode="no-token")
        result = provider.fetch({"id": 1, "account_name": "OpenAI", "account_handle": "@OpenAI"}, max_results=10)

        http_text.assert_called_once_with("https://api.xgo.ing/rss/user/OpenAI")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].raw_payload["rss_url"], "https://api.xgo.ing/rss/user/OpenAI")

    @patch("crawler.providers.http_text", return_value=XGO_RSS)
    def test_x_rss_provider_maps_xgo_feed(self, _http_text):
        provider = XRssProvider()
        result = provider.fetch(
            {
                "id": 1,
                "account_name": "OpenAI",
                "account_handle": "OpenAI",
                "account_url": "https://api.xgo.ing/rss/user/example",
            },
            max_results=10,
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].original_content_id, "2052845770056073216")
        self.assertEqual(result.items[0].view_count, 47397)
        self.assertEqual(result.items[0].like_count, 111)
        self.assertIn("Hello", result.items[0].text)
        self.assertEqual(result.items[0].media_assets[0]["url"], "https://pbs.twimg.com/media/test.jpg")

    @patch("crawler.providers.http_text", return_value=XGO_VIDEO_RSS)
    def test_x_rss_provider_extracts_video_and_image_assets(self, _http_text):
        result = XRssProvider().fetch(
            {"id": 1, "account_name": "OpenAI", "account_handle": "OpenAI"},
            max_results=10,
        )

        assets = result.items[0].media_assets
        self.assertEqual(result.items[0].media_type, "video")
        self.assertTrue(any(asset["type"] == "video" and asset["download_url"].startswith("https://video.twimg.com/") for asset in assets))
        self.assertTrue(any(asset["type"] == "image" and asset["url"] == "https://pbs.twimg.com/media/cover.jpg" for asset in assets))

    @patch("crawler.providers.resolve_bestblogs_xgo_url", return_value="https://api.xgo.ing/rss/user/known-id")
    @patch("crawler.providers.http_text")
    def test_x_rss_provider_falls_back_to_bestblogs_url_when_handle_url_404(self, http_text, _resolve):
        http_text.side_effect = [
            ProviderError("not found", error_type="http_error", status_code=404),
            XGO_RSS,
        ]
        provider = XRssProvider()
        result = provider.fetch(
            {"id": 1, "account_name": "OpenAI", "account_handle": "@OpenAI"},
            max_results=10,
        )

        self.assertEqual(
            [call.args[0] for call in http_text.call_args_list],
            ["https://api.xgo.ing/rss/user/OpenAI", "https://api.xgo.ing/rss/user/known-id"],
        )
        self.assertEqual(len(result.items), 1)

    def test_bestblogs_opml_parser_extracts_handle_and_rss_url(self):
        accounts = parse_bestblogs_opml(
            '<outline text="OpenAI(@OpenAI)" xmlUrl="https://api.xgo.ing/rss/user/abc" />'
        )
        self.assertEqual(accounts[0].display_name, "OpenAI")
        self.assertEqual(accounts[0].handle, "OpenAI")
        self.assertEqual(accounts[0].rss_url, "https://api.xgo.ing/rss/user/abc")

    def test_api_mode_requires_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError) as ctx:
                build_provider("x", mode="api")
        self.assertEqual(ctx.exception.error_type, "missing_credentials")

    def test_browser_session_x_reports_unavailable_webbridge(self):
        provider = build_provider("x", mode="browser-session")
        with patch("crawler.providers.webbridge_status", return_value={"reachable": False, "error": "down"}):
            with self.assertRaises(ProviderError) as ctx:
                provider.fetch({"id": 1, "account_name": "DonaldJTrump"}, max_results=10)
        self.assertEqual(ctx.exception.error_type, "webbridge_unavailable")

    def test_chrome_session_alias_uses_browser_provider(self):
        provider = build_provider("x", mode="chrome-session")
        with patch("crawler.providers.webbridge_status", return_value={"reachable": False, "error": "down"}):
            with self.assertRaises(ProviderError) as ctx:
                provider.fetch({"id": 1, "account_name": "elonmusk"}, max_results=10)
        self.assertEqual(ctx.exception.error_type, "webbridge_unavailable")

    def test_browser_session_marks_profile_reposts_for_filtering(self):
        provider = XBrowserSessionProvider()
        provider.client = Mock()
        provider.client.base_url = "http://127.0.0.1:10086"
        provider.client.evaluate_json.return_value = {
            "items": [
                {
                    "id": "repost-1",
                    "text": "Grok 4.3 is next level.",
                    "url": "https://x.com/AdamLowisz/status/repost-1",
                    "raw_text": "Elon Musk reposted\nAdam Lowisz\n@AdamLowisz\nGrok 4.3 is next level.",
                },
                {
                    "id": "own-1",
                    "text": "Mars update",
                    "url": "https://x.com/elonmusk/status/own-1",
                    "raw_text": "Elon Musk\n@elonmusk\nMars update",
                },
            ]
        }

        with patch("crawler.providers.webbridge_status", return_value={"reachable": True}):
            result = provider.fetch({"id": 1, "account_name": "elonmusk", "account_handle": "elonmusk"}, max_results=10)

        self.assertEqual(result.items[0].raw_payload["author_username"], "AdamLowisz")
        self.assertEqual(result.items[0].raw_payload["referenced_tweets"], [{"type": "retweeted", "id": "repost-1"}])
        self.assertEqual(result.items[1].raw_payload["author_username"], "elonmusk")
        self.assertEqual(result.items[1].raw_payload["referenced_tweets"], [])

    def test_provider_mode_aliases_are_normalized(self):
        self.assertEqual(normalize_provider_mode("chrome"), "chrome-session")
        self.assertEqual(normalize_provider_mode("mcp"), "xmcp")
        self.assertEqual(normalize_provider_mode("beeclaw:x"), "beeclaw:x")
        self.assertEqual(normalize_provider_mode("feedgrab:x"), "beeclaw:x")
        self.assertEqual(normalize_provider_mode("beeclaw:x_api"), "api")
        self.assertEqual(normalize_provider_mode("feedgrab:x_api"), "api")
        self.assertEqual(normalize_provider_mode("feedgrab:xmcp"), "beeclaw:x_mcp")
        self.assertEqual(normalize_provider_mode("beeclaw:xmcp"), "beeclaw:x_mcp")
        self.assertEqual(normalize_provider_mode("feedgrab:x_rss"), "beeclaw:x_rss")
        self.assertEqual(normalize_provider_mode("beeclaw:x_rss"), "beeclaw:x_rss")
        self.assertEqual(normalize_provider_mode("rss"), "x-rss")

    def test_provider_capabilities_expose_platform_matrix(self):
        capabilities = provider_mode_capabilities()
        self.assertTrue(capabilities["chrome-session"]["x"])
        self.assertTrue(capabilities["beeclaw:x"]["x"])
        self.assertTrue(capabilities["beeclaw:x_mcp"]["x"])
        self.assertTrue(capabilities["beeclaw:x_rss"]["x"])
        self.assertTrue(capabilities["beeclaw"]["github"])
        self.assertFalse(capabilities["chrome-session"]["youtube"])
        self.assertTrue(capabilities["api"]["instagram"])

    @patch("crawler.providers.read_url")
    def test_beeclaw_url_account_provider_reads_platform_account_url(self, read_url):
        read_url.return_value = {
            "source_type": "web",
            "source_name": "GitHub",
            "title": "Repo",
            "content": "Repository content",
            "url": "https://github.com/Zanetach/radar-claw",
            "id": "repo-1",
            "extra": {},
        }

        result = build_provider("github", mode="beeclaw").fetch(
            {
                "id": 1,
                "platform": "github",
                "account_name": "radar-claw",
                "account_url": "https://github.com/Zanetach/radar-claw",
            },
            max_results=10,
        )

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].platform, "github")
        self.assertEqual(result.items[0].raw_payload["source"], "beeclaw:github")
        self.assertEqual(result.items[0].raw_payload["provider_backend"], "beeclaw:universal_reader")

    @patch.object(XBrowserSessionProvider, "fetch")
    @patch.object(XRssProvider, "fetch")
    @patch.object(XApiProvider, "__init__", return_value=None)
    @patch.object(XApiProvider, "fetch")
    @patch.object(XMcpXProvider, "fetch")
    def test_auto_x_falls_back_from_xmcp_and_api_to_x_rss(self, xmcp_fetch, api_fetch, _api_init, rss_fetch, browser_fetch):
        xmcp_fetch.side_effect = ProviderError("credits depleted", error_type="credits_depleted", status_code=402)
        api_fetch.side_effect = ProviderError("missing token", error_type="missing_credentials")
        rss_fetch.return_value = FetchResult(
            account_id=1,
            platform="x",
            items=[
                ContentItem(
                    platform="x",
                    original_content_id="1",
                    title=None,
                    text="ok",
                    published_at=None,
                    url=None,
                    view_count=None,
                    like_count=None,
                    comment_count=None,
                    share_count=None,
                    media_type="post",
                    language=None,
                    raw_payload={"source": "beeclaw:x_rss", "provider_backend": "xgo_rss"},
                )
            ],
        )

        result = build_provider("x", mode="auto").fetch({"id": 1, "account_name": "elonmusk"}, max_results=2)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].text, "ok")
        self.assertEqual(result.items[0].raw_payload["source"], "beeclaw:x")
        self.assertEqual(result.items[0].raw_payload["provider_backend"], "x_rss")
        self.assertEqual(result.items[0].raw_payload["backend_attempts"][0]["backend"], "x_mcp")
        self.assertEqual(result.items[0].raw_payload["backend_attempts"][-1]["status"], "success")
        self.assertTrue(xmcp_fetch.called)
        self.assertTrue(api_fetch.called)
        self.assertTrue(rss_fetch.called)
        self.assertFalse(browser_fetch.called)

    @patch("crawler.providers.http_post_json")
    def test_webbridge_client_unwraps_stringified_json(self, http_post_json):
        http_post_json.return_value = {"ok": True, "data": {"type": "string", "value": "{\"items\": []}"}}
        client = WebBridgeClient(session="test", base_url="http://127.0.0.1:10086")
        self.assertEqual(client.evaluate_json("JSON.stringify({items: []})"), {"items": []})

    @patch("crawler.providers.mcp_call_tool")
    def test_xmcp_provider_maps_user_posts(self, mcp_call_tool):
        def fake_call(_server_url, tool_name, args):
            if tool_name == "getUsersByUsername":
                self.assertEqual(args["username"], "realDonaldTrump")
                return {"data": {"id": "123", "username": "realDonaldTrump"}}
            if tool_name == "getUsersPosts":
                self.assertEqual(args["id"], "123")
                return {
                    "data": [
                        {
                            "id": "999",
                            "text": "hello from x",
                            "created_at": "2026-05-06T00:00:00Z",
                            "lang": "en",
                            "attachments": {"media_keys": ["3_abc"]},
                            "public_metrics": {
                                "impression_count": 10,
                                "like_count": 2,
                                "reply_count": 1,
                                "retweet_count": 3,
                            },
                        }
                    ],
                    "includes": {
                        "media": [
                            {
                                "media_key": "3_abc",
                                "type": "video",
                                "preview_image_url": "https://pbs.twimg.com/media/abc.jpg",
                                "variants": [
                                    {"content_type": "video/mp4", "bit_rate": 256000, "url": "https://video.twimg.com/low.mp4"},
                                    {"content_type": "video/mp4", "bit_rate": 832000, "url": "https://video.twimg.com/high.mp4"},
                                ],
                            }
                        ]
                    },
                }
            raise AssertionError(tool_name)

        mcp_call_tool.side_effect = fake_call
        provider = XMcpXProvider()
        result = provider.fetch(
            {"id": 1, "account_name": "Donald J. Trump", "account_handle": "realDonaldTrump"},
            max_results=5,
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].url, "https://x.com/realDonaldTrump/status/999")
        self.assertEqual(result.items[0].view_count, 10)
        self.assertEqual(result.items[0].raw_payload["source"], "beeclaw:x")
        self.assertEqual(result.items[0].raw_payload["provider_backend"], "x_mcp")
        self.assertEqual(result.items[0].media_assets[0]["download_url"], "https://video.twimg.com/high.mp4")

    @patch("crawler.providers.mcp_call_tool")
    def test_beeclaw_xmcp_mode_marks_provider_source_and_backend(self, mcp_call_tool):
        def fake_call(_server_url, tool_name, args):
            if tool_name == "getUsersByUsername":
                return {"data": {"id": "123", "username": "OpenAI"}}
            if tool_name == "getUsersPosts":
                return {
                    "data": [
                        {
                            "id": "999",
                            "text": "hello",
                            "created_at": "2026-05-06T00:00:00Z",
                            "public_metrics": {},
                        }
                    ]
                }
            raise AssertionError(tool_name)

        mcp_call_tool.side_effect = fake_call
        provider = build_provider("x", mode="feedgrab:x_mcp")
        result = provider.fetch({"id": 1, "account_name": "OpenAI", "account_handle": "OpenAI"}, max_results=5)
        self.assertEqual(result.items[0].raw_payload["source"], "beeclaw:x")
        self.assertEqual(result.items[0].raw_payload["provider_backend"], "x_mcp")

    @patch("crawler.providers.mcp_call_tool", side_effect=AssertionError("local MCP endpoint should not be used"))
    @patch("crawler.providers.call_platform_mcp_tool")
    def test_xmcp_provider_uses_platform_gateway_when_enabled(self, gateway_call, _local_mcp_call):
        def fake_gateway_call(*, integration, tool, arguments, trace_id=None):
            self.assertEqual(integration, "x-mcp")
            if tool == "getUsersByUsername":
                self.assertEqual(arguments["username"], "OpenAI")
                return {"data": {"id": "123", "username": "OpenAI"}}
            if tool == "getUsersPosts":
                self.assertEqual(arguments["id"], "123")
                return {
                    "data": [
                        {
                            "id": "gateway-1",
                            "text": "from platform gateway",
                            "created_at": "2026-05-06T00:00:00Z",
                            "public_metrics": {"impression_count": 7},
                        }
                    ]
                }
            raise AssertionError(tool)

        gateway_call.side_effect = fake_gateway_call
        with patch.dict(
            os.environ,
            {
                "RADAR_BACKEND_MCP_MODE": "platform_gateway",
                "PLATFORM_MCP_GATEWAY_URL": "http://gateway.local/mcp",
            },
        ):
            provider = build_provider("x", mode="beeclaw:x_mcp")
            result = provider.fetch({"id": 1, "account_name": "OpenAI", "account_handle": "OpenAI"}, max_results=5)

        self.assertEqual(result.items[0].original_content_id, "gateway-1")
        self.assertEqual(result.items[0].raw_payload["source"], "beeclaw:x")
        self.assertEqual(result.items[0].raw_payload["provider_backend"], "x_mcp")
        self.assertEqual(gateway_call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
