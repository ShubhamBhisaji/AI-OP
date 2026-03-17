"""
launcher.py -- AetheerAI — An AI Master!!  |  Silent GUI Launcher

Double-click this (or its compiled .exe) to:
  1. Show a welcome splash window
  2. Start the Streamlit dashboard silently in the background
  3. Open the browser automatically when the server is ready
  4. Keep running (browser stays alive as long as this process is alive)

Compile to a no-console .exe with:  build_main_exe.bat
"""
from __future__ import annotations

import multiprocessing
import os
import shutil
import sys
import subprocess
import threading
import time
import webbrowser
import socket
import tkinter as tk
from tkinter import ttk

# Bug 4 fix — Multiprocessing / PyInstaller infinite-window crash:
# freeze_support() MUST be called before any other code runs when the module
# is re-imported by a child process spawned by multiprocessing on Windows.
# Place it here (module level) so it fires even before __name__ == '__main__'.
multiprocessing.freeze_support()


# ── .env helpers ─────────────────────────────────────────────────────────
_PLACEHOLDER_VALUES = {
    "your_github_token_here", "your_openai_key_here",
    "your_anthropic_key_here", "your_gemini_key_here",
    "",
}

_PROVIDER_CHOICES = [
    ("GitHub Models",    "GITHUB_TOKEN"),
    ("OpenAI",           "OPENAI_API_KEY"),
    ("Anthropic Claude", "ANTHROPIC_API_KEY"),
    ("Google Gemini",    "GEMINI_API_KEY"),
]


def _get_env_path() -> str:
    """Return the .env path for frozen exe or source-run mode."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), ".env")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, ".env")


def _load_env_file(path: str) -> None:
    """Minimal .env loader — sets os.environ for keys not already present."""
    if not os.path.isfile(path):
        return
    import re
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = rest.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        else:
            value = re.sub(r'\s+#.*$', '', value)
        if key not in os.environ:
            os.environ[key] = value


def _has_valid_key() -> bool:
    """Return True if at least one provider API key is configured."""
    for _, env_key in _PROVIDER_CHOICES:
        val = os.environ.get(env_key, "")
        if val and val not in _PLACEHOLDER_VALUES:
            return True
    return False


def _save_key_to_env(env_path: str, key: str, value: str) -> None:
    """Write (or update) a KEY=value line in the .env file."""
    import re
    try:
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        key_re = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
        replaced = False
        for i, line in enumerate(lines):
            if key_re.match(line):
                lines[i] = f"{key}={value}\n"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.environ[key] = value
    except OSError:
        pass


class EnvSetupDialog:
    """
    Tkinter dialog shown at startup when no API key is configured.
    Lets the user pick a provider, enter their key, and save it to .env.
    """

    def __init__(self, env_path: str):
        self._env_path = env_path
        self._result: str = "skip"  # "saved" | "ollama" | "skip"

        self._root = tk.Tk()
        self._root.title("AetheerAI — Setup")
        self._root.resizable(False, False)
        self._root.configure(bg="#0e1117")
        self._root.protocol("WM_DELETE_WINDOW", self._on_skip)

        w, h = 480, 370
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build_ui()

    def _build_ui(self) -> None:
        root = self._root
        f = tk.Frame(root, bg="#0e1117", padx=28, pady=24)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="⚡", font=("Segoe UI", 32),
                 bg="#0e1117", fg="#3b82f6").pack()
        tk.Label(f, text="AetheerAI — First-Run Setup",
                 font=("Segoe UI", 16, "bold"),
                 bg="#0e1117", fg="#ffffff").pack(pady=(4, 2))
        tk.Label(f, text="No API key found. Configure one to enable AI features.",
                 font=("Segoe UI", 9), bg="#0e1117", fg="#94a3b8").pack()

        # Provider dropdown
        pf = tk.Frame(f, bg="#0e1117")
        pf.pack(fill="x", pady=(16, 4))
        tk.Label(pf, text="AI Provider:", font=("Segoe UI", 9, "bold"),
                 bg="#0e1117", fg="#cbd5e1", width=14, anchor="w").pack(side="left")
        self._provider_var = tk.StringVar(value=_PROVIDER_CHOICES[0][0])
        provider_menu = ttk.Combobox(
            pf, textvariable=self._provider_var,
            values=[p[0] for p in _PROVIDER_CHOICES],
            state="readonly", font=("Segoe UI", 9), width=28,
        )
        provider_menu.pack(side="left", padx=(4, 0))

        # API key field
        kf = tk.Frame(f, bg="#0e1117")
        kf.pack(fill="x", pady=4)
        tk.Label(kf, text="API Key:", font=("Segoe UI", 9, "bold"),
                 bg="#0e1117", fg="#cbd5e1", width=14, anchor="w").pack(side="left")
        self._key_var = tk.StringVar()
        self._key_entry = tk.Entry(
            kf, textvariable=self._key_var, show="•",
            font=("Segoe UI", 9), bg="#1e293b", fg="#e2e8f0",
            insertbackground="#e2e8f0", relief="flat",
            highlightthickness=1, highlightbackground="#334155",
            width=30,
        )
        self._key_entry.pack(side="left", padx=(4, 4), ipady=4)
        self._show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            kf, text="Show", variable=self._show_var,
            command=self._toggle_show,
            bg="#0e1117", fg="#94a3b8", selectcolor="#1e293b",
            activebackground="#0e1117", font=("Segoe UI", 8),
        ).pack(side="left")

        # .env path hint
        tk.Label(f, text=f"Saved to: {self._env_path}",
                 font=("Segoe UI", 7), bg="#0e1117", fg="#475569").pack(pady=(2, 12))

        # Buttons
        bf = tk.Frame(f, bg="#0e1117")
        bf.pack()
        tk.Button(
            bf, text="Save & Start", command=self._on_save,
            bg="#3b82f6", fg="white", relief="flat",
            font=("Segoe UI", 9, "bold"), padx=14, pady=6,
            cursor="hand2", activebackground="#2563eb", activeforeground="white",
        ).pack(side="left", padx=4)
        tk.Button(
            bf, text="Use Ollama (local, free)", command=self._on_ollama,
            bg="#1e293b", fg="#60a5fa", relief="flat",
            font=("Segoe UI", 9), padx=14, pady=6,
            cursor="hand2", activebackground="#334155", activeforeground="#60a5fa",
        ).pack(side="left", padx=4)
        tk.Button(
            bf, text="Skip", command=self._on_skip,
            bg="#1e293b", fg="#94a3b8", relief="flat",
            font=("Segoe UI", 9), padx=10, pady=6,
            cursor="hand2", activebackground="#334155", activeforeground="#94a3b8",
        ).pack(side="left", padx=4)

        self._status_var = tk.StringVar()
        tk.Label(f, textvariable=self._status_var,
                 font=("Segoe UI", 8), bg="#0e1117", fg="#ef4444").pack(pady=(8, 0))

    def _toggle_show(self) -> None:
        self._key_entry.config(show="" if self._show_var.get() else "•")

    def _on_save(self) -> None:
        key_val = self._key_var.get().strip()
        if not key_val or key_val in _PLACEHOLDER_VALUES:
            self._status_var.set("Please enter a valid API key.")
            return
        provider_name = self._provider_var.get()
        env_key = next(ek for pn, ek in _PROVIDER_CHOICES if pn == provider_name)
        _save_key_to_env(self._env_path, env_key, key_val)
        self._result = "saved"
        self._root.destroy()

    def _on_ollama(self) -> None:
        os.environ["AI_PROVIDER"] = "ollama"
        self._result = "ollama"
        self._root.destroy()

    def _on_skip(self) -> None:
        self._result = "skip"
        self._root.destroy()

    def run(self) -> str:
        """Show the dialog and return 'saved', 'ollama', or 'skip'."""
        self._root.mainloop()
        return self._result


def find_free_port() -> int:
    """Find an available TCP port so a stale process never blocks re-launch (Bug 4 fix)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


_PORT = find_free_port()   # dynamically assigned — never clashes with a stale instance
_HOST = "127.0.0.1"
_URL  = f"http://{_HOST}:{_PORT}"

# ── Resolve paths whether running as .py or PyInstaller .exe ─────────────
if getattr(sys, "_MEIPASS", None):
    _ROOT = sys._MEIPASS
else:
    _ROOT = os.path.dirname(os.path.abspath(__file__))

os.chdir(_ROOT)
sys.path.insert(0, _ROOT)


def _port_open(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


class _StreamlitHandle:
    """
    Duck-typed Popen wrapper around a stcli daemon thread.
    Implements the .poll() / .terminate() / .wait() API that the splash
    window and tray use, so the rest of main() can stay unchanged.
    """
    def __init__(self, t: threading.Thread) -> None:
        self._t = t

    def poll(self):
        """Return None when running, 0 when the thread has exited."""
        return None if self._t.is_alive() else 0

    def terminate(self) -> None:
        """No-op: daemon thread exits automatically when the main process ends."""

    def wait(self) -> None:
        """Block until the Streamlit thread finishes."""
        self._t.join()


def _patch_frozen_streamlit() -> None:
    """
    Apply all patches needed to run Streamlit inside a daemon thread in a
    frozen PyInstaller .exe.  Safe no-op when running from source.

    Patch 1 — importlib.metadata.version():
        streamlit/version.py calls version('streamlit') at import time.
        PyInstaller doesn't bundle .dist-info by default, so this raises
        PackageNotFoundError.  We wrap version() to return '0.0.0' for any
        package whose metadata is missing.  Streamlit only uses the version
        string for the About dialog — no functional impact.

    Patch 2 — signal.signal():
        streamlit/web/bootstrap.py calls signal.signal() inside run_server()
        via _set_up_signal_handler().  The stdlib enforces that signal
        handlers can only be registered from the main thread of the main
        interpreter.  Running stcli.main() in our daemon thread always
        triggers  ValueError: signal only works in main thread.
        We wrap signal.signal() to silently skip registration when called
        from a non-main thread — Streamlit shuts down via asyncio cancellation
        anyway, so missing SIGTERM/SIGINT handlers in the thread are harmless.
    """
    if not getattr(sys, "frozen", False):
        return

    # ── Patch 1: metadata ──────────────────────────────────────────────────
    # Wrap importlib.metadata.version() to return '0.0.0' for any package
    # whose .dist-info was not bundled by PyInstaller.
    try:
        import importlib.metadata as _imd
        _orig_version = _imd.version

        def _safe_version(pkg: str) -> str:  # type: ignore[override]
            try:
                return _orig_version(pkg)
            except _imd.PackageNotFoundError:
                return "0.0.0"

        _imd.version = _safe_version  # type: ignore[assignment]
        # Also patch requires() / metadata() used by some packages
        _orig_requires = _imd.requires

        def _safe_requires(pkg: str):  # type: ignore[override]
            try:
                return _orig_requires(pkg)
            except _imd.PackageNotFoundError:
                return []

        _imd.requires = _safe_requires  # type: ignore[assignment]
    except Exception:  # noqa: BLE001
        pass

    # ── Patch 2: signal ────────────────────────────────────────────────────
    try:
        import signal as _signal
        import threading as _threading
        _orig_signal = _signal.signal

        def _safe_signal(sig, handler):  # type: ignore[override]
            if _threading.current_thread() is _threading.main_thread():
                return _orig_signal(sig, handler)
            # Called from daemon thread — silently skip; asyncio handles shutdown

        _signal.signal = _safe_signal  # type: ignore[assignment]
    except Exception:  # noqa: BLE001
        pass


def _stcli_thread() -> None:
    """Thread target: invoke Streamlit via its bundled CLI entry point."""
    # Apply frozen-mode patches BEFORE the first streamlit import.
    _patch_frozen_streamlit()
    try:
        try:
            from streamlit.web import cli as stcli   # Streamlit >= 1.12
        except ImportError:
            from streamlit import cli as stcli        # older layout
        stcli.main()
    except SystemExit:
        pass  # stcli always calls sys.exit() on shutdown — harmless in a thread
    except Exception:  # noqa: BLE001
        # Log to a file next to the exe so the user can diagnose the crash
        log_path = os.path.join(os.path.dirname(sys.executable)
                                if getattr(sys, "frozen", False)
                                else _ROOT, "aetheerai_error.log")
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                import traceback
                fh.write("\n--- Streamlit thread crash ---\n")
                traceback.print_exc(file=fh)
        except OSError:
            pass


def _start_streamlit():
    """
    Start Streamlit and return a handle with a Popen-compatible API.

    Bug 1 fix — “File Not Found” crash in frozen .exe:
      PyInstaller extracts the app into sys._MEIPASS (a hidden temp folder).
      If we spawn a subprocess with the *system* Python it cannot find
      aetheerai_kernel, streamlit, or any other bundled package — instant crash.
      The fix: when frozen, call stcli.main() inside the SAME process in a
      daemon thread.  That thread inherits the full bundled sys.path and
      sees every package that was compiled into the .exe.

      Dev mode (not frozen) is unchanged: subprocess.Popen with sys.executable.
    """
    app_path = os.path.join(_ROOT, "app.py")

    if getattr(sys, "frozen", False):
        # ── Frozen .exe: use bundled Streamlit directly (no subprocess) ────────
        sys.argv = [
            "streamlit", "run", app_path,
            f"--server.port={_PORT}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            f"--server.address={_HOST}",
            "--global.developmentMode=false",
        ]
        t = threading.Thread(target=_stcli_thread, daemon=True)
        t.start()
        return _StreamlitHandle(t)

    # ── Dev / plain-Python: original subprocess approach ──────────────────
    kwargs: dict = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", app_path,
            "--server.port", str(_PORT),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
            "--server.address", _HOST,
        ],
        cwd=_ROOT,
        env=env,
        **kwargs,
    )


class SplashWindow:
    """Welcome splash that shows while Streamlit is booting."""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("AetheerAI — An AI Master!!")
        root.resizable(False, False)
        root.configure(bg="#0e1117")

        # Center on screen
        w, h = 480, 300
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        # Remove title bar decorations for a clean splash look
        root.overrideredirect(True)

        # ── Content ───────────────────────────────────────────────────
        frame = tk.Frame(root, bg="#0e1117", padx=30, pady=30)
        frame.pack(fill="both", expand=True)

        # Lightning bolt + title
        tk.Label(
            frame, text="⚡", font=("Segoe UI", 48),
            bg="#0e1117", fg="#3b82f6",
        ).pack()

        tk.Label(
            frame,
            text="Welcome to AetheerAI",
            font=("Segoe UI", 22, "bold"),
            bg="#0e1117", fg="#ffffff",
        ).pack(pady=(4, 0))

        tk.Label(
            frame,
            text="An AI Master!!",
            font=("Segoe UI", 13),
            bg="#0e1117", fg="#60a5fa",
        ).pack()

        tk.Label(
            frame,
            text="Advanced AI Operating System",
            font=("Segoe UI", 9),
            bg="#0e1117", fg="#64748b",
        ).pack(pady=(2, 16))

        # Status label
        self.status_var = tk.StringVar(value="Starting up...")
        tk.Label(
            frame,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            bg="#0e1117", fg="#94a3b8",
        ).pack()

        # Progress bar
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor="#1e293b",
            background="#3b82f6",
            thickness=6,
        )
        self.progress = ttk.Progressbar(
            frame, style="Blue.Horizontal.TProgressbar",
            orient="horizontal", length=380, mode="indeterminate",
        )
        self.progress.pack(pady=(10, 0))
        self.progress.start(12)

        # Drag support (since title bar is hidden)
        frame.bind("<Button-1>", self._start_drag)
        frame.bind("<B1-Motion>", self._on_drag)
        for child in frame.winfo_children():
            child.bind("<Button-1>", self._start_drag)
            child.bind("<B1-Motion>", self._on_drag)

        self._drag_x = 0
        self._drag_y = 0

    def _start_drag(self, e):
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _on_drag(self, e):
        self.root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    def set_status(self, msg: str):
        self.status_var.set(msg)
        self.root.update_idletasks()

    def close(self):
        self.progress.stop()
        self.root.destroy()


def _wait_and_open(splash: SplashWindow, proc: subprocess.Popen, root: tk.Tk):
    """Background thread: wait for Streamlit to be ready, then open browser."""
    splash.set_status("Booting AetheerAI kernel...")
    time.sleep(1)

    # Poll until Streamlit is listening (max 60 s)
    for i in range(120):
        if proc.poll() is not None:
            # Process died unexpectedly
            root.after(0, lambda: splash.set_status("Startup error — check your .env file"))
            time.sleep(3)
            root.after(0, root.destroy)
            return
        if _port_open(_HOST, _PORT):
            break
        status = f"Loading{'.' * ((i % 3) + 1)}"
        root.after(0, lambda s=status: splash.set_status(s))
        time.sleep(0.5)

    root.after(0, lambda: splash.set_status("Opening browser..."))
    time.sleep(0.4)
    webbrowser.open(_URL)

    # Close splash after browser opens
    time.sleep(0.8)
    root.after(0, splash.close)


def main():
    # ── Pre-flight: load .env and check for a valid API key ───────────────
    env_path = _get_env_path()
    _load_env_file(env_path)

    if not _has_valid_key():
        dlg = EnvSetupDialog(env_path)
        result = dlg.run()
        # Re-load .env in case the user just saved a key
        if result == "saved":
            _load_env_file(env_path)

    # Start Streamlit silently in background
    proc = _start_streamlit()

    # Build splash window
    root = tk.Tk()
    splash = SplashWindow(root)

    # Boot watcher in background thread
    t = threading.Thread(target=_wait_and_open, args=(splash, proc, root), daemon=True)
    t.start()

    # Run splash (blocks until splash.close() is called)
    root.mainloop()

    # Splash closed — keep process alive so Streamlit keeps running
    # Show a minimal system-tray-style notice
    try:
        tray = tk.Tk()
        tray.withdraw()  # invisible — just keeps the process alive
        tray.title("AetheerAI running")

        def _quit():
            proc.terminate()
            tray.destroy()

        # Watch for Streamlit exiting (e.g. stopped from browser button)
        def _watch_proc():
            proc.wait()
            tray.after(0, tray.destroy)
        threading.Thread(target=_watch_proc, daemon=True).start()

        # Simple "still running" notification then invisible
        tray.after(500, tray.deiconify)
        tray.resizable(False, False)
        tray.configure(bg="#0e1117")
        tw, th = 320, 110
        sw = tray.winfo_screenwidth()
        sh = tray.winfo_screenheight()
        tray.geometry(f"{tw}x{th}+{(sw-tw)//2}+{(sh-th)//2}")
        tray.overrideredirect(True)

        tf = tk.Frame(tray, bg="#0e1117", padx=16, pady=14)
        tf.pack(fill="both", expand=True)
        tk.Label(tf, text="⚡ AetheerAI is running",
                 font=("Segoe UI", 11, "bold"), bg="#0e1117", fg="#60a5fa").pack()
        tk.Label(tf, text=f"Dashboard → {_URL}",
                 font=("Segoe UI", 9), bg="#0e1117", fg="#94a3b8").pack(pady=(4, 10))
        tk.Button(tf, text="Stop AetheerAI", command=_quit,
                  bg="#ef4444", fg="white", relief="flat",
                  font=("Segoe UI", 9), padx=12, pady=4,
                  cursor="hand2").pack()

        tray.mainloop()
    except Exception:
        # Fallback: just keep the process alive
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()

    # If Streamlit was stopped from the browser, also close the tray
    proc.terminate()


if __name__ == "__main__":
    main()
