import unittest

from crawler.feedgrab_adapter.health import provider_catalog
from crawler.feedgrab_adapter.mapper import unified_content_to_item


class FeedgrabAdapterTests(unittest.TestCase):
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
        self.assertEqual(item.raw_payload["source"], "feedgrab:universal_reader")

    def test_provider_catalog_includes_feedgrab_xmcp(self):
        providers = provider_catalog()
        self.assertTrue(any(item["provider"] == "feedgrab:x_mcp" for item in providers))


if __name__ == "__main__":
    unittest.main()
