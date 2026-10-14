"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the app runs without extra dependencies.

    Existing environment variables always win over values in the file.
    """
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    # "fake" runs entirely offline with simulated Ring devices; "live" calls the Ring API.
    ring_mode: str = "fake"
    ring_base_url: str = "https://api.amazonvision.com"
    ring_access_token: str = ""
    ring_hmac_key: str = ""
    # Device ID of the front-door doorbell/camera whose events drive access decisions.
    ring_front_door_device_id: str = "fake.front-door"
    # If > 0, also poll Ring Event History every N seconds (fallback when webhooks
    # can't reach this server, e.g. local development without a tunnel).
    ring_poll_seconds: int = 0

    # "fake" uses canned descriptions; "bedrock" sends snapshots to Amazon Bedrock.
    vision_mode: str = "fake"
    # "rules" answers questions without an LLM; "bedrock" uses a Strands agent on Bedrock.
    agent_mode: str = "rules"
    aws_region: str = "us-east-1"
    bedrock_vision_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_agent_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    db_path: str = "carekey.db"
    # IANA name such as "Asia/Singapore". Empty = this computer's timezone.
    timezone: str = ""

    # Care rules (minutes / local clock time).
    late_after_minutes: int = 15
    checkin_early_minutes: int = 15
    presence_window_minutes: int = 5
    unlock_seconds: int = 120
    linger_minutes: int = 3
    quiet_morning_by: str = "11:00"

    # Enables /api/demo/* endpoints that inject simulated events.
    demo_enabled: bool = True
    parent_name: str = "Mum"
    family_name: str = "Ravi"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def timezone_name(self) -> str:
        return self.timezone or system_timezone()


def system_timezone() -> str:
    """This computer's IANA timezone name, from the /etc/localtime symlink."""
    try:
        target = os.path.realpath("/etc/localtime")
        name = target.split("zoneinfo/", 1)[1]
        ZoneInfo(name)
        return name
    except (IndexError, OSError, KeyError, ValueError):
        return "UTC"


def load_settings(env_file: str | None = ".env") -> Settings:
    if env_file:
        _load_dotenv(Path(env_file))
    e = os.environ
    defaults = Settings()

    def get(name: str, default):
        raw = e.get(name.upper())
        if raw is None or raw == "":
            return default
        if isinstance(default, bool):
            return raw.lower() in {"1", "true", "yes", "on"}
        if isinstance(default, int):
            return int(raw)
        return raw

    values = {f: get(f, getattr(defaults, f)) for f in Settings.__dataclass_fields__}
    return Settings(**values)
