"""
App whitelist: manual overrides (ai/apps.py) + auto-discovered Start Menu shortcuts.

The model may only suggest an app NAME (free text). This module sanitizes that name and
maps it to a launch target that WE control: either a manual entry from ai/apps.py or a
Start Menu .lnk path discovered on this machine. Raw model text is never launched.
"""
from __future__ import annotations

import logging
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from .apps import ALIASES, APPS

log = logging.getLogger(__name__)

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
    if not isinstance(name, str):
        return ""
    name = _INVISIBLE.sub("", name).strip().lower()
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
    if not isinstance(name, str):
        return ""
    name = _INVISIBLE.sub("", name).strip()
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
            try:
                if d.is_dir():
                    dirs.append(d)
            except OSError as e:
                log.warning("could not access %s: %s", d, e)
    return dirs


@lru_cache(maxsize=1)
def discover_apps() -> dict[str, Path]:
    """Scan Start Menu shortcuts ONCE. Returns {normalized name -> .lnk path}."""
    found: dict[str, Path] = {}
    for d in _start_menu_dirs():
        try:
            shortcuts = list(d.rglob("*.lnk"))
        except OSError as e:
            log.warning("could not scan %s: %s", d, e)
            continue
        for lnk in shortcuts:
            norm = _normalize(lnk.stem)
            if not norm or any(bad in norm for bad in _EXCLUDED_WORDS):
                continue
            found.setdefault(norm, lnk)  # user folder (APPDATA) wins over all-users
    return found


_ALIASES_NORM = {_normalize(k): v for k, v in ALIASES.items()}


def normalize_name(name: str) -> str:
    """Public helper: lowercase, strip punctuation/extension noise, collapse spaces."""
    return _normalize(name)


def _token_close(query: str, candidate: str, cutoff: float) -> bool:
    """True if two names differ only by likely typos, token by token.

    Whole-string similarity is not enough: "microsoft word" and "microsoft edge" are
    superficially similar but different apps. Token counts and token positions must match,
    and a punctuation-only suffix ("notepad++" vs "notepad") is treated as a different app.
    """
    q_tokens = query.split()
    c_tokens = candidate.split()
    if len(q_tokens) != len(c_tokens):
        return False
    for q_token, c_token in zip(q_tokens, c_tokens):
        if q_token == c_token:
            continue
        if q_token.startswith(c_token) or c_token.startswith(q_token):
            longer = q_token if q_token.startswith(c_token) else c_token
            shorter = c_token if q_token.startswith(c_token) else q_token
            extra = longer[len(shorter):]
            if extra and not re.search(r"\w", extra):
                return False
        if SequenceMatcher(None, q_token, c_token).ratio() < cutoff:
            return False
    return True


def _best_match(query: str, candidates: Iterable[str], cutoff: float = 0.75) -> Optional[str]:
    """Exact match first, then a safe prefix, then token-aware fuzzy match."""
    query = _normalize(query)
    pool = list(candidates)
    if not query or not pool:
        return None
    if query in pool:
        return query
    # "calc" -> "calculator" is safe only for a single token; multi-token substrings
    # ("visual studio" -> "visual studio code") would silently substitute another app.
    if " " not in query and len(query) >= 3:
        subs = [c for c in pool if query in c]
        if subs:
            return min(subs, key=len)
    close = [c for c in pool if _token_close(query, c, cutoff)]
    if close:
        return min(close, key=lambda c: (abs(len(c) - len(query)), len(c)))
    return None


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
