"""
AI / NLP module (INVINCIBLE)

    understand_command("افتح كروم")  ->  {"action": "open_app", "app": "chrome", "name": None}

This module only talks to a local Ollama server, so it has no OS-specific code.

Config (environment variables, all optional):
    INVINCIBLE_MODEL   model name            (default: qwen3:4b)
    OLLAMA_HOST        Ollama server address (default: http://localhost:11434)
"""
import os
import re
from typing import Any, Optional

import ollama

from .app_registry import normalize_name, resolve_app_exact, sanitize_app_name
from .apps import APP_NAMES, BROWSER_NAMES
from .schema import Command
from .sites import SITE_ALIASES, SITES

MODEL = os.getenv("INVINCIBLE_MODEL", "qwen3:4b")

_INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u200b]")

# Trivial commands answered locally (no LLM round-trip -> instant + cheap).
# Substring matching on the cleaned text; English is lowercased, Arabic is case-free.
UNMUTE_PHRASES = (
    "unmute", "un-mute", "شغل الصوت", "ارجع الصوت", "إلغاء الكتم", "الغاء الكتم", "شغل صوت",
)
MUTE_PHRASES = (
    "اكتم الصوت", "كتم الصوت", "اسكت الصوت", "silence the volume", "mute", "silence",
)
VOLUME_UP_PHRASES = (
    "ارفع الصوت", "علي الصوت", "على الصوت", "ارتفع الصوت", "ارتفع مستوى الصوت", "رفع الصوت",
    "ارتفاع الصوت", "زود الصوت", "increase the volume", "turn up the volume", "volume up",
    "raise the volume", "boost the volume", "louder",
)
VOLUME_DOWN_PHRASES = (
    "اخفض الصوت", "خفض الصوت", "وطي الصوت", "وطى الصوت", "تقليل الصوت", "قلل الصوت",
    "decrease the volume", "turn down the volume", "volume down", "lower the volume", "quieter",
)

# "set volume to 50" / "خلي الصوت 50" / "volume 50%"
_SET_VOLUME_RE = re.compile(
    r"(?:set\s+(?:the\s+)?volume(?:\s+(?:to|at))?"
    r"|volume\s*(?:to|at|=|:)?"
    r"|(?:خلي|خلى|ظبط|اضبط|حط|سيب)\s+(?:ال)?صوت(?:\s+(?:على|علي|عند))?)"
    r"\s*(?P<level>\d{1,3})\s*%?",
    re.IGNORECASE,
)

# "open chrome" / "افتح يوتيوب" / "شغل الترمنال" (exact known app/site only)
_OPEN_RE = re.compile(
    r"^(?:open|launch|start|run|افتح|شغل|شغّل|ابدا|ابدأ)\s+(?P<name>.+)$",
    re.IGNORECASE,
)
_SEARCH_WORDS = ("search", "find", "ابحث", "بحث", "دور", "دور على")
_SITE_ALIASES_NORM = {normalize_name(k): v for k, v in SITE_ALIASES.items() if v in SITES}

SYSTEM_PROMPT = """You are the command parser of a voice-controlled Windows PC.
The user speaks Arabic or English (sometimes mixed). The text comes from speech recognition,
so it may contain mistakes, and English app names may be written in Arabic letters
(e.g. "كروم" = chrome, "كالكيوليتور" = calculator).
Sometimes the input has TWO transcripts of the SAME speech, separated by "||": "[ar]" from an Arabic
recognizer and "[en]" from an English recognizer. The speaker may mix Arabic and English in one sentence.
The Arabic recognizer writes English words phonetically in Arabic letters, and the English recognizer
garbles Arabic words. Use both to work out what was really said, then answer with ONE command.
For search queries keep the words in the language the speaker meant (English words in English, Arabic words in Arabic).
Convert the sentence into ONE JSON command. Answer with ONLY the JSON object (no markdown, no thinking).

Actions: open_app, web_search, open_website, create_folder, open_folder, volume_up, volume_down, set_volume, mute, unmute, shutdown, unknown.
Apps the assistant knows by name: {APPS}. Other installed Windows apps are allowed too.
Rules:
- open_app needs "app": the app name as the user said it (Arabic or English), e.g. "chrome", "كروم", "notepad++".
  Return ONLY a short app name - never a file path, executable path, command, or URL.
  If the user says just "browser"/"المتصفح", use firefox. If no app name is clear, use "unknown".
  Never substitute a different app than the one the user named.
- web_search needs "query" (only the search words, without "search for"/"ابحث عن") and "engine" (google by default, youtube if the user says youtube/يوتيوب).
- open_website needs "site", one of: google, youtube, facebook, gmail, github, whatsapp, wikipedia. Websites not in the list -> unknown.
- If the user names a browser for the search (chrome/edge/firefox, or ايدج/كروم/فايرفوكس), put it in "browser". Otherwise omit "browser".
- "open google and search for X" / "افتح جوجل وابحث عن X" is ONE web_search command.
- create_folder and open_folder need "name" (the folder name only, nothing else).
- set_volume needs "level": a whole number from 0 to 100.
- mute silences the system; unmute restores sound (they are different actions).
- If the request does not match any action (questions, chat, deleting files,
  brightness, anything unsupported), use "unknown". Never invent new actions.

Examples:
"افتح كروم" -> {"action":"open_app","app":"chrome"}
"افتح ديسكورد" -> {"action":"open_app","app":"discord"}
"افتح سبوتيفاي" -> {"action":"open_app","app":"spotify"}
"افتح الاعدادات" -> {"action":"open_app","app":"settings"}
"افتح فوتوشوب" -> {"action":"open_app","app":"فوتوشوب"}
"open notepad++" -> {"action":"open_app","app":"notepad++"}
"open C:\\Windows\\System32\\cmd.exe" -> {"action":"unknown"}
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
"خلي الصوت 50" -> {"action":"set_volume","level":50}
"set the volume to 30" -> {"action":"set_volume","level":30}
"اكتم الصوت" -> {"action":"mute"}
"شغل الصوت" -> {"action":"unmute"}
"unmute" -> {"action":"unmute"}
"اقفل الجهاز" -> {"action":"shutdown"}
"ايه الجو النهارده" -> {"action":"unknown"}
"امسح كل الملفات" -> {"action":"unknown"}
""".replace("{APPS}", ", ".join(APP_NAMES))


def _fast_open(text: str) -> Optional[dict]:
    """Open a known app/site by exact keyword (no model). Returns a Command dict or None."""
    for part in text.split("||"):
        part = re.sub(r"^\[(?:ar|en)\]\s*", "", part.strip())
        match = _OPEN_RE.match(part)
        if not match:
            continue
        name = match.group("name").strip(" .!?،؟")
        if not name or any(word in name.lower() for word in _SEARCH_WORDS):
            continue                    # "open google and search X" -> let the model handle it
        site = _SITE_ALIASES_NORM.get(normalize_name(name))
        if site:
            return Command(action="open_website", site=site).model_dump()
        resolved = resolve_app_exact(name)
        if resolved:
            return Command(action="open_app", app=resolved.name).model_dump()
    return None


def _fast_path(text: str) -> Optional[dict]:
    """Answer common commands locally (volume, mute, known app/site), without the LLM.

    Keeps the assistant snappy and adds no new risk (only whitelisted targets).
    Returns a Command dict, or None if the text isn't a fast-path candidate.
    """
    t = _INVISIBLE.sub("", (text or "")).strip()
    low = t.lower()

    match = _SET_VOLUME_RE.search(low)
    if match:
        level = int(match.group("level"))
        if 0 <= level <= 100:
            return Command(action="set_volume", level=level).model_dump()

    # "unmute" contains "mute", so check unmute first
    if any(p in low for p in UNMUTE_PHRASES):
        return Command(action="unmute").model_dump()
    if any(p in low for p in MUTE_PHRASES):
        return Command(action="mute").model_dump()
    if any(p in low for p in VOLUME_DOWN_PHRASES):
        return Command(action="volume_down").model_dump()
    if any(p in low for p in VOLUME_UP_PHRASES):
        return Command(action="volume_up").model_dump()

    return _fast_open(t)


_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think(?:ing)?>", re.IGNORECASE)
_THINK_SUPPORTED = True


def _chat(text: str, model: str) -> Any:
    """Call Ollama with structured JSON output and thinking disabled when supported."""
    global _THINK_SUPPORTED
    system = SYSTEM_PROMPT if _THINK_SUPPORTED else SYSTEM_PROMPT + "\n/no_think"
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        format=Command.model_json_schema(),   # forces JSON that matches the schema
        options={"temperature": 0, "num_predict": 256},   # JSON-only replies, deterministic, no rambling
        keep_alive="30m",                      # keep the model loaded in RAM
    )
    if _THINK_SUPPORTED:
        try:
            return ollama.chat(think=False, **kwargs)   # skip "thinking" -> faster
        except (TypeError, ollama.ResponseError):
            _THINK_SUPPORTED = False
            kwargs["messages"][0]["content"] = SYSTEM_PROMPT + "\n/no_think"
    return ollama.chat(**kwargs)                # older library / model without the think flag


def _parse_command(content: str) -> Command:
    """Parse the model reply defensively: strip thinking, require schema-valid JSON."""
    content = _THINK_RE.sub("", content or "")
    content = _THINK_TAG_RE.sub("", content).strip()
    try:
        return Command.model_validate_json(content)
    except Exception:
        # Defensive: pull out the first JSON object if the model wrapped it in prose
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return Command.model_validate_json(match.group(0))
            except Exception:
                pass
    return Command(action="unknown")


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
    cmd = _parse_command(resp.message.content)

    # Sanity checks: a command missing its required field is useless -> unknown
    if cmd.action == "open_app":
        app = sanitize_app_name(cmd.app or "")
        cmd = Command(action="open_app", app=app) if app else Command(action="unknown")
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
    if cmd.action == "set_volume":
        try:
            level = int(cmd.level)
        except (TypeError, ValueError):
            cmd = Command(action="unknown")
        else:
            cmd = Command(action="set_volume", level=level) if 0 <= level <= 100 else Command(action="unknown")
    if cmd.action == "shutdown":
        # shutdown takes no payload: drop anything else the model may have added
        cmd = Command(action="shutdown")
    if cmd.action == "unknown":
        # unknown takes no payload either (never echo a path/URL the model may have produced)
        cmd = Command(action="unknown")

    return cmd.model_dump()


def warmup(model: Optional[str] = None) -> None:
    """Load the model into RAM so the first real command isn't slow."""
    understand_command("مرحبا", model=model)
