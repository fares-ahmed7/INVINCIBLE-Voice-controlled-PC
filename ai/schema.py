"""
Shared command contract (JSON) between the AI module and the Command Manager.

Anyone who adds a new action MUST update it here, and then:
  - the SYSTEM_PROMPT in command_parser.py (add an example)
  - the executor mapping in executor.py
  - tests/test_cases.json

New apps do NOT need changes here: add a manual override in ai/apps.py, or let the
Start Menu auto-discovery in ai/app_registry.py find them.
"""
from typing import Literal, Optional

from pydantic import BaseModel

# "app" is free text from the model. It is sanitized and matched against the whitelist
# (manual apps + discovered Start Menu shortcuts) in ai/app_registry.py - never executed.

SiteName = Literal["google", "youtube", "facebook", "gmail", "github", "whatsapp", "wikipedia"]
EngineName = Literal["google", "youtube"]

ActionName = Literal[
    "open_app",
    "web_search",
    "open_website",
    "create_folder",
    "open_folder",
    "volume_up",
    "volume_down",
    "mute",
    "shutdown",
    "unknown",
]


class Command(BaseModel):
    action: ActionName
    app: Optional[str] = None   # used with open_app
    name: Optional[str] = None      # used with create_folder / open_folder
    query: Optional[str] = None     # used with web_search
    engine: Optional[EngineName] = None  # used with web_search (default: google)
    site: Optional[SiteName] = None # used with open_website
    browser: Optional[str] = None   # used with web_search: chrome / edge / firefox (default: system browser)
