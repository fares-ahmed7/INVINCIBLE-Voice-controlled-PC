"""
Voice demo: speak -> text -> AI module -> JSON.   (Windows-only. Nothing is executed.)

    python voice_demo.py                 # Arabic (ar-EG)
    python voice_demo.py --lang en-US    # English
    python voice_demo.py --list-mics     # show microphones and their numbers
    python voice_demo.py --mic 1         # use microphone number 1

Needs internet for the speech recognition (Google Web Speech API).
Requires PyAudio for microphone access.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import speech_recognition as sr

from ai import understand_command, warmup

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")


def clean_text(text: str) -> str:
    """Remove invisible direction marks that speech recognition adds to Arabic/mixed text."""
    return _INVISIBLE.sub("", text or "").strip()


EXIT_WORDS = {"exit", "quit", "stop", "خروج", "وقف", "اخرج"}


def build_listener(lang: str, mic_index: Optional[int]) -> Callable[..., Optional[str]]:
    """Build the microphone listener (Google STT via speech_recognition).

    Returns listen(timeout=8, phrase_time_limit=5) -> text or None.
    """
    recognizer = sr.Recognizer()

    try:
        mic = sr.Microphone(device_index=mic_index)
    except (AttributeError, OSError, ImportError, ValueError) as e:
        sys.exit(f"❌ No microphone available ({e}).\n"
                 "Install PyAudio and check Windows Privacy -> Microphone.")

    try:
        with mic as source:
            print("Calibrating for background noise (1s)... stay quiet")
            recognizer.adjust_for_ambient_noise(source, duration=1)
    except (OSError, ValueError) as e:
        sys.exit(f"❌ Could not open the microphone ({e}).\n"
                 "Check Windows Privacy -> Microphone and that no other app is using it.")

    def get_audio(timeout: float = 8, phrase_time_limit: float = 5):
        with mic as source:
            print("🎤 Listening... speak now")
            try:
                # phrase_time_limit ends recognition early so long rambles don't hold the mic
                return recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            except sr.WaitTimeoutError:
                return None

    def recognize_one(audio, language):
        try:
            return clean_text(recognizer.recognize_google(audio, language=language))
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            print(f"   Speech service error (internet?): {e}")
            return None

    def listen(timeout: float = 8, phrase_time_limit: float = 5) -> Optional[str]:
        audio = get_audio(timeout, phrase_time_limit)
        if audio is None:
            return None

        if lang == "mixed":
            # Google understands ONE language per request, so send the same audio twice
            # (Arabic + English) in parallel and let the AI model merge the two transcripts.
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_ar = pool.submit(recognize_one, audio, "ar-EG")
                f_en = pool.submit(recognize_one, audio, "en-US")
                ar, en = f_ar.result(), f_en.result()
            if not ar and not en:
                print("   (couldn't understand the audio)")
                return None
            if not ar or not en or ar == en:
                return ar or en
            return f"[ar] {ar} || [en] {en}"

        text = recognize_one(audio, lang)
        if not text:
            print("   (couldn't understand the audio)")
        return text

    return listen


def main():
    if sys.platform != "win32":
        print("❌ shawkat currently runs on Windows only. Exiting.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="ar-EG", choices=("ar-EG", "en-US", "mixed"),
                        help="ar-EG, en-US, or mixed")
    parser.add_argument("--mic", type=int, default=None, help="microphone number")
    parser.add_argument("--list-mics", action="store_true")
    args = parser.parse_args()

    # Windows consoles default to cp1252 -> UTF-8 output for Arabic / emoji
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if args.list_mics:
        try:
            for i, name in enumerate(sr.Microphone.list_microphone_names()):
                print(f"{i}: {name}")
        except (AttributeError, OSError):
            sys.exit("PyAudio is not installed, so microphones can't be listed.\n"
                     "Run:  pip install pyaudio")
        return

    listen = build_listener(args.lang, args.mic)

    print("Loading model...")
    try:
        warmup()
    except Exception as e:
        sys.exit(f"❌ Could not load the model: {e}\n"
                 "   Make sure Ollama is running (ollama serve) and qwen3:4b is pulled.")
    print("Ready. Say 'exit' to quit (Ctrl+C also works).\n")

    try:
        while True:
            text = listen()
            if not text:
                continue
            text = clean_text(text)
            print(f"📝 Heard: {text}")
            parts = [
                re.sub(r"^\[(ar|en)\]\s*", "", x.strip()).strip(" .!?،؟").lower()
                for x in text.split("||")
            ]
            if any(x in EXIT_WORDS for x in parts):
                break
            result = understand_command(text)
            print("🤖", json.dumps(result, ensure_ascii=False), "\n")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # Stop cleanly with a friendly message instead of a traceback.
        print(f"❌ Failed to run command: {e}")
    print("Bye")


if __name__ == "__main__":
    main()
