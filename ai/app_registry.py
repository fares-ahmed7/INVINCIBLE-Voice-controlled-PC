"""
App whitelist: manual overrides (ai/apps.py) + auto-discovered Start Menu shortcuts.

The model may only suggest an app NAME (free text). This module sanitizes that name and
maps it to a launch target that WE control: either a manual entry from ai/apps.py or a
Start Menu .lnk path discovered on this machine. Raw model text is never launched.
"""
from __future__ import annotations

import os
import re
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from .apps import ALIASES, APPS

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")

# Shortcut names containing these words are not apps (uninstallers, docs, ...)
_EXCLUDED_WORDS = (
    "uninstall", "readme", "help", "documentation", "docs", "manual",
    "release notes", "changelog", "license", "website", "support", "repair",
)

# Anything that looks like a path / URL / command line is rejected outright.
_FORBIDDEN_CHARS = "\\/<>|&;$`\n\r\t"


class ResolvedApp(NamedTuple):
    """A whitelisted launch target for a spoken app name."""
    kind: str      # "manual" (from ai/apps.py) or "shortcut" (Start Menu .lnk)
    name: str      # display name used in messages
    target: str    # exe/URI target for manual entries, .lnk path for shortcuts
    keyword: str = ""  # Start-Menu fallback keyword (manual entries only)


def _normalize(name: str) -> str:
    """Lowercase, drop punctuation/extension noise, collapse spaces (Unicode-safe)."""
    name = _INVISIBLE.sub("", name or "").strip().lower()
    name = re.sub(r"\.lnk$", "", name)
    name = re.sub(r"[^\w\s+]", " ", name, flags=re.UNICODE)
    return re.sub(r"\s+", " ", name).strip()


def _variants(norm: str) -> list[str]:
    """The normalized name plus its form without a leading Arabic definite article."""
    out = [norm]
    if norm.startswith("ال") and len(norm) > 3:
        out.append(norm[2:].strip())
    return out


def sanitize_app_name(name: str) -> str:
    """Return a safe app-name string, or "" if it looks like a path/URL/command.

    The result is only ever used for whitelist lookup - it is never executed.
    """
    name = _INVISIBLE.sub("", name or "").strip()
    if not name or len(name) > 60:
        return ""
    lowered = name.lower()
    if any(ch in name for ch in _FORBIDDEN_CHARS):
        return ""
    if "://" in name or lowered.endswith((".exe", ".bat", ".cmd", ".ps1", ".lnk")):
        return ""
    name = re.sub(r"[^\w\s+.\-]", "", name, flags=re.UNICODE).strip()
    return name


def _start_menu_dirs() -> list[Path]:
    """User + all-users Start Menu folders (Windows)."""
    dirs = []
    for var in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(var)
        if base:
            d = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if d.is_dir():
                dirs.append(d)
    return dirs


@lru_cache(maxsize=1)
def discover_apps() -> dict[str, Path]:
    """Scan Start Menu shortcuts ONCE. Returns {normalized name -> .lnk path}."""
    found: dict[str, Path] = {}
    for d in _start_menu_dirs():
        for lnk in d.rglob("*.lnk"):
            norm = _normalize(lnk.stem)
            if not norm or any(bad in norm for bad in _EXCLUDED_WORDS):
                continue
            found.setdefault(norm, lnk)  # user folder (APPDATA) wins over all-users
    return found


_ALIASES_NORM = {_normalize(k): v for k, v in ALIASES.items()}


def normalize_name(name: str) -> str:
    """Public helper: lowercase, strip punctuation/extension noise, collapse spaces."""
    return _normalize(name)


def _best_match(query: str, candidates: Iterable[str], cutoff: float = 0.75) -> Optional[str]:
    """Exact match first, then substring (shortest name), then difflib fuzzy match."""
    query = _normalize(query)
    pool = list(candidates)
    if not query or not pool:
        return None
    if query in pool:
        return query
    subs = [c for c in pool if query in c]
    if subs:
        return min(subs, key=len)
    close = get_close_matches(query, pool, n=1, cutoff=cutoff)
    return close[0] if close else None


def _manual(app: str) -> ResolvedApp:
    target, keyword = APPS[app]
    return ResolvedApp("manual", app, target, keyword)


def _shortcut(hit: str, discovered: dict[str, Path]) -> ResolvedApp:
    path = discovered[hit]
    return ResolvedApp("shortcut", path.stem, str(path))


def _resolve_alias(canonical: str, discovered: dict[str, Path]) -> Optional[ResolvedApp]:
    """An alias points at a manual app name or at a Start-Menu keyword."""
    if canonical in APPS:
        return _manual(canonical)
    hit = _best_match(canonical, discovered)
    return _shortcut(hit, discovered) if hit else None


def resolve_app(name: str) -> Optional[ResolvedApp]:
    """Resolve a free-text app name to a whitelisted launch target (or None).

    Order: exact manual name -> alias -> discovered shortcut -> fuzzy match.
    Manual entries in ai/apps.py always win over discovered shortcuts.
    """
    safe = sanitize_app_name(name)
    if not safe:
        return None
    norm = _normalize(safe)
    if not norm:
        return None
    discovered = discover_apps()

    for q in _variants(norm):
        # 1) exact manual name
        if q in APPS:
            return _manual(q)
        # 2) exact manual alias
        if q in _ALIASES_NORM:
            resolved = _resolve_alias(_ALIASES_NORM[q], discovered)
            if resolved:
                return resolved
        # 3) discovered shortcut (exact, substring, fuzzy)
        hit = _best_match(q, discovered)
        if hit:
            return _shortcut(hit, discovered)

    # 4) fuzzy match against manual names + aliases
    for q in _variants(norm):
        hit = _best_match(q, list(APPS) + list(_ALIASES_NORM), cutoff=0.8)
        if hit:
            if hit in APPS:
                return _manual(hit)
            resolved = _resolve_alias(_ALIASES_NORM[hit], discovered)
            if resolved:
                return resolved

    return None


def resolve_app_exact(name: str) -> Optional[ResolvedApp]:
    """Resolve only exact manual names, aliases, or Start Menu names (no fuzzy match).

    Used by the pre-model fast path: "open chrome" must never guess a different app.
    """
    safe = sanitize_app_name(name)
    if not safe:
        return None
    norm = _normalize(safe)
    if not norm:
        return None
    discovered = discover_apps()

    for q in _variants(norm):
        if q in APPS:
            return _manual(q)
        if q in _ALIASES_NORM:
            resolved = _resolve_alias(_ALIASES_NORM[q], discovered)
            if resolved:
                return resolved
        if q in discovered:
            return _shortcut(q, discovered)
    return None
