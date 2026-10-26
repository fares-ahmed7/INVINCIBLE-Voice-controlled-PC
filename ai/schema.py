"""
Shared command contract (JSON) between the AI module and the Command Manager.

Anyone who adds a new action/app MUST update it here, and then:
  - the SYSTEM_PROMPT in command_parser.py (add an example)
  - the executor mapping in executor.py
  - tests/test_cases.json
"""
from typing import Literal, Optional

from pydantic import BaseModel

# App names live in ai/apps.py. "app" is a plain string, validated against that list in code.

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
