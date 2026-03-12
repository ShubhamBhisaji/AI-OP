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

_PORT = 8501
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


def _find_python() -> str:
    """
    Return the correct Python interpreter path.

    Bug 4 fix: when frozen, sys.executable is the .exe itself — passing it to
    subprocess would re-launch AetheerAI instead of running Python.  Look for
    a real python.exe on PATH instead.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable  # plain py script: sys.executable IS python
    # Frozen .exe: find the real Python on PATH
    for candidate in ("python", "python3"):
        found = shutil.which(candidate)
        if found:
            return found
    # Absolute last resort — will fail with a clear error message at runtime
    return "python"


def _start_streamlit() -> subprocess.Popen:
    """Launch streamlit run app.py as a hidden background process."""
    python = _find_python()
    app_path = os.path.join(_ROOT, "app.py")

    kwargs: dict = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # On Windows hide the console window entirely
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
            python, "-m", "streamlit", "run", app_path,
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
