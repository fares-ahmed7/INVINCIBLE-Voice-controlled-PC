"""
Voice demo: speak -> text -> AI module -> JSON.   (Works on Windows and Linux. Nothing is executed.)

    python voice_demo.py                 # Arabic (ar-EG)
    python voice_demo.py --lang en-US    # English
    python voice_demo.py --list-mics     # show microphones and their numbers
    python voice_demo.py --mic 1         # use microphone number 1

Needs internet for the speech recognition (Google Web Speech API).
If PyAudio is not installed, it falls back to "press Enter, then speak for 5 seconds"
using sounddevice.
"""
import re
import argparse
import json
import sys
_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")


def clean_text(text: str) -> str:
    """Remove invisible direction marks that speech recognition adds to Arabic/mixed text."""
    return _INVISIBLE.sub("", text or "").strip()


import speech_recognition as sr

from ai import understand_command, warmup

RECORD_SECONDS = 5
EXIT_WORDS = {"exit", "quit", "خروج", "وقف"}


def build_listener(lang: str, mic_index):
    recognizer = sr.Recognizer()

    # ---- Preferred: automatic detection of speech start/end (needs PyAudio) ----
    try:
        mic = sr.Microphone(device_index=mic_index)
    except (AttributeError, OSError, ImportError):
        mic = None

    if mic is not None:
        with mic as source:
            print("Calibrating for background noise (1s)... stay quiet")
            recognizer.adjust_for_ambient_noise(source, duration=1)

        def get_audio():
            with mic as source:
                print("🎤 Listening... speak now")
                try:
                    return recognizer.listen(source, timeout=8, phrase_time_limit=8)
                except sr.WaitTimeoutError:
                    return None
    else:
        # ---- Fallback: push-to-talk with sounddevice (no PyAudio needed) ----
        try:
            import sounddevice as sd
        except ImportError:
            sys.exit("Neither PyAudio nor sounddevice is installed.\n"
                     "Run:  pip install sounddevice numpy")
        print("PyAudio not found -> using push-to-talk mode (sounddevice).")

        def get_audio():
            input(f"Press Enter, then speak for {RECORD_SECONDS} seconds... ")
            print("🎤 Recording...")
            data = sd.rec(int(RECORD_SECONDS * 16000), samplerate=16000,
                          channels=1, dtype="int16", device=mic_index)
            sd.wait()
            return sr.AudioData(data.tobytes(), 16000, 2)

    def recognize_one(audio, language):
        try:
            return clean_text(recognizer.recognize_google(audio, language=language))
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            print(f"   Speech service error (internet?): {e}")
            return None

    def listen():
        audio = get_audio()
        if audio is None:
            return None

        if lang == "mixed":
            # Google understands ONE language per request, so send the same audio twice
            # (Arabic + English) in parallel and let the AI model merge the two transcripts.
            from concurrent.futures import ThreadPoolExecutor
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="ar-EG", help="ar-EG, en-US, or mixed")
    parser.add_argument("--mic", type=int, default=None, help="microphone number")
    parser.add_argument("--list-mics", action="store_true")
    args = parser.parse_args()

    if args.list_mics:
        try:
            for i, name in enumerate(sr.Microphone.list_microphone_names()):
                print(f"{i}: {name}")
        except AttributeError:
            sys.exit("PyAudio is not installed, so microphones can't be listed this way.\n"
                     "Try:  python -c \"import sounddevice as sd; print(sd.query_devices())\"")
        return

    listen = build_listener(args.lang, args.mic)

    print("Loading model...")
    warmup()
    print("Ready. Say 'exit' to quit (Ctrl+C also works).\n")

    try:
        while True:
            text = listen()
            if not text:
                continue
            text = clean_text(text)
            print(f"📝 Heard: {text}")
            if text.strip().lower() in EXIT_WORDS:
                break
            result = understand_command(text)
            print("🤖", json.dumps(result, ensure_ascii=False), "\n")
    except KeyboardInterrupt:
        pass
    print("Bye")


if __name__ == "__main__":
    main()
