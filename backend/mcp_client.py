"""
MCP Client module for connecting to MCP servers.

Provides on-demand connection management for both stdio and SSE transports.
Tools discovered from MCP servers are formatted as OpenAI-compatible function specs.
"""
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

# Anthropic (and, more conservatively, OpenAI/Gemini) require tool names to
# match ^[a-zA-Z0-9_-]{1,128}$ — but MCP server names are free-text user
# input (models.py's MCPServer.name has no format constraint) and upstream
# tool names aren't guaranteed to be constrained either, so a raw
# f"mcp__{server_name}__{tool.name}" prefix (the actual shape that shipped)
# can and did produce invalid names (spaces, dots, etc.) that the provider
# API rejects outright with a 400. Sanitize both halves into the prefix,
# and keep an unsanitized reverse-lookup so dispatch still calls the real
# upstream tool with its real name.
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_name_part(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name) or "_"


class MCPConnection:
    """Represents an active connection to an MCP server."""

    def __init__(self, server_id: str, server_name: str, session: ClientSession):
        self.server_id = server_id
        self.server_name = server_name
        self.sanitized_server_name = _sanitize_name_part(server_name)
        self.session = session
        self.tools: list[dict] = []
        self.tool_names: set[str] = set()
        # sanitized original tool name -> real upstream tool name, so
        # call_tool() can always be given the name the MCP server itself
        # actually expects, not the one shown to the LLM.
        self._tool_name_map: dict[str, str] = {}

    async def discover_tools(self) -> list[dict]:
        """List tools from the MCP server and format as OpenAI function specs."""
        result = await self.session.list_tools()
        self.tools = []
        self.tool_names = set()
        self._tool_name_map = {}
        for tool in result.tools:
            sanitized_tool_name = _sanitize_name_part(tool.name)
            self._tool_name_map[sanitized_tool_name] = tool.name
            prefixed_name = f"mcp__{self.sanitized_server_name}__{sanitized_tool_name}"[:128]
            self.tool_names.add(prefixed_name)
            self.tools.append({
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                },
            })
        return self.tools

    def resolve_real_tool_name(self, sanitized_tool_name: str) -> str:
        """Map a sanitized tool name (as parsed from a prefixed tool call)
        back to the real name the upstream MCP server expects."""
        return self._tool_name_map.get(sanitized_tool_name, sanitized_tool_name)

    async def call_tool(self, original_tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server. Accepts the unprefixed original name."""
        result = await self.session.call_tool(original_tool_name, arguments)
        parts = []
        for content_item in result.content:
            if hasattr(content_item, "text"):
                parts.append(content_item.text)
            else:
                parts.append(str(content_item))
        return "\n".join(parts) if parts else ""


def parse_mcp_tool_name(prefixed_name: str) -> tuple[str, str] | None:
    """Parse 'mcp__<sanitized_server_name>__<sanitized_tool_name>' into
    (sanitized_server_name, sanitized_tool_name). Returns None if the name
    doesn't match the MCP prefix pattern. Both halves are the SANITIZED
    forms — callers must match them against MCPConnection.sanitized_server_name
    (not .server_name) and resolve the real tool name via
    MCPConnection.resolve_real_tool_name() before calling call_tool()."""
    if not prefixed_name.startswith("mcp__"):
        return None
    parts = prefixed_name.split("__", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


@asynccontextmanager
async def connect_mcp_stdio(
    server_id: str,
    server_name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> AsyncIterator[MCPConnection]:
    """Connect to an MCP server via stdio transport."""
    server_params = StdioServerParameters(
        command=command,
        args=args or [],
        env=env,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            conn = MCPConnection(server_id, server_name, session)
            await conn.discover_tools()
            yield conn


@asynccontextmanager
async def connect_mcp_sse(
    server_id: str,
    server_name: str,
    url: str,
    headers: dict[str, str] | None = None,
) -> AsyncIterator[MCPConnection]:
    """Connect to an MCP server via SSE transport."""
    async with sse_client(url, headers=headers or {}) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            conn = MCPConnection(server_id, server_name, session)
            await conn.discover_tools()
            yield conn


@asynccontextmanager
async def connect_mcp_streamable_http(
    server_id: str,
    server_name: str,
    url: str,
    headers: dict[str, str] | None = None,
) -> AsyncIterator[MCPConnection]:
    """Connect to an MCP server via Streamable HTTP transport."""
    async with streamablehttp_client(url, headers=headers or {}) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            conn = MCPConnection(server_id, server_name, session)
            await conn.discover_tools()
            yield conn


@asynccontextmanager
async def connect_mcp_server(server_config: dict) -> AsyncIterator[MCPConnection]:
    """Connect to an MCP server using its stored config.

    server_config should contain:
        - id or _id (str)
        - name (str)
        - transport_type ("stdio" | "sse" | "streamable_http")
        - command, args_json, env_json (for stdio)
        - url, headers_json (for sse / streamable_http)
    """
    server_id = str(server_config.get("id") or server_config.get("_id"))
    server_name = server_config["name"]
    transport = server_config["transport_type"]

    if transport == "stdio":
        command = server_config.get("command", "")
        args_raw = server_config.get("args_json") or server_config.get("args")
        if isinstance(args_raw, str):
            args = json.loads(args_raw)
        elif isinstance(args_raw, list):
            args = args_raw
        else:
            args = []
        env_raw = server_config.get("env_json") or server_config.get("env")
        if isinstance(env_raw, str):
            env = json.loads(env_raw)
        elif isinstance(env_raw, dict):
            env = env_raw
        else:
            env = None

        async with connect_mcp_stdio(server_id, server_name, command, args, env) as conn:
            yield conn

    elif transport == "sse":
        url = server_config.get("url", "")
        headers_raw = server_config.get("headers_json") or server_config.get("headers")
        if isinstance(headers_raw, str):
            headers = json.loads(headers_raw)
        elif isinstance(headers_raw, dict):
            headers = headers_raw
        else:
            headers = None

        async with connect_mcp_sse(server_id, server_name, url, headers) as conn:
            yield conn

    elif transport in ("streamable_http", "http", "streamable-http"):
        url = server_config.get("url", "")
        headers_raw = server_config.get("headers_json") or server_config.get("headers")
        if isinstance(headers_raw, str):
            headers = json.loads(headers_raw)
        elif isinstance(headers_raw, dict):
            headers = headers_raw
        else:
            headers = None

        async with connect_mcp_streamable_http(server_id, server_name, url, headers) as conn:
            yield conn

    else:
        raise ValueError(f"Unsupported MCP transport: {transport}")
