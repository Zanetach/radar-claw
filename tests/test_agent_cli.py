import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


def run_cli(argv):
    from crawler import agent_cli

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = agent_cli.main(argv)
    return code, buffer.getvalue()


class BeeclawAgentCliTests(unittest.TestCase):
    def test_chat_posts_instruction_to_agent_chat_api(self):
        from crawler import agent_cli

        with patch.object(agent_cli, "_request") as request:
            request.return_value = {
                "reply": "采集完成：保存 1 条，失败 0 个。",
                "agent_feedback": {"message": "采集完成：保存 1 条，失败 0 个。"},
            }

            code, output = run_cli(["chat", "采集", "@OpenAI", "--json"])

        self.assertEqual(code, 0)
        request.assert_called_once_with(
            "POST",
            "/api/agent/chat",
            {"message": "采集 @OpenAI", "execute": True},
            base_url="http://127.0.0.1:8780",
        )
        self.assertEqual(json.loads(output)["reply"], "采集完成：保存 1 条，失败 0 个。")

    def test_collect_url_posts_collection_task_payload(self):
        from crawler import agent_cli

        with patch.object(agent_cli, "_request") as request:
            request.return_value = {"id": "crawl-rss", "status": "success", "saved_count": 2}

            code, output = run_cli(
                [
                    "collect",
                    "--url",
                    "https://example.com/feed.xml",
                    "--platform",
                    "rss",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        method, path, payload = request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/collection-tasks"))
        self.assertEqual(payload["sourceType"], "url")
        self.assertEqual(payload["url"], "https://example.com/feed.xml")
        self.assertEqual(payload["platform"], "rss")
        self.assertEqual(payload["mode"], "auto")
        self.assertEqual(json.loads(output)["id"], "crawl-rss")

    def test_collect_urls_file_passes_batch_urls_and_queue(self):
        from crawler import agent_cli

        with tempfile.TemporaryDirectory() as tmp:
            urls_file = Path(tmp) / "urls.txt"
            urls_file.write_text("https://example.com/a\nhttps://example.com/b\n", encoding="utf-8")
            with patch.object(agent_cli, "_request") as request:
                request.return_value = {"id": "crawl-batch", "source_type": "batch"}

                code, _output = run_cli(
                    [
                        "collect",
                        "--urls-file",
                        str(urls_file),
                        "--platform",
                        "web",
                        "--queue",
                    ]
                )

        self.assertEqual(code, 0)
        _method, _path, payload = request.call_args.args
        self.assertEqual(payload["sourceType"], "url")
        self.assertEqual(payload["urls"], "https://example.com/a\nhttps://example.com/b")
        self.assertTrue(payload["queue"])

    def test_task_get_calls_collection_task_detail_endpoint(self):
        from crawler import agent_cli

        with patch.object(agent_cli, "_request") as request:
            request.return_value = {"id": "crawl-1", "status": "success"}

            code, output = run_cli(["task", "get", "crawl-1", "--json"])

        self.assertEqual(code, 0)
        request.assert_called_once_with(
            "GET",
            "/api/collection-tasks/crawl-1",
            None,
            base_url="http://127.0.0.1:8780",
        )
        self.assertEqual(json.loads(output)["status"], "success")

    def test_provider_health_json_outputs_parseable_json(self):
        from crawler import agent_cli

        with patch.object(agent_cli, "_request") as request:
            request.return_value = {"beeclaw": {"ready": True}}

            code, output = run_cli(["provider", "health", "--json"])

        self.assertEqual(code, 0)
        request.assert_called_once_with(
            "GET",
            "/api/providers/health",
            None,
            base_url="http://127.0.0.1:8780",
        )
        self.assertTrue(json.loads(output)["beeclaw"]["ready"])

    def test_api_unavailable_returns_nonzero_and_start_command(self):
        from crawler import agent_cli

        with patch.object(agent_cli, "_request", side_effect=agent_cli.ApiUnavailable("connection refused")):
            code, output = run_cli(["provider", "health", "--json"])

        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "radar_api_unavailable")
        self.assertEqual(payload["error"]["fix"], "./tools/run_radar_api.sh")

    def test_default_output_is_human_readable_summary(self):
        from crawler import agent_cli

        with patch.object(agent_cli, "_request") as request:
            request.return_value = {
                "id": "crawl-1",
                "status": "success",
                "saved_count": 1,
                "failure_count": 0,
                "agent_feedback": {
                    "message": "采集完成：保存 1 条，失败 0 个。",
                    "content_ids": [101],
                    "summary": {"execution_backends": ["rss_parser"]},
                },
            }

            code, output = run_cli(["task", "get", "crawl-1"])

        self.assertEqual(code, 0)
        self.assertIn("采集完成：保存 1 条，失败 0 个。", output)
        self.assertIn("任务: crawl-1", output)
        self.assertIn("内容 IDs: 101", output)
        self.assertIn("执行后端: rss_parser", output)

    def test_tools_beeclaw_script_exists_and_is_executable(self):
        script = Path("tools/beeclaw")

        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
