"""
Run commands for real.
    python main.py            # type commands
    python main.py --voice    # speak commands (ar-EG by default)
    python main.py --voice --lang en-US
"""
import argparse
import json
import re
import sys
import time

from ai import understand_command, warmup
from ai.app_registry import discover_apps
from executor import execute

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")


def clean_text(text: str) -> str:
    """Remove invisible direction marks that speech recognition adds to Arabic/mixed text."""
    return _INVISIBLE.sub("", text or "").strip()


EXIT_WORDS = {"exit", "quit", "stop", "خروج", "وقف", "اخرج"}


def main():
    if sys.platform != "win32":
        print("❌ INVINCIBLE currently runs on Windows only. Exiting.")
        sys.exit(1)

    p = argparse.ArgumentParser()
    p.add_argument("--voice", action="store_true")
    p.add_argument("--lang", default="mixed", help="mixed (Arabic+English, default), ar-EG, or en-US")
    p.add_argument("--mic", type=int, default=None)
    p.add_argument("--debug", action="store_true", help="print STT / LLM / execution timings")
    args = p.parse_args()

    # Windows consoles default to cp1252 -> UTF-8 output for Arabic / emoji
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.voice:
        from voice_demo import build_listener
        listen = build_listener(args.lang, args.mic)
    else:
        def listen():
            try:
                return input("> ").strip()
            except EOFError:
                return None      # EOF (e.g. piped input) -> treat as "no more commands"

    print("Scanning Start Menu...")
    app_count = len(discover_apps())
    print("Loading model...")
    warmup()
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
            print(f"📝 {text}")
            parts = [re.sub(r"^\[(ar|en)\]\s*", "", x.strip()).lower() for x in text.split("||")]
            if any(x in EXIT_WORDS for x in parts):
                break
            t2 = time.perf_counter()
            try:
                cmd = understand_command(text)
                print("🤖", json.dumps(cmd, ensure_ascii=False))
                t3 = time.perf_counter()
                result = execute(cmd)
                t4 = time.perf_counter()
            except Exception as e:
                # A single bad command (Ollama down, mic error, ...) must not kill the assistant
                print(f"❌ Failed to run command: {e}")
                continue
            print(result, "\n")
            if args.debug:
                print(f"⏱ STT: {t1 - t0:.2f}s | LLM: {t3 - t2:.2f}s | Execute: {t4 - t3:.2f}s | Total: {t4 - t0:.2f}s")
    except KeyboardInterrupt:
        pass
    print("Bye")


if __name__ == "__main__":
    main()
