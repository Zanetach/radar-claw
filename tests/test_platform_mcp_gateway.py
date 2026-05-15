import json
import os
import unittest
from unittest.mock import patch

from crawler.platform_mcp_gateway import (
    PlatformMcpGatewayError,
    call_platform_mcp_tool,
    gateway_config_status,
    platform_mcp_manager_identity,
    unwrap_gateway_response,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def open(self, request, timeout=0):
        self.request = request
        self.timeout = timeout
        return FakeResponse(self.payload)


class PlatformMcpGatewayTests(unittest.TestCase):
    def test_gateway_config_status_does_not_expose_secret_values(self):
        with patch.dict(
            os.environ,
            {
                "RADAR_BACKEND_MCP_MODE": "platform_gateway",
                "PLATFORM_MCP_GATEWAY_URL": "http://gateway.local",
                "PLATFORM_MCP_WORKSPACE_ID": "workspace-1",
                "PLATFORM_MCP_RUNTIME_TOKEN": "secret-runtime-token",
            },
            clear=True,
        ):
            status = gateway_config_status()

        self.assertTrue(status["enabled"])
        self.assertTrue(status["urlConfigured"])
        self.assertTrue(status["workspaceIdConfigured"])
        self.assertTrue(status["runtimeTokenConfigured"])
        self.assertFalse(status["secretValuesExposed"])
        self.assertNotIn("secret-runtime-token", json.dumps(status))

    def test_manager_identity_is_configurable_and_not_qianfeng_specific(self):
        with patch.dict(
            os.environ,
            {
                "MCP_MANAGER_NAME": "tenant-mcp-manager",
                "MCP_MANAGER_DISPLAY_NAME": "Tenant MCP Manager",
                "MCP_MANAGER_MANAGED_BY": "tenant_platform",
            },
            clear=True,
        ):
            identity = platform_mcp_manager_identity()

        self.assertEqual(identity["name"], "tenant-mcp-manager")
        self.assertEqual(identity["displayName"], "Tenant MCP Manager")
        self.assertEqual(identity["managedBy"], "tenant_platform")
        self.assertEqual(identity["message"], "managed_by_tenant_mcp_manager")

    def test_call_platform_mcp_tool_posts_integration_tool_and_arguments(self):
        opener = FakeOpener({"ok": True, "data": {"data": [{"id": "post-1"}]}})
        with patch.dict(
            os.environ,
            {
                "RADAR_BACKEND_MCP_MODE": "platform_gateway",
                "PLATFORM_MCP_GATEWAY_URL": "http://gateway.local/mcp",
                "PLATFORM_MCP_WORKSPACE_ID": "workspace-1",
                "PLATFORM_MCP_RUNTIME_TOKEN": "secret-runtime-token",
            },
            clear=True,
        ):
            with patch("crawler.platform_mcp_gateway.urllib.request.build_opener", return_value=opener):
                result = call_platform_mcp_tool(
                    integration="x-mcp",
                    tool="searchPostsRecent",
                    arguments={"query": "from:elonmusk"},
                    trace_id="task-1",
                )

        request_payload = json.loads(opener.request.data.decode("utf-8"))
        self.assertEqual(opener.request.full_url, "http://gateway.local/mcp/invoke")
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer secret-runtime-token")
        self.assertEqual(request_payload["integration"], "x-mcp")
        self.assertEqual(request_payload["tool"], "searchPostsRecent")
        self.assertEqual(request_payload["arguments"], {"query": "from:elonmusk"})
        self.assertEqual(request_payload["workspace_id"], "workspace-1")
        self.assertEqual(request_payload["trace_id"], "task-1")
        self.assertEqual(result, {"data": [{"id": "post-1"}]})

    def test_call_platform_mcp_tool_requires_explicit_gateway_mode(self):
        with patch.dict(os.environ, {"PLATFORM_MCP_GATEWAY_URL": "http://gateway.local/mcp"}, clear=True):
            with self.assertRaises(PlatformMcpGatewayError) as ctx:
                call_platform_mcp_tool(integration="x-mcp", tool="getUsersPosts", arguments={})

        self.assertEqual(ctx.exception.error_type, "platform_mcp_gateway_disabled")

    def test_unwrap_gateway_response_supports_mcp_text_content(self):
        payload = unwrap_gateway_response(
            {
                "ok": True,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "{\"data\":[{\"id\":\"1\"}]}",
                        }
                    ]
                },
            }
        )

        self.assertEqual(payload, {"data": [{"id": "1"}]})


if __name__ == "__main__":
    unittest.main()
