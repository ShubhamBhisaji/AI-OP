"""AetheerAI.tools — built-in tool implementations.

IMPORTANT — Enforcement Gate
============================
Installing the _ToolImportHook here ensures that every tools.* sub-module
imported anywhere in the process (ToolManager, skills, scripts, tests) has its
public callables replaced with _GatedCallable wrappers.  Direct imports such
as ``from tools.email_tool import email_tool; email_tool(...)`` are therefore
routed through EnforcementGate before executing — making policy enforcement
architecturally non-bypassable.
"""

from security.enforcement_gate import install_tool_import_hook as _install_hook

# Install once at package load time.  Retroactively patches any tool modules
# that were already in sys.modules before this __init__ ran.
_install_hook()
