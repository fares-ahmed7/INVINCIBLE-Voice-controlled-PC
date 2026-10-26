"""
Executor: turns the AI's JSON command into a real action.
SAFE by design: only whitelisted actions/apps run. Nothing from the model is ever run as text.
Works on Windows and Linux.
"""
import os
import re
import subprocess
import sys
import webbrowser
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from ai.apps import APPS as _APPS, BROWSER_NAMES

IS_WIN = sys.platform.startswith("win")


def _spawn(cmd):
    """Start a program fully detached: its output stays out of our terminal,
    and it keeps running if this program exits (or Ctrl+C is pressed)."""
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if IS_WIN:
        kwargs["creationflags"] = 0x00000008 | 0x00000200 
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


# ---------- launching apps (with real success/failure detection) ----------
def _start_menu_dirs():
    for var in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(var)
        if base:
            d = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if d.is_dir():
                yield d


@lru_cache(maxsize=None)
def _find_shortcut(keyword: str):
    """Search Start Menu shortcuts (.lnk) for a keyword. Shortest name wins (skips 'uninstall')."""
    # lru_cache: the Start Menu rarely changes, so scan it only ONCE and reuse the result
    keyword = keyword.lower()
    best = None
    for d in _start_menu_dirs():
        for lnk in d.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if keyword in stem and "uninstall" not in stem:
                if best is None or len(stem) < len(best.stem):
                    best = lnk
    return best


def _uri_registered(scheme: str) -> bool:
    """True if Windows has a handler for scheme: (e.g. discord:)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme) as k:
            winreg.QueryValueEx(k, "URL Protocol")
        return True
    except (OSError, ImportError):
        return False


def _shell_open(target: str):
    """Open a URI/shortcut through explorer.exe, so the new app is NOT a child of our terminal
    (nothing it prints can leak here, and Ctrl+C can't kill it)."""
    _spawn(["explorer.exe", target])


def _launch_windows(app: str) -> bool:
    target, _, keyword = _APPS[app]

    # 1) Discord's own launcher (silent, fully detached)
    if app == "discord":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            upd = Path(local) / "Discord" / "Update.exe"
            if upd.exists():
                _spawn([str(upd), "--processStart", "Discord.exe"])
                return True

    # 2) URI targets (discord:, spotify:, ms-settings: ...) -> only if Windows has a handler
    if target.endswith(":"):
        if _uri_registered(target[:-1]):
            _shell_open(target)
            return True
    else:
        # 3) registered exe name (chrome.exe, calc.exe, winword.exe ...)
        try:
            os.startfile(target)
            return True
        except OSError:
            pass

    # 4) Start Menu shortcut
    lnk = _find_shortcut(keyword)
    if lnk:
        _shell_open(str(lnk))
        return True
    return False


def _launch_linux(app: str) -> bool:
    try:
        _spawn(_APPS[app][1])
        return True
    except (FileNotFoundError, OSError):
        return False


# ---------- browsers ----------
def _browser_path(browser: str):
    """Find a browser executable. Returns a path string or None."""
    import shutil
    if IS_WIN:
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = {
            "chrome": [pf + r"\Google\Chrome\Application\chrome.exe",
                       pf86 + r"\Google\Chrome\Application\chrome.exe",
                       local + r"\Google\Chrome\Application\chrome.exe"],
            "edge": [pf86 + r"\Microsoft\Edge\Application\msedge.exe",
                     pf + r"\Microsoft\Edge\Application\msedge.exe"],
            "firefox": [pf + r"\Mozilla Firefox\firefox.exe",
                        pf86 + r"\Mozilla Firefox\firefox.exe"],
        }
        for c in candidates.get(browser, []):
            if os.path.exists(c):
                return c
        return None
    names = {"chrome": "google-chrome", "edge": "microsoft-edge", "firefox": "firefox"}
    return shutil.which(names.get(browser, ""))


def _open_url(url: str, browser=None) -> str:
    """Open a URL. Returns the name of the browser used."""
    if browser:
        path = _browser_path(browser)
        if path:
            _spawn([path, url])      # list, no shell
            return browser
    webbrowser.open(url)
    return "default browser" + (f" ({browser} not found)" if browser else "")


# ---------- website whitelist: the model never supplies a URL ----------
SITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "facebook": "https://www.facebook.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "wikipedia": "https://www.wikipedia.org",
}
SEARCH_URLS = {
    "google": "https://www.google.com/search?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
}

KNOWN_FOLDERS = {"pictures", "documents", "downloads", "desktop", "music", "videos"}


def _clean_name(name: str) -> str:
    """Letters/digits/space/-/_ only (Arabic letters are allowed)."""
    name = re.sub(r"[^\w\s\-]", "", name or "", flags=re.UNICODE).strip()
    return name[:50]


def _open_path(path: Path):
    if IS_WIN:
        os.startfile(str(path))
    else:
        _spawn(["xdg-open", str(path)])


def _press_volume_key(vk: int, times: int = 5):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def _volume(direction: str):
    if IS_WIN:
        if direction == "mute":
            _press_volume_key(0xAD, 1)
        else:
            _press_volume_key(0xAF if direction == "up" else 0xAE, 5)  # 5 presses ~ 10%
    else:
        if direction == "mute":
            _spawn(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        else:
            sign = "+" if direction == "up" else "-"
            _spawn(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}10%"])


def execute(cmd: dict, confirm=input) -> str:
    """Run a command dict from understand_command(). Returns a message to show the user."""
    action = cmd.get("action")

    if action == "open_app":
        app = cmd.get("app")
        if app not in _APPS:
            return f"❌ Unknown app: {app}"
        ok = _launch_windows(app) if IS_WIN else _launch_linux(app)
        return f"✅ Opening {app}" if ok else f"❌ Could not open {app} (is it installed?)"

    if action == "web_search":
        query = (cmd.get("query") or "").strip()[:200]
        if not query:
            return "❌ Empty search"
        engine = cmd.get("engine") if cmd.get("engine") in SEARCH_URLS else "google"
        browser = cmd.get("browser") if cmd.get("browser") in BROWSER_NAMES else None
        used = _open_url(SEARCH_URLS[engine] + quote_plus(query), browser)   # domain fixed, query URL-encoded
        return f"🔎 Searching {engine} for: {query}  [{used}]"

    if action == "open_website":
        site = cmd.get("site")
        if site not in SITES:
            return f"❌ Website not allowed: {site}"
        _open_url(SITES[site])
        return f"🌐 Opening {site}"

    if action == "create_folder":
        name = _clean_name(cmd.get("name"))
        if not name:
            return "❌ Invalid folder name"
        path = Path.home() / "Desktop" / name if (Path.home() / "Desktop").exists() else Path.home() / name
        path.mkdir(exist_ok=True)
        return f"✅ Folder created: {path}"

    if action == "open_folder":
        name = _clean_name(cmd.get("name"))
        if not name:
            return "❌ Invalid folder name"
        path = Path.home() / (name.capitalize() if name.lower() in KNOWN_FOLDERS else name)
        if not path.is_dir():
            return f"❌ Folder not found: {path}"
        _open_path(path)
        return f"✅ Opening {path}"

    if action == "volume_up":
        _volume("up"); return "🔊 Volume up"
    if action == "volume_down":
        _volume("down"); return "🔉 Volume down"
    if action == "mute":
        _volume("mute"); return "🔇 Mute toggled"

    if action == "shutdown":
        if confirm("⚠️ Shut down the computer? (y/n): ").strip().lower() != "y":
            return "Cancelled"
        if IS_WIN:
            _spawn(["shutdown", "/s", "/t", "15"])
            return "⏻ Shutting down in 15s (cancel with: shutdown /a)"
        _spawn(["systemctl", "poweroff"])
        return "⏻ Shutting down"

    return "🤷 Didn't understand / unsupported command"
