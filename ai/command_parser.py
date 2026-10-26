"""
AI / NLP module (INVINCIBLE)

    understand_command("افتح كروم")  ->  {"action": "open_app", "app": "chrome", "name": None}

This module has NO dependency on Ubuntu: it only talks to a local Ollama server,
so it runs the same on Windows, Linux or macOS.

Config (environment variables, all optional):
    INVINCIBLE_MODEL   model name            (default: qwen3:4b)
    OLLAMA_HOST        Ollama server address (default: http://localhost:11434)
"""
import os
import re
from typing import Optional

import ollama

from .apps import APP_NAMES, BROWSER_NAMES
from .schema import Command

MODEL = os.getenv("INVINCIBLE_MODEL", "qwen3:4b")

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")

# Trivial commands answered locally (no LLM round-trip -> instant + cheap).
# Substring matching on the cleaned text; English is lowercased, Arabic is case-free.
MUTE_PHRASES = ("اكتم الصوت", "كتم الصوت", "silence the volume", "mute", "silence")
VOLUME_UP_PHRASES = (
    "ارفع الصوت", "علي الصوت", "ارتفع الصوت", "ارتفع مستوى الصوت", "رفع الصوت", "ارتفاع الصوت",
    "increase the volume", "turn up the volume", "volume up", "raise the volume", "boost the volume",
)
VOLUME_DOWN_PHRASES = (
    "اخفض الصوت", "خفض الصوت", "وطي الصوت", "تقليل الصوت", "decrease the volume",
    "turn down the volume", "volume down", "lower the volume",
)

SYSTEM_PROMPT = """You are the command parser of a voice-controlled Ubuntu system.
The user speaks Arabic or English (sometimes mixed). The text comes from speech recognition,
so it may contain mistakes, and English app names may be written in Arabic letters
(e.g. "كروم" = chrome, "كالكيوليتور" = calculator).
Sometimes the input has TWO transcripts of the SAME speech, separated by "||": "[ar]" from an Arabic
recognizer and "[en]" from an English recognizer. The speaker may mix Arabic and English in one sentence.
The Arabic recognizer writes English words phonetically in Arabic letters, and the English recognizer
garbles Arabic words. Use both to work out what was really said, then answer with ONE command.
For search queries keep the words in the language the speaker meant (English words in English, Arabic words in Arabic).
Convert the sentence into ONE JSON command.

Actions: open_app, web_search, open_website, create_folder, open_folder, volume_up, volume_down, mute, shutdown, unknown.
Apps: {APPS}.
Rules:
- open_app needs "app" (exactly one name from the Apps list). If the app is NOT in the list, use "unknown" - never pick a different app.
- open_app needs "app". If the user says just "browser"/"المتصفح" use firefox.
- web_search needs "query" (only the search words, without "search for"/"ابحث عن") and "engine" (google by default, youtube if the user says youtube/يوتيوب).
- open_website needs "site", one of: google, youtube, facebook, gmail, github, whatsapp, wikipedia. Websites not in the list -> unknown.
- If the user names a browser for the search (chrome/edge/firefox, or ايدج/كروم/فايرفوكس), put it in "browser". Otherwise omit "browser".
- "open google and search for X" / "افتح جوجل وابحث عن X" is ONE web_search command.
- create_folder and open_folder need "name" (the folder name only, nothing else).
- If the request does not match any action (questions, chat, deleting files,
  brightness, anything unsupported), use "unknown". Never invent new actions.

Examples:
"افتح كروم" -> {"action":"open_app","app":"chrome"}
"افتح ديسكورد" -> {"action":"open_app","app":"discord"}
"افتح سبوتيفاي" -> {"action":"open_app","app":"spotify"}
"افتح الاعدادات" -> {"action":"open_app","app":"settings"}
"افتح فوتوشوب" -> {"action":"unknown"}
"افتح المتصفح" -> {"action":"open_app","app":"firefox"}
"open the calculator" -> {"action":"open_app","app":"calculator"}
"شغل الترمنال" -> {"action":"open_app","app":"terminal"}
"ابحث في جوجل عن طريقة عمل الكشري" -> {"action":"web_search","query":"طريقة عمل الكشري","engine":"google"}
"افتح جوجل وابحث عن اخبار الطقس" -> {"action":"web_search","query":"اخبار الطقس","engine":"google"}
"search google for python tutorial" -> {"action":"web_search","query":"python tutorial","engine":"google"}
"دور على اغاني عمرو دياب في يوتيوب" -> {"action":"web_search","query":"اغاني عمرو دياب","engine":"youtube"}
"افتح ايدج وابحث عن اخبار الطقس" -> {"action":"web_search","query":"اخبار الطقس","engine":"google","browser":"edge"}
"open chrome and search for cats" -> {"action":"web_search","query":"cats","engine":"google","browser":"chrome"}
"[ar] اوبن اي جي اند سيرش ويذر || [en] open edge and search weather" -> {"action":"web_search","query":"weather","engine":"google","browser":"edge"}
"[ar] افتح ديسكورد || [en] a fat disk cord" -> {"action":"open_app","app":"discord"}
"[ar] ابحث عن الطقس في القاهرة || [en] a bath and the tax feel koi" -> {"action":"web_search","query":"الطقس في القاهرة","engine":"google"}
"افتح يوتيوب" -> {"action":"open_website","site":"youtube"}
"open github" -> {"action":"open_website","site":"github"}
"اعمل فولدر اسمه Projects" -> {"action":"create_folder","name":"Projects"}
"create a folder named Photos" -> {"action":"create_folder","name":"Photos"}
"افتح فولدر الصور" -> {"action":"open_folder","name":"Pictures"}
"علي الصوت" -> {"action":"volume_up"}
"وطي الصوت" -> {"action":"volume_down"}
"اكتم الصوت" -> {"action":"mute"}
"اقفل الجهاز" -> {"action":"shutdown"}
"ايه الجو النهارده" -> {"action":"unknown"}
"امسح كل الملفات" -> {"action":"unknown"}
""".replace("{APPS}", ", ".join(APP_NAMES))


def _fast_path(text: str):
    """Answer trivial spoken commands (volume / mute) directly, without calling the LLM.

    Keeps the assistant snappy for the most common commands and adds no new risk.
    Returns a Command dict, or None if the text isn't a fast-path candidate.
    """
    t = _INVISIBLE.sub("", (text or "")).lower()
    if any(p in t for p in MUTE_PHRASES):
        return Command(action="mute").model_dump()
    if any(p in t for p in VOLUME_DOWN_PHRASES):
        return Command(action="volume_down").model_dump()
    if any(p in t for p in VOLUME_UP_PHRASES):
        return Command(action="volume_up").model_dump()
    return None


def _chat(text: str, model: str):
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        format=Command.model_json_schema(),   # forces JSON that matches the schema
        options={"temperature": 0, "num_predict": 256},   # JSON-only replies, deterministic, no rambling
        keep_alive="30m",                      # keep the model loaded in RAM
    )
    try:
        return ollama.chat(think=False, **kwargs)   # skip "thinking" -> faster
    except (TypeError, ollama.ResponseError):
        return ollama.chat(**kwargs)                # older library / model without thinking


def understand_command(text: str, model: Optional[str] = None) -> dict:
    """Convert recognized speech text into a command dict. Never raises on bad model output."""
    text = (text or "").strip()
    if not text:
        return Command(action="unknown").model_dump()

    fast = _fast_path(text)
    if fast is not None:
        # trivial command (volume/mute): skip the LLM completely -> instant
        return fast

    resp = _chat(text, model or MODEL)   # connection errors (Ollama down) propagate on purpose

    try:
        cmd = Command.model_validate_json(resp.message.content)
    except Exception:
        return Command(action="unknown").model_dump()

    # Sanity checks: a command missing its required field is useless -> unknown
    if cmd.action == "open_app":
        app = (cmd.app or "").strip().lower()
        cmd = Command(action="open_app", app=app) if app in APP_NAMES else Command(action="unknown")
    if cmd.action == "web_search":
        if not (cmd.query or "").strip():
            cmd = Command(action="unknown")
        else:
            if not cmd.engine:
                cmd.engine = "google"
            b = (cmd.browser or "").strip().lower()
            cmd.browser = b if b in BROWSER_NAMES else None
    if cmd.action == "open_website" and not cmd.site:
        cmd = Command(action="unknown")
    if cmd.action in ("create_folder", "open_folder") and not (cmd.name or "").strip():
        cmd = Command(action="unknown")
    if cmd.action == "shutdown":
        # shutdown takes no payload: drop anything else the model may have added
        cmd = Command(action="shutdown")

    return cmd.model_dump()


def warmup(model: Optional[str] = None) -> None:
    """Load the model into RAM so the first real command isn't slow."""
    understand_command("مرحبا", model=model)
