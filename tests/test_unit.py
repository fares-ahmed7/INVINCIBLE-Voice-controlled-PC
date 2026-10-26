"""Offline unit tests for shawkat.

No microphone, Ollama server, or internet connection is needed.
Run with:  python -m pytest -q
"""
import pytest

import ai.app_registry as registry
import ai.command_parser as parser
import executor
from ai.app_registry import (
    discover_apps,
    normalize_name,
    resolve_app,
    resolve_app_exact,
    sanitize_app_name,
)
from ai.schema import ActionName
from main import RateLimiter, clean_text, is_exit, parse_yes_no, strip_wake_word


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def isolated_start_menu(tmp_path, monkeypatch):
    """Keep every test independent of the real Windows Start Menu."""
    empty = tmp_path / "EmptyStartMenu"
    empty.mkdir()
    monkeypatch.setattr(registry, "_start_menu_dirs", lambda: [empty])
    discover_apps.cache_clear()
    yield
    discover_apps.cache_clear()


@pytest.fixture
def fake_start_menu(tmp_path, monkeypatch):
    programs = tmp_path / "Programs"
    programs.mkdir()
    for name in (
        "My App.lnk",
        "Adobe Photoshop 2024.lnk",
        "Visual Studio Code.lnk",
        "Uninstall My App.lnk",
        "Readme.lnk",
    ):
        (programs / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(registry, "_start_menu_dirs", lambda: [programs])
    discover_apps.cache_clear()
    yield programs
    discover_apps.cache_clear()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --------------------------------------------------------------------------- sanitizing
@pytest.mark.parametrize("bad", [
    r"C:\Windows\System32\cmd.exe",
    "https://evil.example",
    "chrome.exe",
    "rm -rf /",
    "chrome & calc",
    "a" * 61,
])
def test_sanitize_rejects_paths_urls_commands(bad):
    assert sanitize_app_name(bad) == ""
    assert sanitize_app_name(None) == ""


@pytest.mark.parametrize("good,expected", [
    ("Notepad++", "Notepad++"),
    ("فوتوشوب", "فوتوشوب"),
    ("7-Zip", "7-Zip"),
    ("Visual Studio Code", "Visual Studio Code"),
    ("  chrome  ", "chrome"),
])
def test_sanitize_keeps_normal_names(good, expected):
    assert sanitize_app_name(good) == expected


def test_normalize_name():
    assert normalize_name("  Adobe   Photoshop 2024.lnk ") == "adobe photoshop 2024"
    assert normalize_name("Notepad++") == "notepad++"
    assert normalize_name("كروم") == "كروم"


# --------------------------------------------------------------------------- app matching
def test_manual_app_exact():
    resolved = resolve_app("chrome")
    assert resolved is not None
    assert resolved.kind == "manual"
    assert resolved.target == "chrome.exe"


def test_manual_alias_and_arabic_article():
    assert resolve_app("كروم").name == "chrome"
    assert resolve_app("الكروم").name == "chrome"


def test_manual_substring_match():
    assert resolve_app("calc").name == "calculator"


def test_unknown_app_and_path_rejected():
    assert resolve_app("zzzz-not-installed") is None
    assert resolve_app(r"C:\Windows\System32\cmd.exe") is None
    assert resolve_app("https://evil.example") is None


def test_discovery_excludes_docs_and_uninstallers(fake_start_menu):
    apps = discover_apps()
    assert "my app" in apps
    assert "adobe photoshop 2024" in apps
    assert not any("uninstall" in name or "readme" in name for name in apps)


def test_shortcut_exact_match(fake_start_menu):
    resolved = resolve_app("My App")
    assert resolved is not None
    assert resolved.kind == "shortcut"
    assert resolved.target.endswith("My App.lnk")


def test_shortcut_fuzzy_match(fake_start_menu):
    resolved = resolve_app("visul studio code")
    assert resolved is not None
    assert resolved.kind == "shortcut"
    assert "Visual Studio Code" in resolved.target


def test_fuzzy_match_does_not_substitute_different_apps(fake_start_menu):
    # Whole-string similarity used to match "microsoft word" -> Microsoft Edge.
    assert resolve_app("microsoft word").name == "word"
    assert resolve_app("visual studio") is None
    assert resolve_app("calculator++") is None


def test_notepad_plus_plus_is_not_notepad():
    resolved = resolve_app("notepad++")
    assert resolved is not None
    assert resolved.name == "notepad++"
    assert resolved.name != "notepad"


def test_alias_resolves_to_discovered_shortcut(fake_start_menu):
    resolved = resolve_app("فوتوشوب")
    assert resolved is not None
    assert resolved.kind == "shortcut"
    assert "Photoshop" in resolved.target


def test_manual_entry_wins_over_shortcut(fake_start_menu):
    (fake_start_menu / "Chrome.lnk").write_text("", encoding="utf-8")
    discover_apps.cache_clear()
    resolved = resolve_app("chrome")
    assert resolved is not None
    assert resolved.kind == "manual"
    assert resolved.target == "chrome.exe"


def test_resolve_app_exact_does_not_fuzzy_match(fake_start_menu):
    assert resolve_app_exact("visul studio code") is None
    assert resolve_app_exact("My App") is not None


# --------------------------------------------------------------------------- text helpers
def test_clean_text_removes_invisible_marks():
    assert clean_text("\u200ehello\u200f\u200b") == "hello"
    assert clean_text("  مرحبا  ") == "مرحبا"
    assert clean_text(None) == ""


@pytest.mark.parametrize("text,expected", [
    ("shawkat open chrome", "open chrome"),
    ("شوكت افتح كروم", "افتح كروم"),
    ("invisible open chrome", "open chrome"),
    ("[ar] شوكت افتح كروم || [en] shawkat open chrome",
     "[ar] افتح كروم || [en] open chrome"),
    ("hey shawkat open chrome", "open chrome"),
    ("shawkat exit", "exit"),
])
def test_strip_wake_word(text, expected):
    assert strip_wake_word(text) == expected


def test_strip_wake_word_absent_or_only():
    assert strip_wake_word("open chrome") is None
    assert strip_wake_word("shawkat") == ""
    assert strip_wake_word("shawkat!") == ""
    assert strip_wake_word("[en] shawkat!") == ""


@pytest.mark.parametrize("text,expected", [
    ("exit", True),
    ("خروج", True),
    ("exit.", True),
    ("خروج!", True),
    ("shawkat exit", False),
    ("open chrome", False),
])
def test_is_exit(text, expected):
    assert is_exit(text) is expected


@pytest.mark.parametrize("answer,expected", [
    ("yes", True),
    ("نعم", True),
    ("[ar] نعم || [en] yes", True),
    ("no", False),
    ("لا", False),
    ("", False),
    (None, False),
    ("yes no", False),
])
def test_parse_yes_no(answer, expected):
    assert parse_yes_no(answer) is expected


# --------------------------------------------------------------------------- rate limiter
def test_rate_limiter_sliding_window():
    clock = FakeClock()
    limiter = RateLimiter(max_calls=2, period=60, clock=clock)
    assert limiter.allow()
    assert limiter.allow()
    assert not limiter.allow()
    clock.now = 59.9
    assert not limiter.allow()
    clock.now = 60.0
    assert limiter.allow()
    clock.now = 60.1
    assert limiter.allow()
    assert not limiter.allow()


def test_rate_limiter_zero_is_unlimited():
    limiter = RateLimiter(max_calls=0)
    assert all(limiter.allow() for _ in range(100))


# --------------------------------------------------------------------------- JSON validation
class FakeResponse:
    def __init__(self, content: str) -> None:
        self.message = type("Msg", (), {"content": content})()


def _understand(monkeypatch, content: str) -> dict:
    monkeypatch.setattr(parser, "_chat", lambda text, model: FakeResponse(content))
    return parser.understand_command("please do something")


def test_parse_plain_json():
    assert parser._parse_command('{"action":"volume_up"}').action == "volume_up"


def test_parse_strips_thinking():
    cmd = parser._parse_command(' thinkinghmm, maybe...</think>\n{"action":"mute"}')
    assert cmd.action == "mute"


def test_parse_extracts_json_from_prose():
    cmd = parser._parse_command('Sure! {"action":"open_app","app":"chrome"}')
    assert cmd.action == "open_app"
    assert cmd.app == "chrome"


@pytest.mark.parametrize("payload", [
    "not json",
    '{"action":"nonsense"}',
    '{"action":"open_app","app":"C:\\\\Windows\\\\cmd.exe"}',
    '{"action":"set_volume","level":150}',
    '{"action":"web_search","query":"   "}',
    '{"action":"open_website","site":"evil.com"}',
])
def test_invalid_model_output_becomes_unknown(monkeypatch, payload):
    assert _understand(monkeypatch, payload)["action"] == "unknown"


def test_shutdown_payload_is_dropped(monkeypatch):
    cmd = _understand(monkeypatch, '{"action":"shutdown","query":"rm -rf"}')
    assert cmd["action"] == "shutdown"
    assert cmd["query"] is None


def test_empty_text_does_not_call_model(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(parser, "_chat", fail)
    assert parser.understand_command("")["action"] == "unknown"


def test_chat_uses_think_false(monkeypatch):
    monkeypatch.setattr(parser, "_THINK_SUPPORTED", True)
    calls = []

    def fake_chat(**kwargs):
        calls.append(dict(kwargs))
        return FakeResponse('{"action":"mute"}')

    monkeypatch.setattr(parser.ollama, "chat", fake_chat)
    parser._chat("hello", "test-model")
    assert calls[0]["think"] is False


def test_chat_falls_back_to_no_think(monkeypatch):
    monkeypatch.setattr(parser, "_THINK_SUPPORTED", True)
    calls = []

    def fake_chat(**kwargs):
        calls.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        if "think" in kwargs:
            raise TypeError("unexpected keyword argument 'think'")
        return FakeResponse('{"action":"mute"}')

    monkeypatch.setattr(parser.ollama, "chat", fake_chat)
    parser._chat("hello", "test-model")
    assert "think" not in calls[1]
    assert "/no_think" in calls[1]["messages"][0]["content"]
    assert parser._THINK_SUPPORTED is False


# --------------------------------------------------------------------------- fast paths
@pytest.mark.parametrize("text,action", [
    ("mute", "mute"),
    ("unmute", "unmute"),
    ("volume up", "volume_up"),
    ("ارفع الصوت", "volume_up"),
    ("وطي الصوت", "volume_down"),
])
def test_fast_volume_commands(text, action):
    assert parser._fast_path(text)["action"] == action


def test_fast_set_volume():
    cmd = parser._fast_path("خلي الصوت 50")
    assert cmd["action"] == "set_volume"
    assert cmd["level"] == 50


def test_fast_open_known_app():
    cmd = parser._fast_path("open chrome")
    assert cmd["action"] == "open_app"
    assert cmd["app"] == "chrome"


def test_fast_open_known_site():
    cmd = parser._fast_path("افتح يوتيوب")
    assert cmd["action"] == "open_website"
    assert cmd["site"] == "youtube"


def test_fast_path_does_not_hijack_search():
    assert parser._fast_path("open google and search for cats") is None
    assert parser._fast_path("search for volume 50") is None
    assert parser._fast_path("what's my commute") is None
    assert parser._fast_path("muted") is None
    assert parser._fast_path("silence of the lambs") is None


def test_fast_set_volume_mixed_transcript():
    cmd = parser._fast_path("[ar] خلي الصوت 40 || [en] set the volume to 40")
    assert cmd["action"] == "set_volume"
    assert cmd["level"] == 40


def test_fast_path_skips_model(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(parser, "_chat", fail)
    assert parser.understand_command("open chrome")["action"] == "open_app"


# --------------------------------------------------------------------------- executor
def test_every_action_has_a_handler():
    assert set(executor._HANDLERS) == set(ActionName.__args__) - {"unknown"}


@pytest.mark.parametrize("answer", ["y", "yes", "Yes!", "نعم", "أيوه"])
def test_dangerous_action_confirmed(monkeypatch, answer):
    spawned = []
    monkeypatch.setattr(executor, "_spawn", lambda cmd: spawned.append(cmd))
    result = executor.execute({"action": "shutdown"}, confirm=lambda question: answer)
    assert "Shutting down" in result
    assert spawned == [["shutdown", "/s", "/t", "15"]]


@pytest.mark.parametrize("answer", ["n", "no", "لا", "", "maybe"])
def test_dangerous_action_cancelled(monkeypatch, answer):
    spawned = []
    monkeypatch.setattr(executor, "_spawn", lambda cmd: spawned.append(cmd))
    assert executor.execute({"action": "shutdown"}, confirm=lambda question: answer) == "Cancelled"
    assert spawned == []


def test_dangerous_action_cancelled_when_stdin_closes(monkeypatch):
    spawned = []
    monkeypatch.setattr(executor, "_spawn", lambda cmd: spawned.append(cmd))

    def closed_stdin(question):
        raise EOFError

    assert executor.execute({"action": "shutdown"}, confirm=closed_stdin) == "Cancelled"
    assert spawned == []


def test_unknown_app_is_not_launched(monkeypatch):
    launched = []
    monkeypatch.setattr(executor, "_launch_app", lambda resolved: launched.append(resolved) or True)
    result = executor.execute({"action": "open_app", "app": "definitely-not-installed-xyz"},
                              confirm=lambda question: "n")
    assert result.startswith("❌ App not found")
    assert launched == []


def test_web_search_encodes_the_query(monkeypatch):
    opened = []
    monkeypatch.setattr(executor, "_open_url",
                        lambda url, browser=None: opened.append((url, browser)) or "default browser")
    result = executor.execute({"action": "web_search", "query": "a&b c", "engine": "google"},
                              confirm=lambda question: "n")
    assert opened == [("https://www.google.com/search?q=a%26b+c", None)]
    assert "a&b c" in result


def test_web_search_drops_invalid_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(executor, "_open_url",
                        lambda url, browser=None: opened.append((url, browser)) or "default browser")
    executor.execute({"action": "web_search", "query": "cats", "browser": "evil"},
                     confirm=lambda question: "n")
    assert opened[0][1] is None


def test_web_search_reports_browser_failure(monkeypatch):
    monkeypatch.setattr(executor.webbrowser, "open", lambda url: False)
    result = executor.execute({"action": "web_search", "query": "cats"},
                              confirm=lambda question: "n")
    assert "Could not open the browser" in result


def test_open_website_whitelist(monkeypatch):
    opened = []
    monkeypatch.setattr(executor, "_open_url", lambda url, browser=None: opened.append(url))
    result = executor.execute({"action": "open_website", "site": "evil"}, confirm=lambda question: "n")
    assert "not allowed" in result
    assert opened == []


def test_volume_handlers_use_exact_percent(monkeypatch):
    monkeypatch.setattr(executor, "_step_volume", lambda delta: 40)
    assert "40%" in executor.execute({"action": "volume_up"}, confirm=lambda question: "n")

    monkeypatch.setattr(executor, "_set_volume_percent", lambda level: level)
    assert "55%" in executor.execute({"action": "set_volume", "level": 55},
                                     confirm=lambda question: "n")


def test_volume_handlers_are_offline(monkeypatch):
    monkeypatch.setattr(executor, "_set_mute", lambda muted: muted)
    assert "Muted" in executor.execute({"action": "mute"}, confirm=lambda question: "n")
    assert "Unmuted" in executor.execute({"action": "unmute"}, confirm=lambda question: "n")


def test_invalid_volume_level():
    assert executor.execute({"action": "set_volume", "level": "abc"},
                            confirm=lambda question: "n") == "❌ Invalid volume level"


def test_unknown_action():
    result = executor.execute({"action": "format_drive"}, confirm=lambda question: "n")
    assert "Didn't understand" in result


def test_folder_name_cleaning_blocks_traversal():
    assert executor._clean_name("../evil") == "evil"
    assert executor._clean_name(r"..\evil") == "evil"
    assert executor._clean_name("") == ""
    assert executor._clean_name(None) == ""
