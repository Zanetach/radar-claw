import sqlite3
import unittest

from crawler.db import init_db, link_run_contents, save_fetch_result, save_fetch_result_with_ids, upsert_accounts
from crawler.models import ContentItem, FetchResult, SourceAccount


def sample_account() -> SourceAccount:
    return SourceAccount(
        category="科技商业领袖",
        platform="youtube",
        account_name="Example Channel",
        original_account="X/YouTube-Example Channel",
        official_identity="Example",
        radar_name="Example Radar",
        radar_persona="Example persona",
        threshold_views=1000,
        threshold_engagement_rate=0.01,
        average_views=2000,
        raw_average_views="YouTube 平台 2000",
        raw_threshold="单条阅读≥1000，互动率≥1%",
        source_row_number=2,
    )


class DatabaseTests(unittest.TestCase):
    def test_upsert_content_is_deduplicated_and_qualified(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        upsert_accounts(conn, [sample_account()])
        account_id = conn.execute("SELECT id FROM source_accounts").fetchone()["id"]

        item = ContentItem(
            platform="youtube",
            original_content_id="video-1",
            title="Video",
            text="Description",
            published_at="2026-05-03T00:00:00Z",
            url="https://www.youtube.com/watch?v=video-1",
            view_count=10_000,
            like_count=200,
            comment_count=20,
            share_count=None,
            media_type="video",
            language="en",
            raw_payload={"id": "video-1"},
            media_assets=[{"type": "video", "url": "https://www.youtube.com/watch?v=video-1"}],
        )
        result = FetchResult(account_id=account_id, platform="youtube", items=[item])
        save_fetch_result(conn, result)
        save_fetch_result(conn, result)

        rows = conn.execute("SELECT * FROM source_contents").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qualification_status"], "qualified")
        self.assertAlmostEqual(rows[0]["engagement_rate"], 0.022)
        self.assertIn("video-1", rows[0]["media_assets_json"])
        self.assertEqual(rows[0]["original_text"], "Description")
        self.assertEqual(rows[0]["translation_status"], "pending")
        media_rows = conn.execute("SELECT * FROM media_assets").fetchall()
        self.assertEqual(len(media_rows), 1)
        self.assertEqual(media_rows[0]["content_id"], rows[0]["id"])
        self.assertIsNone(media_rows[0]["provider"])
        self.assertEqual(media_rows[0]["media_type"], "video")
        self.assertEqual(media_rows[0]["download_status"], "pending")

    def test_default_strategies_are_seeded(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)

        rows = conn.execute("SELECT id, name, mode FROM crawl_strategies ORDER BY id").fetchall()
        ids = {row["id"] for row in rows}
        self.assertIn("x-7d-original-media", ids)
        self.assertIn("x-rss-ai-intel", ids)
        self.assertIn("linkedin-browser-debug", ids)

    def test_old_crawl_runs_table_is_migrated_before_parent_index(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE crawl_runs (
                id TEXT PRIMARY KEY,
                agent_type TEXT NOT NULL DEFAULT 'crawler',
                source_type TEXT NOT NULL,
                platform TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                input_label TEXT,
                params_json TEXT NOT NULL DEFAULT '{}',
                total_accounts INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                saved_count INTEGER NOT NULL DEFAULT 0,
                media_downloaded INTEGER NOT NULL DEFAULT 0,
                media_failed INTEGER NOT NULL DEFAULT 0,
                feishu_written INTEGER NOT NULL DEFAULT 0,
                report_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        init_db(conn)

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crawl_runs)").fetchall()}
        self.assertIn("parent_run_id", columns)
        self.assertIn("batch_index", columns)
        self.assertIn("attempt_count", columns)
        self.assertIn("max_attempts", columns)
        self.assertIn("next_attempt_at", columns)
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(crawl_runs)").fetchall()}
        self.assertIn("idx_crawl_runs_parent", indexes)

    def test_run_content_links_track_exact_task_outputs(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        upsert_accounts(conn, [sample_account()])
        account_id = conn.execute("SELECT id FROM source_accounts").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO crawl_runs (id, source_type, mode, status, params_json, started_at, updated_at)
            VALUES ('run-1', 'account', 'feedgrab:x_mcp', 'running', '{}', '2026-05-13T00:00:00+00:00', '2026-05-13T00:00:00+00:00')
            """
        )

        ids = save_fetch_result_with_ids(
            conn,
            FetchResult(
                account_id=account_id,
                platform="youtube",
                items=[
                    ContentItem(
                        platform="youtube",
                        original_content_id="video-linked",
                        title="Linked Video",
                        text="Description",
                        published_at="2026-05-13T00:00:00Z",
                        url="https://www.youtube.com/watch?v=video-linked",
                        view_count=10_000,
                        like_count=100,
                        comment_count=10,
                        share_count=None,
                        media_type="video",
                        language="en",
                        raw_payload={"source": "feedgrab:youtube"},
                    )
                ],
            ),
        )
        link_run_contents(conn, "run-1", ids)

        links = conn.execute("SELECT run_id, content_id FROM crawl_run_contents").fetchall()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["run_id"], "run-1")
        self.assertEqual(links[0]["content_id"], ids[0])
        content = conn.execute("SELECT provider, raw_payload_json FROM source_contents WHERE id = ?", (ids[0],)).fetchone()
        self.assertEqual(content["provider"], "beeclaw:youtube")
        self.assertIn('"provider_backend": "feedgrab:youtube"', content["raw_payload_json"])


if __name__ == "__main__":
    unittest.main()
