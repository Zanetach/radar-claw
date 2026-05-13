import unittest

from crawler.markdown_store import safe_path_part, update_frontmatter


class MarkdownStoreTests(unittest.TestCase):
    def test_safe_path_part_removes_invalid_path_chars(self):
        self.assertEqual(safe_path_part('A/B:C* "Name"'), "A-B-C-Name")

    def test_update_frontmatter_changes_status(self):
        markdown = "---\nid: \"a\"\nstatus: \"old\"\n---\nbody"
        updated = update_frontmatter(markdown, {"status": "new"})
        self.assertIn('status: "new"', updated)
        self.assertTrue(updated.endswith("body"))


if __name__ == "__main__":
    unittest.main()
