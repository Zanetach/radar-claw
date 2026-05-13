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


if __name__ == "__main__":
    unittest.main()
