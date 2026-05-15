from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


GATEWAY_MODE = "platform_gateway"
MODE_ALIASES = {"platform_gateway", "qianfeng_gateway", "mcp_gateway", "gateway"}


class PlatformMcpGatewayError(Exception):
    def __init__(self, message: str, *, error_type: str = "platform_mcp_gateway_error", status_code: int | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _manager_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return slug or "platform_mcp_manager"


def platform_mcp_manager_identity() -> dict[str, str]:
    name = _env_first("MCP_MANAGER_NAME", "PLATFORM_MCP_MANAGER_NAME") or "platform-mcp-manager"
    display_name = _env_first("MCP_MANAGER_DISPLAY_NAME", "PLATFORM_MCP_MANAGER_DISPLAY_NAME") or "Platform MCP Manager"
    managed_by = _env_first("MCP_MANAGER_MANAGED_BY", "PLATFORM_MCP_MANAGER_MANAGED_BY") or "platform_runtime"
    return {
        "name": name,
        "displayName": display_name,
        "managedBy": managed_by,
        "message": f"managed_by_{_manager_slug(name)}",
    }


def platform_gateway_enabled() -> bool:
    mode = os.getenv("RADAR_BACKEND_MCP_MODE", "").strip().lower()
    return mode in MODE_ALIASES


def gateway_url() -> str | None:
    value = _env_first(
        "MCP_GATEWAY_URL",
        "PLATFORM_MCP_GATEWAY_URL",
        "QF_MCP_GATEWAY_URL",
        "QIANFENG_MCP_GATEWAY_URL",
    )
    return value.strip().rstrip("/") if value else None


def gateway_config_status() -> dict[str, Any]:
    url = gateway_url()
    workspace_id = _env_first(
        "MCP_WORKSPACE_ID",
        "PLATFORM_MCP_WORKSPACE_ID",
        "QF_MCP_WORKSPACE_ID",
        "QIANFENG_MCP_WORKSPACE_ID",
    )
    runtime_token = _env_first(
        "MCP_RUNTIME_TOKEN",
        "PLATFORM_MCP_RUNTIME_TOKEN",
        "QF_MCP_RUNTIME_TOKEN",
        "QIANFENG_MCP_RUNTIME_TOKEN",
    )
    return {
        "enabled": platform_gateway_enabled(),
        "urlConfigured": bool(url),
        "workspaceIdConfigured": bool(workspace_id),
        "runtimeTokenConfigured": bool(runtime_token),
        "secretValuesExposed": False,
    }


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = _env_first(
        "MCP_RUNTIME_TOKEN",
        "PLATFORM_MCP_RUNTIME_TOKEN",
        "QF_MCP_RUNTIME_TOKEN",
        "QIANFENG_MCP_RUNTIME_TOKEN",
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gateway_endpoint(base_url: str) -> str:
    configured_path = _env_first(
        "MCP_GATEWAY_INVOKE_PATH",
        "PLATFORM_MCP_GATEWAY_INVOKE_PATH",
        "QF_MCP_GATEWAY_INVOKE_PATH",
        "QIANFENG_MCP_GATEWAY_INVOKE_PATH",
    )
    if configured_path:
        if configured_path.startswith(("http://", "https://")):
            return configured_path
        return f"{base_url}/{configured_path.lstrip('/')}"
    return f"{base_url}/invoke"


def _parse_tool_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {"text": payload}
        return _parse_tool_payload(decoded)
    if isinstance(payload, list):
        return {"data": payload}
    if not isinstance(payload, dict):
        return {"result": payload}
    if payload.get("isError") or payload.get("is_error"):
        raise PlatformMcpGatewayError(json.dumps(payload, ensure_ascii=False), error_type="backend_mcp_error")
    structured = payload.get("structuredContent") or payload.get("structured_content")
    if isinstance(structured, dict):
        return structured
    content = payload.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else getattr(first, "text", None)
        if isinstance(text, str):
            return _parse_tool_payload(text)
    return payload


def unwrap_gateway_response(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok") is False or response.get("success") is False:
        error = response.get("error") or response.get("message") or response
        raise PlatformMcpGatewayError(json.dumps(error, ensure_ascii=False), error_type="backend_mcp_error")
    if "ok" in response or "success" in response:
        for key in ("result", "data", "structuredContent", "structured_content"):
            if key in response:
                return _parse_tool_payload(response[key])
    return _parse_tool_payload(response)


def call_platform_mcp_tool(
    *,
    integration: str,
    tool: str,
    arguments: dict[str, Any],
    trace_id: str | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    if not platform_gateway_enabled():
        raise PlatformMcpGatewayError(
            "Platform MCP Gateway mode is not enabled. Set RADAR_BACKEND_MCP_MODE=platform_gateway.",
            error_type="platform_mcp_gateway_disabled",
        )
    base_url = gateway_url()
    if not base_url:
        raise PlatformMcpGatewayError(
            "Platform MCP Gateway URL is not configured. Set MCP_GATEWAY_URL or PLATFORM_MCP_GATEWAY_URL.",
            error_type="platform_mcp_gateway_unavailable",
        )
    workspace_id = _env_first(
        "MCP_WORKSPACE_ID",
        "PLATFORM_MCP_WORKSPACE_ID",
        "QF_MCP_WORKSPACE_ID",
        "QIANFENG_MCP_WORKSPACE_ID",
    )
    payload = {
        "integration": integration,
        "tool": tool,
        "arguments": arguments,
    }
    if trace_id:
        payload["trace_id"] = trace_id
    if workspace_id:
        payload["workspace_id"] = workspace_id
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _gateway_endpoint(base_url),
        data=body,
        headers=_headers(),
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout_seconds) as response:
            text = response.read().decode("utf-8")
            data = json.loads(text) if text else {}
            return unwrap_gateway_response(data)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        lowered = detail.lower()
        if "creditsdepleted" in lowered or "payment required" in lowered or exc.code == 402:
            error_type = "credits_depleted"
        elif exc.code in {401, 403}:
            error_type = "platform_mcp_gateway_auth_failed"
        else:
            error_type = "platform_mcp_gateway_http_error"
        raise PlatformMcpGatewayError(detail or exc.reason, error_type=error_type, status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise PlatformMcpGatewayError(str(exc.reason), error_type="platform_mcp_gateway_unavailable") from exc
    except json.JSONDecodeError as exc:
        raise PlatformMcpGatewayError(str(exc), error_type="platform_mcp_gateway_bad_response") from exc


def platform_backend_mcp_status(integration: str) -> dict[str, Any]:
    config = gateway_config_status()
    status = "connected" if config["enabled"] and config["urlConfigured"] else "unavailable"
    if config["enabled"] and not config["urlConfigured"]:
        status = "gateway_url_missing"
    return {
        "integration": integration,
        "mode": GATEWAY_MODE,
        "status": status,
        **config,
    }
