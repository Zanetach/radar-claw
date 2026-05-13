import tempfile
import unittest
from pathlib import Path

from crawler.feishu_store import LocalFeishuStore


class LocalFeishuStoreTests(unittest.TestCase):
    def test_upsert_and_markdown_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFeishuStore(Path(tmp))
            store.upsert_record("content_index", "youtube:1", {"title": "First"})
            store.upsert_record("content_index", "youtube:1", {"title": "Updated"})
            rows = store.read_table("content_index")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Updated")

            location = store.write_markdown(Path("01_待整理/a.md"), "# A")
            self.assertEqual(store.read_markdown(location["markdown_path"]), "# A")
            moved = store.move_markdown(location["markdown_path"], "02_待审核")
            self.assertEqual(store.read_markdown(moved["markdown_path"]), "# A")


if __name__ == "__main__":
    unittest.main()
