"""
mcp_bridge.py — Model Context Protocol (MCP) & Agent-to-Agent (A2A) Bridge.

Feature 2 — Multi-Protocol Interoperability:

    MCPClient  — connect to any external MCP server (JSON-RPC 2.0 over HTTP),
                 discover its tools, and register them inside AetheerAI's
                 ToolManager so agents can call them transparently.

    MCPServer  — expose AetheerAI's own tools as an MCP-compliant HTTP endpoint
                 so external MCP clients can call into AetheerAI without any
                 custom integration code.

    A2AClient  — delegate tasks to external A2A-compliant agents (Google A2A
                 spec).  Discovers capabilities via Agent Card at
                 /.well-known/agent.json, then submits tasks via POST /tasks/send.

    A2AServer  — expose AetheerAI as an A2A-compliant agent endpoint so any
                 A2A-capable platform (OpenAI Assistants, Microsoft AutoGen, etc.)
                 can hire AetheerAI as a worker agent.

    InteropBridge — unified facade wiring all four components together.
                    Attach to AetheerAiKernel as kernel.interop.

No extra dependencies required.  Built entirely on Python stdlib
(urllib.request, http.server, threading).
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: dict, timeout: float = 15.0) -> dict:
    """POST JSON payload and return the decoded JSON response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: float = 10.0) -> dict:
    """GET and return the decoded JSON response."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _jsonrpc(method: str, params: dict, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Connects to an MCP server over HTTP JSON-RPC 2.0.
    Discovers the server's tool catalogue and wraps each tool as an
    AetheerAI-compatible callable.

    Example::

        client = MCPClient("http://localhost:3000")
        tools  = client.as_aetheerai_tools()   # {name: callable, ...}
        for name, fn in tools.items():
            kernel.tool_manager.register(name, fn)
    """

    def __init__(self, server_url: str, timeout: float = 15.0) -> None:
        self._url = server_url.rstrip("/")
        self._timeout = timeout
        self._schemas: list[dict] = []

    @property
    def url(self) -> str:
        return self._url

    def discover_tools(self) -> list[dict]:
        """Fetch the tool list from the MCP server via tools/list."""
        try:
            resp = _post_json(self._url, _jsonrpc("tools/list", {}), timeout=self._timeout)
            self._schemas = resp.get("result", {}).get("tools", [])
            logger.info("MCPClient[%s]: discovered %d tool(s).", self._url, len(self._schemas))
        except Exception as exc:
            logger.error("MCPClient[%s]: discovery failed — %s", self._url, exc)
            self._schemas = []
        return self._schemas

    def call_tool(self, tool_name: str, **kwargs: Any) -> str:
        """Call a remote MCP tool and return the text result."""
        try:
            resp = _post_json(
                self._url,
                _jsonrpc("tools/call", {"name": tool_name, "arguments": kwargs}),
                timeout=self._timeout,
            )
            content = resp.get("result", {}).get("content", [])
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else str(resp.get("result", ""))
        except Exception as exc:
            return f"[MCP error] {exc}"

    def as_aetheerai_tools(self) -> dict[str, Callable]:
        """
        Return a dict mapping tool_name → callable compatible with
        ToolManager.register().  Auto-discovers if not yet done.
        """
        if not self._schemas:
            self.discover_tools()

        tools: dict[str, Callable] = {}
        for schema in self._schemas:
            name = schema.get("name", "")
            if not name:
                continue

            def _make_fn(n: str, description: str) -> Callable:
                def _fn(input: str = "", **kw: Any) -> str:  # noqa: A002
                    return self.call_tool(n, input=input, **kw)
                _fn.__name__ = f"mcp:{n}"
                _fn.__doc__ = description or f"MCP tool '{n}'"
                return _fn

            tools[name] = _make_fn(name, schema.get("description", ""))

        return tools


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

class MCPServer:
    """
    Minimal HTTP MCP server that exposes AetheerAI's registered tools to any
    MCP-compatible client.  Runs in a daemon thread — safe to start and forget.
    """

    def __init__(self, tool_manager, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._tools = tool_manager
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        tools_ref = self._tools

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # silence access logs
                pass

            def do_POST(self) -> None:  # noqa: N802
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length))
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return

                method = body.get("method", "")
                req_id = body.get("id", 1)
                result: dict = {}

                if method == "tools/list":
                    result = {
                        "tools": [
                            {
                                "name": n,
                                "description": getattr(fn, "__doc__", "") or "",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"input": {"type": "string"}},
                                },
                            }
                            for n, fn in tools_ref._tools.items()
                        ]
                    }
                elif method == "tools/call":
                    params = body.get("params", {})
                    name = params.get("name", "")
                    args = params.get("arguments", {})
                    try:
                        output = tools_ref.call(
                            name, **args, agent_name="mcp_caller", agent_level=1
                        )
                        result = {"content": [{"type": "text", "text": str(output)}]}
                    except Exception as exc:
                        result = {"content": [{"type": "text", "text": f"Error: {exc}"}]}

                response = json.dumps(
                    {"jsonrpc": "2.0", "id": req_id, "result": result}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response)

        self._server = HTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("MCPServer: listening on http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            logger.info("MCPServer: stopped.")


# ---------------------------------------------------------------------------
# A2A Client
# ---------------------------------------------------------------------------

class A2AClient:
    """
    HTTP client for the Google A2A protocol.

    Discovers an external agent's capabilities via its Agent Card at
    /.well-known/agent.json, then submits tasks via POST /tasks/send
    and returns the text response.

    Example::

        client = A2AClient("https://openai-researcher.example.com")
        client.discover()
        result = client.send_task("Summarise the top AI papers from 2025")
    """

    def __init__(self, agent_base_url: str, timeout: float = 30.0) -> None:
        self._base = agent_base_url.rstrip("/")
        self._timeout = timeout
        self._card: dict = {}

    def discover(self) -> dict:
        """Fetch the agent card from /.well-known/agent.json."""
        try:
            self._card = _get_json(
                f"{self._base}/.well-known/agent.json", timeout=self._timeout
            )
            logger.info(
                "A2AClient: connected to '%s' at %s.",
                self._card.get("name", "unknown"),
                self._base,
            )
        except Exception as exc:
            logger.error("A2AClient: discovery failed for %s — %s", self._base, exc)
        return self._card

    def send_task(self, task_text: str, session_id: str | None = None) -> str:
        """
        Submit a task to the remote A2A agent and block until complete.
        Returns the agent's text response.
        """
        import uuid

        task_id = str(uuid.uuid4())
        payload = {
            "id": task_id,
            "sessionId": session_id or task_id,
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task_text}],
            },
        }
        try:
            resp = _post_json(f"{self._base}/tasks/send", payload, timeout=self._timeout)
            parts = (
                resp.get("result", {})
                    .get("status", {})
                    .get("message", {})
                    .get("parts", [])
            )
            texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
            return "\n".join(texts) if texts else str(resp)
        except Exception as exc:
            return f"[A2A error] {exc}"

    @property
    def name(self) -> str:
        return self._card.get("name", self._base)

    @property
    def capabilities(self) -> list[str]:
        return self._card.get("capabilities", [])

    @property
    def base_url(self) -> str:
        return self._base


# ---------------------------------------------------------------------------
# A2A Server
# ---------------------------------------------------------------------------

class A2AServer:
    """
    Minimal A2A-compliant HTTP server exposing AetheerAI as an agent endpoint.

    External agents can:
    - GET  /.well-known/agent.json  → discover capabilities
    - POST /tasks/send              → submit a task and receive a result

    Runs in a daemon thread.

    Example::

        server = A2AServer(workflow_engine, registry, port=8766)
        server.start()
    """

    def __init__(
        self,
        workflow_engine,
        registry,
        host: str = "0.0.0.0",
        port: int = 8766,
        agent_name: str = "AetheerAI",
        description: str = "AetheerAI Master Agent — multi-agent AI orchestration.",
    ) -> None:
        self._engine = workflow_engine
        self._registry = registry
        self._host = host
        self._port = port
        self._card = {
            "name": agent_name,
            "description": description,
            "version": "1.0.0",
            "url": f"http://{host}:{port}",
            "capabilities": ["tasks/send"],
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
        }
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        card = self._card
        engine = self._engine
        registry = self._registry

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/.well-known/agent.json":
                    body = json.dumps(card).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/tasks/send":
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length))
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return

                task_id = body.get("id", "unknown")
                parts = body.get("message", {}).get("parts", [])
                task_text = " ".join(
                    p.get("text", "") for p in parts if p.get("type") == "text"
                ).strip()

                # Route to the first registered agent
                agent_names = registry.list_names()
                if agent_names:
                    agent = registry.get(agent_names[0])
                    try:
                        result_text = engine.execute(agent, task_text)
                    except Exception as exc:
                        result_text = f"Error: {exc}"
                else:
                    result_text = "No agents registered in AetheerAI."

                response = json.dumps({
                    "id": task_id,
                    "status": {
                        "state": "completed",
                        "message": {
                            "role": "agent",
                            "parts": [{"type": "text", "text": result_text}],
                        },
                    },
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response)

        self._server = HTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("A2AServer: listening on http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            logger.info("A2AServer: stopped.")


# ---------------------------------------------------------------------------
# InteropBridge — unified facade
# ---------------------------------------------------------------------------

class InteropBridge:
    """
    High-level facade that provides a single interoperability surface for:
    - Importing tools from external MCP servers
    - Exposing AetheerAI tools as an MCP server
    - Delegating tasks to external A2A agents
    - Accepting tasks from external A2A agents

    Attach to AetheerAiKernel as:
        kernel.interop = InteropBridge(kernel.tool_manager,
                                        kernel.workflow_engine,
                                        kernel.registry)
    """

    def __init__(self, tool_manager, workflow_engine, registry) -> None:
        self._tools = tool_manager
        self._engine = workflow_engine
        self._registry = registry

        self._mcp_server: MCPServer | None = None
        self._a2a_server: A2AServer | None = None
        self._mcp_clients: dict[str, MCPClient] = {}
        self._a2a_clients: dict[str, A2AClient] = {}

    # ── MCP ────────────────────────────────────────────────────────────

    def connect_mcp_server(self, server_url: str, namespace: str | None = None) -> int:
        """
        Connect to an external MCP server and import its tools into
        AetheerAI's ToolManager.  Returns the count of imported tools.

        Tools are registered as "<namespace>:<original_name>" when a
        namespace is provided, or "<original_name>" otherwise.
        """
        client = MCPClient(server_url)
        raw_tools = client.as_aetheerai_tools()
        prefix = f"{namespace}:" if namespace else ""
        for raw_name, fn in raw_tools.items():
            self._tools.register(f"{prefix}{raw_name}", fn)
        self._mcp_clients[server_url] = client
        logger.info(
            "InteropBridge: imported %d tool(s) from MCP server %s.",
            len(raw_tools), server_url,
        )
        return len(raw_tools)

    def start_mcp_server(self, host: str = "0.0.0.0", port: int = 8765) -> MCPServer:
        """Expose AetheerAI's tools as an MCP server endpoint."""
        self._mcp_server = MCPServer(self._tools, host=host, port=port)
        self._mcp_server.start()
        return self._mcp_server

    # ── A2A ────────────────────────────────────────────────────────────

    def connect_a2a_agent(self, base_url: str) -> A2AClient:
        """
        Connect to an external A2A agent.  Discovers its Agent Card and
        caches the client for subsequent task delegation.
        """
        client = A2AClient(base_url)
        client.discover()
        self._a2a_clients[base_url] = client
        logger.info(
            "InteropBridge: connected to A2A agent '%s' at %s.",
            client.name, base_url,
        )
        return client

    def delegate_task(self, agent_url: str, task: str) -> str:
        """
        Delegate a task to a connected A2A agent.
        Auto-connects if the URL has not been seen before.
        """
        if agent_url not in self._a2a_clients:
            self.connect_a2a_agent(agent_url)
        return self._a2a_clients[agent_url].send_task(task)

    def start_a2a_server(
        self,
        host: str = "0.0.0.0",
        port: int = 8766,
        agent_name: str = "AetheerAI",
    ) -> A2AServer:
        """Expose AetheerAI as an A2A-compliant agent endpoint."""
        self._a2a_server = A2AServer(
            self._engine,
            self._registry,
            host=host,
            port=port,
            agent_name=agent_name,
        )
        self._a2a_server.start()
        return self._a2a_server

    def stop_all_servers(self) -> None:
        """Shut down all running server threads."""
        if self._mcp_server:
            self._mcp_server.stop()
        if self._a2a_server:
            self._a2a_server.stop()

    # ── Discovery / status ────────────────────────────────────────────

    def list_connected_agents(self) -> list[dict]:
        """Return metadata for all connected A2A agents."""
        return [
            {
                "type": "A2A",
                "url": url,
                "name": c.name,
                "capabilities": c.capabilities,
            }
            for url, c in self._a2a_clients.items()
        ]

    def list_mcp_sources(self) -> list[str]:
        """Return URLs of all connected MCP tool servers."""
        return list(self._mcp_clients.keys())

    def status(self) -> dict:
        return {
            "mcp_server_running": self._mcp_server is not None,
            "a2a_server_running": self._a2a_server is not None,
            "mcp_sources": self.list_mcp_sources(),
            "a2a_agents": [c.name for c in self._a2a_clients.values()],
        }
