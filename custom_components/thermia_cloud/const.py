"""Constants for the Thermia Cloud integration."""

from __future__ import annotations

import json
from pathlib import Path

DOMAIN = "thermia_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REFRESH_TOKEN = "refresh_token"

# Options
CONF_INSTALLATIONS = "installations"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_READ_ONLY = "read_only"
CONF_TIMEOUT = "timeout"
CONF_SHOW_HIDDEN = "show_hidden"
CONF_EXPOSE_UNKNOWN = "expose_unknown"
CONF_DEBUG_ATTRIBUTES = "debug_attributes"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 600
DEFAULT_TIMEOUT = 30

VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
USER_AGENT = f"HomeAssistant thermia_cloud/{VERSION}"
