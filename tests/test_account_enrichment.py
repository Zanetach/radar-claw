import sqlite3
import unittest

from crawler.account_enrichment import enrich_accounts
from crawler.db import init_db, upsert_accounts
from crawler.models import SourceAccount


class AccountEnrichmentTests(unittest.TestCase):
    def test_enrich_accounts_fills_seed_identifier(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        upsert_accounts(
            conn,
            [
                SourceAccount(
                    category="科技商业领袖",
                    platform="x",
                    account_name="Elon Musk",
                    original_account="X-Elon Musk",
                    official_identity="X / 特斯拉 / SpaceX CEO",
                    radar_name="马斯克科技前沿",
                    radar_persona="",
                    threshold_views=1,
                    threshold_engagement_rate=None,
                    average_views=1,
                    raw_average_views="",
                    raw_threshold="",
                    source_row_number=1,
                )
            ],
        )
        result = enrich_accounts(conn)
        row = conn.execute("SELECT account_handle, account_url FROM source_accounts").fetchone()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(row["account_handle"], "elonmusk")
        self.assertEqual(row["account_url"], "https://x.com/elonmusk")


if __name__ == "__main__":
    unittest.main()
