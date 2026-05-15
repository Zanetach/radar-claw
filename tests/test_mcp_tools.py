import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeFastMCP:
    def __init__(self, *args, **kwargs):
        pass

    def tool(self):
        def decorator(func):
            return func

        return decorator

    def run(self):
        pass


def import_mcp_server_with_fake_mcp():
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = _FakeFastMCP
    server_module = types.ModuleType("mcp.server")
    mcp_module = types.ModuleType("mcp")
    with patch.dict(
        sys.modules,
        {
            "mcp": mcp_module,
            "mcp.server": server_module,
            "mcp.server.fastmcp": fastmcp_module,
        },
    ):
        sys.modules.pop("tools.radar_mcp_server", None)
        return importlib.import_module("tools.radar_mcp_server")


class RadarMcpToolsTests(unittest.TestCase):
    def test_radar_agent_collect_posts_instruction_to_chat_api(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.return_value = {"agent_feedback": {"message": "采集完成：保存 1 条，失败 0 个。"}}

            result = server.radar_agent_collect(
                "免费抓取 @OpenAI 最近7天原创推文",
                execute=True,
                strategy_id="x-rss-ai-intel",
            )

        request.assert_called_once_with(
            "POST",
            "/api/agent/chat",
            {
                "message": "免费抓取 @OpenAI 最近7天原创推文",
                "execute": True,
                "strategyId": "x-rss-ai-intel",
            },
        )
        self.assertEqual(result["agent_feedback"]["message"], "采集完成：保存 1 条，失败 0 个。")

    def test_radar_handoff_to_organizer_uses_new_endpoint(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.return_value = {"organizer_task": {"agent": "内容整理 Agent"}}

            result = server.radar_handoff_to_organizer([1, 2], translate_to_zh=True)

        request.assert_called_once_with(
            "POST",
            "/api/raw-contents/handoff/organizer",
            {
                "contentIds": [1, 2],
                "translateToZh": True,
                "ocrImages": True,
                "summarize": True,
                "classify": True,
                "qualityScore": True,
            },
        )
        self.assertEqual(result["organizer_task"]["agent"], "内容整理 Agent")

    def test_radar_create_collection_task_passes_batch_urls(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.return_value = {"id": "crawl-batch", "source_type": "batch"}

            result = server.radar_create_collection_task(
                urls="https://example.com/a\nhttps://example.com/b",
                platform="web",
                mode="beeclaw",
                queue=True,
            )

        request.assert_called_once()
        method, path, payload = request.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/collection-tasks")
        self.assertEqual(payload["sourceType"], "url")
        self.assertEqual(payload["urls"], "https://example.com/a\nhttps://example.com/b")
        self.assertTrue(payload["queue"])
        self.assertEqual(result["source_type"], "batch")

    def test_retry_and_media_batch_tools_call_expected_endpoints(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.side_effect = [
                {"status": "queued"},
                {"attempted": 2},
                {"dataset_jsonl": "{}"},
            ]

            retry = server.radar_retry_collection_task("crawl-1", queue=True)
            media_retry = server.radar_retry_media_assets(run_id="crawl-1", status="failed", limit=20)
            export = server.radar_export_media_assets(run_id="crawl-1", output_format="jsonl")

        self.assertEqual(retry["status"], "queued")
        self.assertEqual(media_retry["attempted"], 2)
        self.assertIn("dataset_jsonl", export)
        self.assertEqual(request.call_args_list[0].args, ("POST", "/api/runs/crawl-1/retry", {"queue": True}))
        self.assertEqual(
            request.call_args_list[1].args,
            ("POST", "/api/media-assets/retry", {"contentId": 0, "runId": "crawl-1", "status": "failed", "limit": 20}),
        )
        self.assertEqual(
            request.call_args_list[2].args,
            ("GET", "/api/media-assets/export?runId=crawl-1&limit=100&format=jsonl"),
        )

    def test_xmcp_pressure_test_tool_calls_provider_endpoint(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.return_value = {"mode": "beeclaw:x_mcp", "estimatedApiCalls": 4}

            result = server.radar_xmcp_pressure_test(
                handles="@OpenAI,@Anthropic",
                max_accounts=2,
                max_results=3,
                execute=True,
                queue=True,
            )

        self.assertEqual(result["mode"], "beeclaw:x_mcp")
        self.assertEqual(
            request.call_args.args,
            (
                "POST",
                "/api/providers/xmcp/pressure-test",
                {
                    "handles": "@OpenAI,@Anthropic",
                    "maxAccounts": 2,
                    "maxResults": 3,
                    "execute": True,
                    "queue": True,
                    "maxAttempts": 1,
                },
            ),
        )

    def test_mcp_integrations_tool_calls_catalog_endpoint(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.return_value = {"items": [{"name": "radar"}, {"name": "x-mcp"}]}

            result = server.radar_list_mcp_integrations(integration_type="backend")

        self.assertEqual(result["items"][1]["name"], "x-mcp")
        request.assert_called_once_with("GET", "/api/mcp/integrations?type=backend")

    def test_production_readiness_tool_calls_readiness_endpoint(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.return_value = {"overallStatus": "project_ready_requires_production_validation"}

            result = server.radar_check_production_readiness()

        self.assertEqual(result["overallStatus"], "project_ready_requires_production_validation")
        request.assert_called_once_with("GET", "/api/production-readiness")

    def test_interaction_tools_call_expected_endpoints(self):
        server = import_mcp_server_with_fake_mcp()
        with patch.object(server, "_request") as request:
            request.side_effect = [
                {"interaction_task": {"agent": "互动建议 Agent"}},
                {"saved": 1},
                {"items": [{"id": 1}]},
                {"dataset_markdown": "# 黄金互动窗口候选"},
            ]

            handoff = server.radar_handoff_to_interaction_agent([1, 2], target_channel="feishu_table")
            saved = server.radar_save_interaction_candidates(
                '[{"contentId":1,"windowScore":86,"suggestedReply":"reply"}]'
            )
            listed = server.radar_list_interaction_candidates(status="pending")
            exported = server.radar_export_interaction_candidates(output_format="markdown")

        self.assertEqual(handoff["interaction_task"]["agent"], "互动建议 Agent")
        self.assertEqual(saved["saved"], 1)
        self.assertEqual(listed["items"][0]["id"], 1)
        self.assertIn("黄金互动窗口候选", exported["dataset_markdown"])
        self.assertEqual(
            request.call_args_list[0].args,
            (
                "POST",
                "/api/raw-contents/handoff/interaction",
                {
                    "contentIds": [1, 2],
                    "targetChannel": "feishu_table",
                    "goldenWindowScore": True,
                    "generateReply": True,
                    "generateQuote": True,
                    "riskCheck": True,
                },
            ),
        )
        self.assertEqual(request.call_args_list[1].args[0:2], ("POST", "/api/interaction-candidates"))
        self.assertEqual(request.call_args_list[2].args, ("GET", "/api/interaction-candidates?status=pending&limit=50"))
        self.assertEqual(request.call_args_list[3].args, ("GET", "/api/interaction-candidates/export?limit=100&format=markdown"))


if __name__ == "__main__":
    unittest.main()
