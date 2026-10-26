"""
Run commands for real.

    python main.py                      # type commands
    python main.py --voice              # speak commands (Arabic + English, mixed)
    python main.py --voice --lang en-US # English only
    python main.py --voice --no-wake    # don't require the "invincible" wake word
    python main.py --max-per-minute 20  # change the command rate limit (0 = unlimited)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from ai import understand_command, warmup
from ai.app_registry import discover_apps
from executor import execute
from voice_demo import build_listener

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")

log = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "invincible.log"

EXIT_WORDS = {"exit", "quit", "stop", "خروج", "وقف", "اخرج"}

# ---------- wake word ----------
_WAKE_WORDS = (
    # English + common Google STT misspellings
    "invincible", "invincibles", "invisible",
    # Arabic + common spellings
    "إنفينسيبل", "انفينسيبل", "إنفنسيبل", "انفنسيبل", "إنفينسبل", "انفينسبل",
    "إنفيسيبل", "انفيسيبل", "إنفيسيبول", "انفيسيبول", "إنفينسيبول", "انفينسيبول",
    "إنفنسبل", "انفنسبل",
)
_WAKE_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(w) for w in sorted(_WAKE_WORDS, key=len, reverse=True))
    + r"|in[\s\-_]*(?:vin|vis)[\s\-_]*(?:ci|si|i)[\s\-_]*ble[s]?"
    + r"|[اإأ]?ن[\s\-_]*ف[يى]?ن?[\s\-_]*س[يى]?[\s\-_]*ب[و]?ل"
    + r")(?!\w)",
    re.IGNORECASE,
)

# ---------- yes/no answers (English + Arabic) ----------
_YES_TOKENS = {
    "y", "yes", "yeah", "yep", "sure", "ok", "okay", "confirm",
    "نعم", "أيوه", "ايوه", "ايوة", "أيوة", "تمام", "أكيد", "اكيد", "موافق", "آه", "اه",
}
_NO_TOKENS = {
    "n", "no", "nope", "cancel", "stop", "never",
    "لا", "لأ", "الغاء", "إلغاء", "بلاش", "مش",
}


def clean_text(text: str) -> str:
    """Remove invisible direction marks that speech recognition adds to Arabic/mixed text."""
    return _INVISIBLE.sub("", text or "").strip()


def strip_wake_word(text: str) -> Optional[str]:
    """Remove the wake word from every transcript part.

    Returns the remaining command text ("" if only the wake word was said), or None if no
    wake word was found. Mixed transcripts ("[ar] ... || [en] ...") are handled per part.
    """
    parts = [p.strip() for p in (text or "").split("||")]
    cleaned: list[str] = []
    found = False
    for part in parts:
        new = part
        while True:
            match = _WAKE_RE.search(new)
            if not match:
                break
            found = True
            new = re.sub(r"\s+", " ", f"{new[:match.start()]} {new[match.end():]}").strip()
        if re.fullmatch(r"\[(?:ar|en)\]\s*", new):
            continue                      # the part contained only a tag (+ wake word)
        new = re.sub(r"^(?:hey|hi|ok|okay|يا|هي|أهلا|اهلا)[\s,،.!]+", "", new,
                     flags=re.IGNORECASE).strip(" \t,،.-")
        if new:
            cleaned.append(new)
    if not found:
        return None
    return " || ".join(cleaned)


def is_exit(text: str) -> bool:
    """True if the utterance is a single exit word (works with or without the wake word)."""
    parts = [re.sub(r"^\[(?:ar|en)\]\s*", "", p.strip()).lower() for p in (text or "").split("||")]
    return any(p in EXIT_WORDS for p in parts)


def parse_yes_no(answer: Optional[str]) -> bool:
    """True only for a clear yes. 'No' wins if both appear (safe for shutdown)."""
    if not answer:
        return False
    tokens = set(re.findall(r"\w+", clean_text(answer).lower(), flags=re.UNICODE))
    if tokens & _NO_TOKENS:
        return False
    return bool(tokens & _YES_TOKENS)


def make_voice_confirm(listen: Callable[..., Optional[str]]) -> Callable[[str], str]:
    """Build a confirm(question) callback that listens for ~5s and returns "y" or "n"."""
    def confirm(question: str) -> str:
        print(question)
        answer = listen(timeout=5, phrase_time_limit=3)
        if not answer:
            print("⏱ No answer — cancelled.")
            return "n"
        print(f"📝 {clean_text(answer)}")
        return "y" if parse_yes_no(answer) else "n"
    return confirm


class RateLimiter:
    """Sliding-window limiter: at most `max_calls` commands per `period` seconds."""

    def __init__(self, max_calls: int = 10, period: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.max_calls = max_calls
        self.period = period
        self._clock = clock
        self._calls: deque[float] = deque()

    def allow(self) -> bool:
        """Record a command and return True, or return False if the limit is reached."""
        if self.max_calls <= 0:
            return True                    # 0 (or negative) = unlimited
        now = self._clock()
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            return False
        self._calls.append(now)
        return True


def setup_logging(debug: bool = False) -> None:
    """Console logging + rotating file logging (logs/invincible.log)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    for noisy in ("comtypes", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> None:
    if sys.platform != "win32":
        print("❌ INVINCIBLE currently runs on Windows only. Exiting.")
        sys.exit(1)

    p = argparse.ArgumentParser()
    p.add_argument("--voice", action="store_true")
    p.add_argument("--lang", default="mixed", help="mixed (Arabic+English, default), ar-EG, or en-US")
    p.add_argument("--mic", type=int, default=None)
    p.add_argument("--debug", action="store_true", help="verbose logs + STT/LLM/execute timings")
    p.add_argument("--no-wake", action="store_true", help="don't require the 'invincible' wake word (voice mode)")
    p.add_argument("--max-per-minute", type=int, default=_env_int("INVINCIBLE_MAX_PER_MINUTE", 10),
                   help="max commands per minute (0 = unlimited; default 10)")
    args = p.parse_args()

    # Windows consoles default to cp1252 -> UTF-8 output for Arabic / emoji
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    setup_logging(args.debug)

    if args.voice:
        listen = build_listener(args.lang, args.mic)
        confirm = make_voice_confirm(listen)
    else:
        def listen():
            try:
                return input("> ").strip()
            except EOFError:
                return None      # EOF (e.g. piped input) -> treat as "no more commands"
        confirm = input

    wake_enabled = (
        args.voice
        and not args.no_wake
        and os.getenv("INVINCIBLE_WAKE", "1").strip().lower() not in {"0", "false", "no", "off"}
    )
    limiter = RateLimiter(args.max_per_minute)

    print("Scanning Start Menu...")
    app_count = len(discover_apps())
    print("Loading model...")
    warmup()
    if wake_enabled:
        print("Wake word is ON — start each command with 'invincible' / 'إنفينسيبل'.")
    print(f"Ready ({app_count} Start Menu apps). Say/type 'exit' to quit.\n")

    try:
        while True:
            t0 = time.perf_counter()
            text = listen()
            t1 = time.perf_counter()
            if not text:
                if args.voice:
                    continue
                break
            text = clean_text(text)
            if not text:
                continue

            heard = text
            if wake_enabled and not is_exit(text):
                stripped = strip_wake_word(text)
                if stripped is None:
                    print("💤 Wake word not heard (say 'invincible').")
                    continue
                text = stripped
                if not text:
                    print("✅ I'm listening.")
                    continue

            print(f"📝 {text}")
            if is_exit(text):
                break

            if not limiter.allow():
                print("⏳ Too many commands — please wait a minute.")
                log.info("rate-limited: raw=%r", heard)
                continue

            t2 = time.perf_counter()
            try:
                cmd = understand_command(text)
                print("🤖", json.dumps(cmd, ensure_ascii=False))
                t3 = time.perf_counter()
                result = execute(cmd, confirm=confirm)
                t4 = time.perf_counter()
            except Exception as e:
                # A single bad command (Ollama down, mic error, ...) must not kill the assistant
                log.exception("command failed: raw=%r", heard)
                print(f"❌ Failed to run command: {e}")
                continue
            log.info("command: raw=%r text=%r json=%s result=%r",
                     heard, text, json.dumps(cmd, ensure_ascii=False), result)
            print(result, "\n")
            if args.debug:
                log.debug("timings: STT %.2fs | LLM %.2fs | Execute %.2fs | Total %.2fs",
                          t1 - t0, t3 - t2, t4 - t3, t4 - t0)
    except KeyboardInterrupt:
        pass
    print("Bye")


if __name__ == "__main__":
    main()
