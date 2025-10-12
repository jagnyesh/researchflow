"""
MCP Server Registry

Central registry for managing MCP server connections and routing tool calls.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MCPServerRegistry:
    """
    Registry for MCP server instances

    Manages connections to various MCP servers (Epic Clarity, FHIR, Terminology, etc.)
    and provides unified interface for tool calls.
    """

    def __init__(self):
        self._servers = {}
        self._initialize_default_servers()

    def _initialize_default_servers(self):
        """Initialize default MCP server stubs"""
        # TODO: Initialize actual MCP server connections
        # For now, register mock servers
        logger.info("Initializing MCP server registry")

    def register_server(self, server_id: str, server_instance):
        """
        Register an MCP server instance

        Args:
            server_id: Unique identifier (e.g., 'epic_clarity', 'fhir_server')
            server_instance: MCP server instance
        """
        self._servers[server_id] = server_instance
        logger.info(f"Registered MCP server: {server_id}")

    def get_server(self, server_id: str):
        """
        Get MCP server instance by ID

        Args:
            server_id: Server identifier

        Returns:
            MCP server instance or None
        """
        server = self._servers.get(server_id)
        if not server:
            logger.warning(f"MCP server not found: {server_id}")
        return server

    def list_servers(self) -> list:
        """List all registered MCP servers"""
        return list(self._servers.keys())

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Any:
        """
        Call a tool on an MCP server

        Args:
            server_id: Server identifier
            tool_name: Tool/method name
            parameters: Tool parameters

        Returns:
            Tool result
        """
        server = self.get_server(server_id)
        if not server:
            raise ValueError(f"MCP server not found: {server_id}")

        logger.debug(f"Calling {server_id}.{tool_name}")

        # Call the tool on the server
        if hasattr(server, 'call_tool'):
            return await server.call_tool(tool_name, parameters)
        elif hasattr(server, tool_name):
            method = getattr(server, tool_name)
            return await method(**parameters)
        else:
            raise ValueError(f"Tool not found: {server_id}.{tool_name}")


class BaseMCPServer:
    """
    Base class for MCP servers

    Provides common interface for all MCP server implementations.
    """

    def __init__(self, server_id: str):
        self.server_id = server_id
        self.tools = {}

    def register_tool(self, tool_name: str, handler):
        """Register a tool handler"""
        self.tools[tool_name] = handler
        logger.debug(f"[{self.server_id}] Registered tool: {tool_name}")

    async def call_tool(self, tool_name: str, parameters: Dict) -> Any:
        """Call a registered tool"""
        if tool_name not in self.tools:
            raise ValueError(f"Tool not found: {tool_name}")

        handler = self.tools[tool_name]
        return await handler(parameters)

    def list_tools(self) -> list:
        """List available tools"""
        return list(self.tools.keys())
