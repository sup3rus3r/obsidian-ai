"""
MCP Client module for connecting to MCP servers.

Provides on-demand connection management for both stdio and SSE transports.
Tools discovered from MCP servers are formatted as OpenAI-compatible function specs.
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


class MCPConnection:
    """Represents an active connection to an MCP server."""

    def __init__(self, server_id: str, server_name: str, session: ClientSession):
        self.server_id = server_id
        self.server_name = server_name
        self.session = session
        self.tools: list[dict] = []
        self.tool_names: set[str] = set()

    async def discover_tools(self) -> list[dict]:
        """List tools from the MCP server and format as OpenAI function specs."""
        result = await self.session.list_tools()
        self.tools = []
        self.tool_names = set()
        for tool in result.tools:
            prefixed_name = f"mcp__{self.server_name}__{tool.name}"
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
    """Parse 'mcp__<server_name>__<tool_name>' into (server_name, tool_name).
    Returns None if the name doesn't match the MCP prefix pattern."""
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
async def connect_mcp_server(server_config: dict) -> AsyncIterator[MCPConnection]:
    """Connect to an MCP server using its stored config.

    server_config should contain:
        - id or _id (str)
        - name (str)
        - transport_type ("stdio" | "sse")
        - command, args_json, env_json (for stdio)
        - url, headers_json (for sse)
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

    else:
        raise ValueError(f"Unsupported MCP transport: {transport}")
