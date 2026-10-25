"""
Run commands for real.
    python main.py            # type commands
    python main.py --voice    # speak commands (ar-EG by default)
    python main.py --voice --lang en-US
"""
import argparse
import json
import re

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")


def clean_text(text: str) -> str:
    """Remove invisible direction marks that speech recognition adds to Arabic/mixed text."""
    return _INVISIBLE.sub("", text or "").strip()


from ai import understand_command, warmup
from executor import execute

EXIT_WORDS = {"exit", "quit", "stop", "خروج", "وقف", "اخرج"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--voice", action="store_true")
    p.add_argument("--lang", default="mixed", help="mixed (Arabic+English, default), ar-EG, or en-US")
    p.add_argument("--mic", type=int, default=None)
    args = p.parse_args()

    if args.voice:
        from voice_demo import build_listener
        listen = build_listener(args.lang, args.mic)
    else:
        listen = lambda: input("> ").strip()

    print("Loading model...")
    warmup()
    print("Ready. Say/type 'exit' to quit.\n")

    try:
        while True:
            text = listen()
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
            cmd = understand_command(text)
            print("🤖", json.dumps(cmd, ensure_ascii=False))
            print(execute(cmd), "\n")
    except KeyboardInterrupt:
        pass
    print("Bye")


if __name__ == "__main__":
    main()
