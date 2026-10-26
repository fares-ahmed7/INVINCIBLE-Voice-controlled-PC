"""
Executor: turns the AI's JSON command into a real action.

SAFE by design: only whitelisted actions/apps run. Nothing from the model is ever run
as text or as a shell command. Windows-only build.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import webbrowser
from ctypes import POINTER, cast
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib.parse import quote_plus

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from ai.app_registry import ResolvedApp, resolve_app
from ai.apps import BROWSER_NAMES
from ai.sites import SEARCH_URLS, SITES

log = logging.getLogger(__name__)

# A confirmation callback: question -> user answer (input() in the real app, a stub in tests).
Confirm = Callable[[str], str]
# Every handler takes the command dict + the confirmation callback and returns a message.
Handler = Callable[[dict, Confirm], str]


def _spawn(cmd: Sequence[str]) -> subprocess.Popen:
    """Start a program fully detached: its output stays out of our terminal,
    and it keeps running if this program exits (or Ctrl+C is pressed). Windows-only build."""
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Detached process (no inherited console) + its own process group.
    kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    kwargs["close_fds"] = True
    return subprocess.Popen(cmd, **kwargs)


# ---------- launching apps (with real success/failure detection) ----------
def _start_menu_dirs() -> list[Path]:
    """The user's and the all-users Start Menu folders that exist on this PC."""
    dirs: list[Path] = []
    for var in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(var)
        if base:
            d = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            try:
                if d.is_dir():
                    dirs.append(d)
            except OSError as e:
                log.warning("could not access %s: %s", d, e)
    return dirs


@lru_cache(maxsize=None)
def _find_shortcut(keyword: str) -> Optional[Path]:
    """Search Start Menu shortcuts (.lnk) for a keyword. Shortest name wins (skips 'uninstall')."""
    # lru_cache: the Start Menu rarely changes, so scan it only ONCE and reuse the result
    keyword = keyword.lower()
    best: Optional[Path] = None
    for d in _start_menu_dirs():
        try:
            shortcuts = list(d.rglob("*.lnk"))
        except OSError as e:
            log.warning("could not scan %s: %s", d, e)
            continue
        for lnk in shortcuts:
            stem = lnk.stem.lower()
            if keyword in stem and "uninstall" not in stem:
                if best is None or len(stem) < len(best.stem):
                    best = lnk
    return best


def _shell_open(target: str) -> None:
    """Open a URI/shortcut through explorer.exe, so the new app is NOT a child of our terminal
    (nothing it prints can leak here, and Ctrl+C can't kill it)."""
    _spawn(["explorer.exe", target])


def _launch_app(resolved: ResolvedApp) -> bool:
    """Launch an app resolved by ai.app_registry (manual target or Start-Menu shortcut).

    Only targets that came from OUR whitelist are used - never raw model text.
    """
    log.debug("launching app %r (%s -> %s)", resolved.name, resolved.kind, resolved.target)

    if resolved.kind == "shortcut":
        try:
            os.startfile(resolved.target)   # .lnk path from our Start Menu scan
            return True
        except OSError as e:
            log.warning("could not open shortcut %s: %s", resolved.target, e)
            return False

    # Discord's own launcher (silent, fully detached)
    if resolved.name == "discord":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            upd = Path(local) / "Discord" / "Update.exe"
            if upd.exists():
                _spawn([str(upd), "--processStart", "Discord.exe"])
                return True

    try:
        os.startfile(resolved.target)   # exe name or URI scheme from ai/apps.py
        return True
    except OSError as e:
        log.debug("os.startfile(%r) failed: %s", resolved.target, e)

    # Fallback: Start Menu shortcut by keyword
    if resolved.keyword:
        lnk = _find_shortcut(resolved.keyword)
        if lnk:
            _shell_open(str(lnk))
            return True
    return False


# ---------- browsers ----------
def _browser_path(browser: str) -> Optional[str]:
    """Find a browser executable on Windows. Returns a path string or None."""
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


def _open_url(url: str, browser: Optional[str] = None) -> str:
    """Open a URL. Returns the name of the browser used."""
    log.debug("opening url %r with browser=%r", url, browser)
    if browser:
        path = _browser_path(browser)
        if path:
            _spawn([path, url])      # list, no shell
            return browser
    if not webbrowser.open(url):
        raise RuntimeError("no browser available")
    return "default browser" + (f" ({browser} not found)" if browser else "")


# ---------- folders (names are sanitized; the model never supplies a path) ----------
KNOWN_FOLDERS = {"pictures", "documents", "downloads", "desktop", "music", "videos"}


def _clean_name(name: str) -> str:
    """Letters/digits/space/-/_ only (Arabic letters are allowed)."""
    if not isinstance(name, str):
        return ""
    name = re.sub(r"[^\w\s\-]", "", name, flags=re.UNICODE).strip()
    return name[:50]


def _open_path(path: Path) -> None:
    """Open a folder/file with its default Windows handler."""
    os.startfile(str(path))


# ---------- volume (pycaw: exact Windows master volume) ----------
def _volume_interface() -> IAudioEndpointVolume:
    """Return the Windows master-volume endpoint (old and new pycaw APIs)."""
    device = AudioUtilities.GetSpeakers()
    if hasattr(device, "EndpointVolume"):          # pycaw 2024+
        return device.EndpointVolume
    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)  # pycaw 0.6.x
    return cast(interface, POINTER(IAudioEndpointVolume))


def _get_volume_percent() -> int:
    """Current master volume as an integer percentage (0-100)."""
    return round(_volume_interface().GetMasterVolumeLevelScalar() * 100)


def _set_volume_percent(level: int) -> int:
    """Set the master volume to `level` percent (clamped to 0-100). Returns the level set."""
    level = max(0, min(100, int(level)))
    _volume_interface().SetMasterVolumeLevelScalar(level / 100.0, None)
    return level


def _step_volume(delta: int) -> int:
    """Raise/lower the master volume by `delta` percentage points. Returns the new level."""
    return _set_volume_percent(_get_volume_percent() + delta)


def _set_mute(muted: bool) -> bool:
    """Set system mute to `muted`. Returns the new state."""
    endpoint = _volume_interface()
    endpoint.SetMute(bool(muted), None)
    return bool(muted)


# ---------- dangerous actions (always need confirmation) ----------
DANGEROUS_ACTIONS = {"shutdown"}
_DANGER_PROMPTS = {"shutdown": "⚠️ Shut down the computer? Are you sure? (y/n): "}
_YES_WORDS = {
    "y", "yes", "yeah", "yep", "sure", "ok", "okay", "confirm",
    "نعم", "أيوه", "ايوه", "ايوة", "أيوة", "تمام", "أكيد", "اكيد", "موافق", "آه", "اه",
}


def _is_yes(answer: str) -> bool:
    """True only for a clear yes (English or Arabic). Anything else means no."""
    if not isinstance(answer, str):
        return False
    return answer.strip().strip(" .!?،؟").lower() in _YES_WORDS


# ---------- action handlers ----------
def _handle_open_app(cmd: dict, confirm: Confirm) -> str:
    """Open an installed app by name (resolved against the whitelist)."""
    app_name = cmd.get("app")
    resolved = resolve_app(app_name)
    if resolved is None:
        return f"❌ App not found: {app_name}"
    try:
        launched = _launch_app(resolved)
    except OSError as e:          # e.g. Discord's Update.exe disappearing between checks
        log.warning("launch failed for %s: %s", resolved.name, e)
        launched = False
    if not launched:
        return f"❌ Could not open {resolved.name} (is it installed?)"
    return f"✅ Opening {resolved.name}"


def _handle_web_search(cmd: dict, confirm: Confirm) -> str:
    """Search Google/YouTube (the domain is fixed in code; only the query is encoded)."""
    query = (cmd.get("query") or "").strip()[:200]
    if not query:
        return "❌ Empty search"
    engine = cmd.get("engine") if cmd.get("engine") in SEARCH_URLS else "google"
    browser = cmd.get("browser") if cmd.get("browser") in BROWSER_NAMES else None
    try:
        used = _open_url(SEARCH_URLS[engine] + quote_plus(query), browser)
    except Exception as e:          # browser launch problems are reported, not fatal
        log.warning("could not open browser: %s", e)
        return "❌ Could not open the browser"
    return f"🔎 Searching {engine} for: {query}  [{used}]"


def _handle_open_website(cmd: dict, confirm: Confirm) -> str:
    """Open a site from the fixed whitelist (never a model-provided URL)."""
    site = cmd.get("site")
    if site not in SITES:
        return f"❌ Website not allowed: {site}"
    try:
        _open_url(SITES[site])
    except Exception as e:
        log.warning("could not open browser: %s", e)
        return "❌ Could not open the browser"
    return f"🌐 Opening {site}"


def _handle_create_folder(cmd: dict, confirm: Confirm) -> str:
    """Create a folder on the Desktop (or the home folder if there is no Desktop)."""
    name = _clean_name(cmd.get("name") or "")
    if not name:
        return "❌ Invalid folder name"
    desktop = Path.home() / "Desktop"
    path = (desktop if desktop.exists() else Path.home()) / name
    try:
        path.mkdir(exist_ok=True)
    except OSError as e:
        log.warning("could not create folder %s: %s", path, e)
        return f"❌ Could not create folder: {e}"
    return f"✅ Folder created: {path}"


def _handle_open_folder(cmd: dict, confirm: Confirm) -> str:
    """Open a known Windows folder or one directly under the home folder."""
    name = _clean_name(cmd.get("name") or "")
    if not name:
        return "❌ Invalid folder name"
    path = Path.home() / (name.capitalize() if name.lower() in KNOWN_FOLDERS else name)
    if not path.is_dir() and name.lower() in KNOWN_FOLDERS:
        path = Path.home() / name       # localized Windows folder name
    if not path.is_dir():
        return f"❌ Folder not found: {path}"
    try:
        _open_path(path)
    except OSError as e:
        log.warning("could not open folder %s: %s", path, e)
        return f"❌ Could not open folder: {e}"
    return f"✅ Opening {path}"


def _handle_volume_up(cmd: dict, confirm: Confirm) -> str:
    """Raise the volume by 10 percentage points."""
    try:
        level = _step_volume(10)
    except Exception as e:  # COM/audio errors must not kill the assistant
        log.warning("volume control failed: %s", e)
        return "❌ Volume control unavailable"
    return f"🔊 Volume up ({level}%)"


def _handle_volume_down(cmd: dict, confirm: Confirm) -> str:
    """Lower the volume by 10 percentage points."""
    try:
        level = _step_volume(-10)
    except Exception as e:
        log.warning("volume control failed: %s", e)
        return "❌ Volume control unavailable"
    return f"🔉 Volume down ({level}%)"


def _handle_set_volume(cmd: dict, confirm: Confirm) -> str:
    """Set the volume to an exact percentage (0-100)."""
    try:
        level = _set_volume_percent(int(cmd.get("level")))
    except (TypeError, ValueError):
        return "❌ Invalid volume level"
    except Exception as e:
        log.warning("volume control failed: %s", e)
        return "❌ Volume control unavailable"
    return f"🔊 Volume set to {level}%"


def _handle_mute(cmd: dict, confirm: Confirm) -> str:
    """Mute the system."""
    try:
        _set_mute(True)
    except Exception as e:
        log.warning("volume control failed: %s", e)
        return "❌ Volume control unavailable"
    return "🔇 Muted"


def _handle_unmute(cmd: dict, confirm: Confirm) -> str:
    """Unmute the system."""
    try:
        _set_mute(False)
    except Exception as e:
        log.warning("volume control failed: %s", e)
        return "❌ Volume control unavailable"
    return "🔊 Unmuted"


def _handle_shutdown(cmd: dict, confirm: Confirm) -> str:
    """Shut down in 15 seconds (confirmation happens in execute for dangerous actions)."""
    try:
        _spawn(["shutdown", "/s", "/t", "15"])
    except OSError as e:
        log.warning("could not start shutdown: %s", e)
        return "❌ Could not shut down"
    return "⏻ Shutting down in 15s (cancel with: shutdown /a)"


_HANDLERS: dict[str, Handler] = {
    "open_app": _handle_open_app,
    "web_search": _handle_web_search,
    "open_website": _handle_open_website,
    "create_folder": _handle_create_folder,
    "open_folder": _handle_open_folder,
    "volume_up": _handle_volume_up,
    "volume_down": _handle_volume_down,
    "set_volume": _handle_set_volume,
    "mute": _handle_mute,
    "unmute": _handle_unmute,
    "shutdown": _handle_shutdown,
}


def execute(cmd: dict, confirm: Confirm = input) -> str:
    """Run a command dict from understand_command(). Returns a message to show the user."""
    action = cmd.get("action")
    handler = _HANDLERS.get(action)
    if handler is None:
        log.debug("unsupported action: %r", action)
        return "🤷 Didn't understand / unsupported command"
    if action in DANGEROUS_ACTIONS:
        prompt = _DANGER_PROMPTS.get(action, f"⚠️ {action}? Are you sure? (y/n): ")
        try:
            answer = confirm(prompt)
        except EOFError:
            answer = ""                  # stdin closed -> safe default (no)
        if not _is_yes(answer):
            log.info("cancelled dangerous action: %s", action)
            return "Cancelled"
    return handler(cmd, confirm)
