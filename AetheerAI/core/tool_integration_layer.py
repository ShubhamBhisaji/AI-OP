"""Plugin-based tool integration layer for autonomous agents.

Provides a stable interface over ToolManager for common operations:
- File read/write
- HTTP/API requests
- Safe terminal execution
- Runtime plugin registration for custom extensions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


PluginHandler = Callable[..., Any]


@dataclass
class ToolPlugin:
    name: str
    description: str
    handler: PluginHandler


class ToolIntegrationLayer:
    """Abstraction and plugin registry over the low-level ToolManager."""

    def __init__(self, tool_manager) -> None:
        self.tool_manager = tool_manager
        self._plugins: dict[str, ToolPlugin] = {}
        self._register_default_plugins()

    def _register_default_plugins(self) -> None:
        self.register_plugin(
            "fs.read",
            self._read_file,
            "Read a file from workspace/local filesystem via file_reader",
        )
        self.register_plugin(
            "fs.write",
            self._write_file,
            "Write content to a file via file_writer",
        )
        self.register_plugin(
            "http.request",
            self._http_request,
            "Issue HTTP requests via http_client",
        )
        self.register_plugin(
            "terminal.safe",
            self._terminal_safe,
            "Run allowlisted terminal commands via terminal_tool",
        )

    def register_plugin(self, name: str, handler: PluginHandler, description: str = "") -> None:
        self._plugins[name] = ToolPlugin(name=name, description=description, handler=handler)
        logger.debug("ToolIntegrationLayer: registered plugin '%s'.", name)

    def unregister_plugin(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        del self._plugins[name]
        return True

    def list_plugins(self) -> list[dict[str, str]]:
        return [
            {"name": plugin.name, "description": plugin.description}
            for plugin in self._plugins.values()
        ]

    def execute(
        self,
        plugin_name: str,
        *,
        agent_name: str,
        agent_level: int,
        **kwargs: Any,
    ) -> Any:
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise KeyError(f"Plugin '{plugin_name}' is not registered.")
        return plugin.handler(agent_name=agent_name, agent_level=agent_level, **kwargs)

    def _read_file(self, *, agent_name: str, agent_level: int, path: str) -> Any:
        return self.tool_manager.call(
            "file_reader",
            filename=path,
            agent_name=agent_name,
            agent_level=agent_level,
        )

    def _write_file(self, *, agent_name: str, agent_level: int, path: str, content: str) -> Any:
        return self.tool_manager.call(
            "file_writer",
            filename=path,
            content=content,
            agent_name=agent_name,
            agent_level=agent_level,
        )

    def _http_request(
        self,
        *,
        agent_name: str,
        agent_level: int,
        url: str,
        method: str = "GET",
        **kwargs: Any,
    ) -> Any:
        return self.tool_manager.call(
            "http_client",
            url=url,
            method=method,
            agent_name=agent_name,
            agent_level=agent_level,
            **kwargs,
        )

    def _terminal_safe(
        self,
        *,
        agent_name: str,
        agent_level: int,
        command: str,
        cwd: str = "",
    ) -> Any:
        return self.tool_manager.call(
            "terminal_tool",
            command=command,
            cwd=cwd,
            agent_name=agent_name,
            agent_level=agent_level,
        )
