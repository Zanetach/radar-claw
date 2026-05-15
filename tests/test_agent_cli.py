import io
import importlib
import json
import os
import stat
import subprocess
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

    def test_agent_cli_request_adds_radar_api_token_when_configured(self):
        from crawler import agent_cli

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"ok": true}'

        captured = {}

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.dict(os.environ, {"RADAR_API_TOKEN": "secret-radar-token"}, clear=False):
            with patch.object(agent_cli.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = agent_cli._request("GET", "/api/summary")

        self.assertTrue(result["ok"])
        self.assertEqual(captured["authorization"], "Bearer secret-radar-token")

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

    def test_unified_install_script_help_lists_core_steps(self):
        script = Path("tools/install_beeclaw.sh")

        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        result = subprocess.run([str(script.resolve()), "--help"], check=False, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)
        self.assertIn("install-deps", result.stdout)
        self.assertIn("install-hermes", result.stdout)
        self.assertIn("--no-start", result.stdout)
        self.assertIn("doctor", result.stdout)

    def test_release_package_script_help_is_available(self):
        script = Path("tools/package_beeclaw_release.sh")

        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        result = subprocess.run([str(script.resolve()), "--help"], check=False, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)
        self.assertIn("beeclaw-radar", result.stdout)
        self.assertIn("dist", result.stdout)

    def test_root_env_example_documents_runtime_modes(self):
        env_example = Path(".env.example")

        self.assertTrue(env_example.exists())
        text = env_example.read_text(encoding="utf-8")
        self.assertIn("RADAR_BASE_URL", text)
        self.assertIn("BEECLAW_X_BROWSER_SESSION_MODE", text)
        self.assertIn("BEECLAW_X_BROWSER_ENDPOINT", text)
        self.assertIn("RADAR_BACKEND_MCP_MODE", text)
        self.assertIn("RADAR_API_TOKEN", text)

    def test_package_json_exposes_npx_installer(self):
        package_json = Path("package.json")

        self.assertTrue(package_json.exists())
        payload = json.loads(package_json.read_text(encoding="utf-8"))
        self.assertEqual(payload["bin"]["beeclaw-radar"], "tools/npx-install.mjs")
        self.assertIn("tools/npx-install.mjs", payload["files"])
        self.assertIn("crawler", payload["files"])

    def test_smoke_script_writes_report_file_with_summary(self):
        smoke = importlib.import_module("tools.beeclaw_platform_smoke")
        with tempfile.TemporaryDirectory() as tmp:
            report_file = Path(tmp) / "smoke.json"
            with patch.object(
                smoke.sys,
                "argv",
                [
                    "beeclaw_platform_smoke.py",
                    "--platforms",
                    "web",
                    "--types",
                    "url",
                    "--report-file",
                    str(report_file),
                    "--json",
                ],
            ):
                with redirect_stdout(io.StringIO()):
                    code = smoke.main()

            payload = json.loads(report_file.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["dryRun"], 1)
        self.assertEqual(payload["results"][0]["platform"], "web")

    def test_npx_installer_help_lists_actions(self):
        script = Path("tools/npx-install.mjs")

        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        result = subprocess.run(["node", str(script), "--help"], check=False, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)
        self.assertIn("npx", result.stdout)
        self.assertIn("install", result.stdout)
        self.assertIn("start-api", result.stdout)
        self.assertIn("--no-start", result.stdout)
        self.assertIn("doctor", result.stdout)

    def test_root_install_script_wraps_npx_autostart(self):
        script = Path("install.sh")

        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        result = subprocess.run([str(script.resolve()), "--help"], check=False, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)
        self.assertIn("curl", result.stdout)
        self.assertIn("npx github:Zanetach/radar-claw install", result.stdout)
        self.assertIn("--no-start", result.stdout)

    def test_npx_installer_refuses_to_delete_unrelated_install_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            keep = target / "keep.txt"
            keep.write_text("do not delete", encoding="utf-8")

            result = subprocess.run(
                [
                    "node",
                    "tools/npx-install.mjs",
                    "install",
                    "--dir",
                    str(target),
                    "--no-start",
                    "--skip-hermes",
                    "--skip-clis",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(keep.exists())
            self.assertIn("Refusing to overwrite", result.stderr)

    def test_run_radar_api_derives_host_and_port_from_base_url(self):
        script = Path("tools/run_radar_api.sh")

        text = script.read_text(encoding="utf-8")
        self.assertIn("RADAR_BASE_URL", text)
        self.assertIn("urlparse", text)
        self.assertIn("RADAR_DERIVED_HOST", text)
        self.assertIn("RADAR_DERIVED_PORT", text)
        self.assertIn("RADAR_DERIVED_BIND", text)

    def test_run_radar_api_has_pip_fallback_without_uv(self):
        text = Path("tools/run_radar_api.sh").read_text(encoding="utf-8")

        self.assertIn("python3 -m venv", text)
        self.assertIn("ensurepip", text)
        self.assertIn("pip install", text)


if __name__ == "__main__":
    unittest.main()
