"""
PluginLoader — Marketplace-style tool plugin system for AetheerAI.

Enables third-party and custom tools to be dropped into tools/plugins/
without modifying core code — the equivalent of an "app store" for tools.

Plugin Layout
-------------
tools/plugins/
  my_plugin/
    plugin_manifest.json     ← required descriptor
    my_plugin.py             ← entry module

Manifest Schema
---------------
{
  "name":             "my_custom_tool",          // registry key (no spaces)
  "version":          "1.0.0",
  "description":      "Does X when given Y",
  "entry":            "my_plugin.py",            // relative to plugin dir
  "function":         "run",                     // callable name inside entry
  "permission_level": 2,                         // 0-3 (same as tool_manager)
  "author":           "optional",
  "tags":             ["optional", "keywords"]
}

Security
--------
- Plugins run in-process but their permission_level is enforced by ToolManager.
- Manifests with permission_level > 3 are rejected.
- Plugin code is imported under its own module namespace to avoid collisions.
- Only plugins whose manifests pass schema validation are loaded.
- A sandboxed mode (sandbox=True) wraps each call in a subprocess via
  subprocess.run() with a timeout, capturing only stdout as the result.
  This prevents a buggy plugin from crashing the host process.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PLUGINS_DIR = Path(__file__).parent / "plugins"
_MANIFEST_FILE = "plugin_manifest.json"
_TRUSTED_REGISTRY = "trusted_plugins.json"
_MAX_PERMISSION_LEVEL = 3
_SANDBOX_TIMEOUT_SEC = 30
_TRUST_ALL = os.getenv("AETHEER_PLUGIN_TRUST_ALL", "").lower() in ("1", "true", "yes")


class PluginValidationError(Exception):
    """Raised when a plugin manifest fails validation."""



class PluginRecord:
    __slots__ = ("name", "version", "description", "permission_level",
                 "tags", "entry_path", "function_name", "callable_ref", "sandboxed")

    def __init__(
        self,
        *,
        name: str,
        version: str,
        description: str,
        permission_level: int,
        tags: list[str],
        entry_path: Path,
        function_name: str,
        callable_ref: Callable,
        sandboxed: bool = False,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.permission_level = permission_level
        self.tags = tags
        self.entry_path = entry_path
        self.function_name = function_name
        self.callable_ref = callable_ref
        self.sandboxed = sandboxed

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "permission_level": self.permission_level,
            "tags": self.tags,
            "entry": str(self.entry_path),
            "function": self.function_name,
            "sandboxed": self.sandboxed,
        }


class PluginLoader:
    """
    Scans a plugins directory, validates manifests, imports tool functions,
    and registers them with the ToolManager.

    Usage
    -----
    loader = PluginLoader(tool_manager)
    loaded = loader.load_all()          # scan & register all valid plugins
    loader.reload()                     # hot-reload (unregister + re-scan)
    loader.list_plugins()               # returns metadata of loaded plugins
    """

    def __init__(self, tool_manager, plugins_dir: Path | str | None = None) -> None:
        self.tool_manager = tool_manager
        self.plugins_dir = Path(plugins_dir) if plugins_dir else _PLUGINS_DIR
        self._loaded: dict[str, PluginRecord] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def load_all(self, *, sandbox: bool = True) -> list[str]:
        """
        Scan the plugins directory, load all valid plugins, and register them
        with the ToolManager.  Returns a list of successfully loaded plugin names.
        """
        if not self.plugins_dir.exists():
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            logger.info("PluginLoader: created plugins directory at %s", self.plugins_dir)
            return []

        loaded_names: list[str] = []
        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / _MANIFEST_FILE
            if not manifest_path.exists():
                logger.debug("PluginLoader: skipping %s (no manifest)", plugin_dir.name)
                continue
            try:
                record = self._load_plugin(plugin_dir, manifest_path, sandbox=sandbox)
                self._register(record)
                loaded_names.append(record.name)
            except PluginValidationError as exc:
                logger.warning("PluginLoader: plugin '%s' validation error: %s", plugin_dir.name, exc)
            except Exception as exc:
                logger.error("PluginLoader: failed to load plugin '%s': %s", plugin_dir.name, exc)

        logger.info("PluginLoader: loaded %d plugin(s): %s", len(loaded_names), loaded_names)
        return loaded_names

    def reload(self, *, sandbox: bool = True) -> list[str]:
        """Unregister all currently loaded plugins and re-scan the directory."""
        with self._lock:
            for name in list(self._loaded.keys()):
                self._unregister(name)
        return self.load_all(sandbox=sandbox)

    def load_single(self, plugin_dir: str | Path, *, sandbox: bool = True) -> str:
        """Load and register a single plugin by its directory path."""
        plugin_dir = Path(plugin_dir)
        manifest_path = plugin_dir / _MANIFEST_FILE
        if not manifest_path.exists():
            raise FileNotFoundError(f"No manifest found at {manifest_path}")
        record = self._load_plugin(plugin_dir, manifest_path, sandbox=sandbox)
        self._register(record)
        return record.name

    def unload(self, plugin_name: str) -> bool:
        """Unregister a plugin by name. Returns True if found and removed."""
        return self._unregister(plugin_name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return metadata for all currently loaded plugins."""
        with self._lock:
            return [rec.to_dict() for rec in self._loaded.values()]

    def get_plugin(self, name: str) -> PluginRecord | None:
        with self._lock:
            return self._loaded.get(name)

    # ── Internal loader ───────────────────────────────────────────────────

    def _load_plugin(
        self, plugin_dir: Path, manifest_path: Path, *, sandbox: bool
    ) -> PluginRecord:
        # 1. Parse and validate manifest
        manifest = self._validate_manifest(manifest_path)

        name = manifest["name"]
        entry_file = plugin_dir / manifest["entry"]
        function_name = manifest["function"]
        permission_level = int(manifest["permission_level"])

        if not entry_file.exists():
            raise PluginValidationError(f"Entry file '{entry_file}' not found.")

        # 2a. Trusted-plugin allow-list check
        if not _TRUST_ALL:
            trusted = self._load_trusted_registry()
            if trusted is not None and name not in trusted:
                raise PluginValidationError(
                    f"Plugin '{name}' is not in the trusted_plugins.json allow-list. "
                    f"Add it to {self.plugins_dir / _TRUSTED_REGISTRY} to enable loading."
                )
        else:
            logger.warning(
                "PluginLoader: AETHEER_PLUGIN_TRUST_ALL is enabled — "
                "skipping allow-list check for '%s'. Do NOT use in production.",
                name,
            )

        # 2b. SHA-256 hash verification (if manifest declares sha256)
        declared_hash = manifest.get("sha256")
        if declared_hash:
            actual_hash = hashlib.sha256(
                entry_file.read_bytes()
            ).hexdigest()
            if actual_hash != declared_hash:
                raise PluginValidationError(
                    f"SHA-256 mismatch for '{name}': manifest declares "
                    f"{declared_hash[:16]}… but file hashes to {actual_hash[:16]}…. "
                    f"The plugin file may have been tampered with."
                )

        # 2. Import the plugin module dynamically
        module_key = f"_aetheerai_plugin_{name}"
        if module_key in sys.modules:
            # Hot-reload: remove old module
            del sys.modules[module_key]

        spec = importlib.util.spec_from_file_location(module_key, entry_file)
        if spec is None or spec.loader is None:
            raise PluginValidationError(f"Cannot load module from '{entry_file}'.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        # 3. Get the callable
        if not hasattr(module, function_name):
            raise PluginValidationError(
                f"Module '{entry_file.name}' has no function '{function_name}'."
            )
        fn = getattr(module, function_name)
        if not callable(fn):
            raise PluginValidationError(
                f"'{function_name}' in '{entry_file.name}' is not callable."
            )

        # 4. Optionally wrap in sandbox (subprocess isolation)
        if sandbox:
            fn = self._make_sandbox_wrapper(entry_file, function_name, name)

        return PluginRecord(
            name=name,
            version=str(manifest.get("version", "0.0.0")),
            description=str(manifest.get("description", "")),
            permission_level=permission_level,
            tags=list(manifest.get("tags", [])),
            entry_path=entry_file,
            function_name=function_name,
            callable_ref=fn,
            sandboxed=sandbox,
        )

    def _register(self, record: PluginRecord) -> None:
        """Add plugin to tool_manager and internal registry."""
        with self._lock:
            if record.name in self._loaded:
                self._unregister(record.name)
            self._loaded[record.name] = record

        self.tool_manager.register_tool(
            name=record.name,
            fn=record.callable_ref,
            description=record.description,
            permission_level=record.permission_level,
        )
        logger.info(
            "PluginLoader: registered plugin '%s' v%s (level=%d, sandboxed=%s)",
            record.name, record.version, record.permission_level, record.sandboxed,
        )

    def _unregister(self, plugin_name: str) -> bool:
        with self._lock:
            if plugin_name not in self._loaded:
                return False
            del self._loaded[plugin_name]

        # Remove from tool_manager if it supports dynamic unregistration
        if hasattr(self.tool_manager, "unregister_tool"):
            self.tool_manager.unregister_tool(plugin_name)
        logger.info("PluginLoader: unregistered plugin '%s'.", plugin_name)
        return True

    # ── Sandbox wrapper ───────────────────────────────────────────────────

    def _make_sandbox_wrapper(
        self, entry_file: Path, function_name: str, plugin_name: str
    ) -> Callable:
        """Return a callable that runs the plugin in an isolated subprocess."""

        def sandboxed_call(**kwargs: Any) -> str:
            # Build a minimal runner script
            runner_script = (
                "import importlib.util, sys, json\n"
                f"spec = importlib.util.spec_from_file_location('plugin', {str(entry_file)!r})\n"
                "mod = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(mod)\n"
                f"fn = getattr(mod, {function_name!r})\n"
                f"kwargs = json.loads(sys.argv[1])\n"
                "result = fn(**kwargs)\n"
                "print(result)\n"
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(runner_script)
                tmp_path = tmp.name

            try:
                proc = subprocess.run(
                    [sys.executable, tmp_path, json.dumps(kwargs, default=str)],
                    capture_output=True,
                    text=True,
                    timeout=_SANDBOX_TIMEOUT_SEC,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Plugin '{plugin_name}' subprocess error: {proc.stderr[:500]}"
                    )
                return proc.stdout.strip()
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"Plugin '{plugin_name}' timed out after {_SANDBOX_TIMEOUT_SEC}s."
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        sandboxed_call.__name__ = f"{plugin_name}_sandboxed"
        return sandboxed_call

    # ── Trusted-plugin registry ─────────────────────────────────────────

    def _load_trusted_registry(self) -> set[str] | None:
        """Load the trusted_plugins.json allow-list. Returns None if file absent."""
        registry_path = self.plugins_dir / _TRUSTED_REGISTRY
        if not registry_path.exists():
            return None  # No registry = allow all (for backwards compatibility)
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "trusted" not in data:
                logger.warning("PluginLoader: invalid trusted_plugins.json format.")
                return set()
            return set(data["trusted"])
        except Exception as exc:
            logger.warning("PluginLoader: failed to read trusted registry: %s", exc)
            return set()  # Fail closed — deny all if registry is unreadable

    # ── Manifest validator ────────────────────────────────────────────────

    @staticmethod
    def _validate_manifest(manifest_path: Path) -> dict[str, Any]:
        try:
            raw = manifest_path.read_text(encoding="utf-8")
            manifest = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            raise PluginValidationError(f"Cannot read manifest: {exc}") from exc

        required = ("name", "entry", "function", "permission_level")
        missing = [k for k in required if k not in manifest]
        if missing:
            raise PluginValidationError(f"Manifest missing required fields: {missing}")

        name = str(manifest["name"]).strip()
        if not name or " " in name:
            raise PluginValidationError("Plugin name must be a non-empty string without spaces.")

        level = manifest["permission_level"]
        if not isinstance(level, int) or not (0 <= level <= _MAX_PERMISSION_LEVEL):
            raise PluginValidationError(
                f"permission_level must be an integer 0–{_MAX_PERMISSION_LEVEL}, got: {level!r}"
            )

        return manifest

    # ── Create example plugin scaffold ────────────────────────────────────

    def create_plugin_scaffold(self, plugin_name: str, description: str = "") -> Path:
        """
        Create a starter plugin directory with manifest and entry module.
        Use this to quickly scaffold new tool plugins.
        """
        plugin_dir = self.plugins_dir / plugin_name
        plugin_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "name": plugin_name,
            "version": "0.1.0",
            "description": description or f"{plugin_name} — custom AetheerAI tool plugin",
            "entry": f"{plugin_name}.py",
            "function": "run",
            "permission_level": 1,
            "author": "",
            "tags": [],
        }
        (plugin_dir / _MANIFEST_FILE).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        entry = plugin_dir / f"{plugin_name}.py"
        entry.write_text(
            f'"""{plugin_name} plugin for AetheerAI."""\n\n\n'
            f'def run(**kwargs) -> str:\n'
            f'    """Entry point called by AetheerAI ToolManager."""\n'
            f'    # TODO: implement {plugin_name} logic here\n'
            f'    return "Plugin {plugin_name}: not yet implemented"\n',
            encoding="utf-8",
        )
        logger.info("PluginLoader: created scaffold at %s", plugin_dir)
        return plugin_dir
