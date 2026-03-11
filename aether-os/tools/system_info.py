"""system_info — Query information about the running system and environment."""
from __future__ import annotations
import os, sys, platform, logging
from pathlib import Path

logger = logging.getLogger(__name__)


def system_info(query: str = "all") -> str:
    """
    Return information about the current system.

    query : os | python | cpu | memory | disk | cwd | env | all

    Queries:
        os     : Operating system name and version.
        python : Python version and executable path.
        cpu    : CPU architecture and core count.
        memory : RAM usage (requires psutil — gracefully skipped if absent).
        disk   : Disk usage for the current drive.
        cwd    : Current working directory.
        env    : Safe subset of environment variables (PATH excluded).
        all    : All of the above.
    """
    query = (query or "all").strip().lower()

    def os_info():
        return (
            f"OS        : {platform.system()} {platform.release()}\n"
            f"Version   : {platform.version()}\n"
            f"Machine   : {platform.machine()}\n"
            f"Node      : {platform.node()}"
        )

    def python_info():
        return (
            f"Python    : {sys.version}\n"
            f"Executable: {sys.executable}\n"
            f"Prefix    : {sys.prefix}"
        )

    def cpu_info():
        arch = platform.processor() or platform.machine()
        try:
            import multiprocessing
            cores = multiprocessing.cpu_count()
        except Exception:
            cores = "unknown"
        return f"Arch      : {arch}\nCPU cores : {cores}"

    def memory_info():
        try:
            import psutil  # type: ignore
            vm = psutil.virtual_memory()
            return (
                f"Total  : {_human_size(vm.total)}\n"
                f"Used   : {_human_size(vm.used)} ({vm.percent}%)\n"
                f"Free   : {_human_size(vm.available)}"
            )
        except ImportError:
            return "Memory info unavailable (psutil not installed)."

    def disk_info():
        import shutil
        cwd = Path.cwd()
        try:
            usage = shutil.disk_usage(cwd)
            return (
                f"Drive  : {cwd.anchor}\n"
                f"Total  : {_human_size(usage.total)}\n"
                f"Used   : {_human_size(usage.used)} ({usage.used/usage.total*100:.1f}%)\n"
                f"Free   : {_human_size(usage.free)}"
            )
        except Exception as e:
            return f"Disk info unavailable: {e}"

    def cwd_info():
        return f"CWD: {Path.cwd()}"

    def env_info():
        # Only expose safe variables, never credentials/tokens
        safe_keys = [
            "COMPUTERNAME", "USERNAME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "LOCALAPPDATA", "APPDATA", "TEMP", "TMP",
            "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
            "SYSTEMDRIVE", "WINDIR", "PROGRAMFILES",
            "LANG", "LC_ALL", "TERM",
        ]
        lines = []
        for k in safe_keys:
            v = os.environ.get(k)
            if v is not None:
                lines.append(f"  {k:<28} = {v}")
        return "Environment (safe subset):\n" + ("\n".join(lines) if lines else "(none)")

    sections = {
        "os":     ("OS", os_info),
        "python": ("Python", python_info),
        "cpu":    ("CPU", cpu_info),
        "memory": ("Memory", memory_info),
        "disk":   ("Disk", disk_info),
        "cwd":    ("Working Directory", cwd_info),
        "env":    ("Environment", env_info),
    }

    if query in sections:
        label, fn = sections[query]
        return f"=== {label} ===\n{fn()}"

    if query == "all":
        parts = []
        for key, (label, fn) in sections.items():
            parts.append(f"=== {label} ===\n{fn()}")
        return "\n\n".join(parts)

    return f"Unknown query '{query}'. Use: os, python, cpu, memory, disk, cwd, env, all."


def _human_size(size: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
