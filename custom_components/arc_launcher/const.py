"""Constants for the Arc Launcher integration."""

from datetime import timedelta

DOMAIN = "arc_launcher"

DEFAULT_PORT = 47474
API_PREFIX = "/arc-launcher/v1"
CLIENT_NAME = "Home Assistant"

SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = 10
# Sync and restore wait for the TV to fetch or apply a whole layout.
LONG_REQUEST_TIMEOUT = 60

BACKUP_FORMAT = "arc-launcher-backup"

CONF_QUICK_ACTIONS = "quick_actions"
CONF_WEBHOOK_ID = "webhook_id"
EVENT_QUICK_ACTION = "arc_launcher_quick_action"
MAX_QUICK_ACTIONS = 6
MAX_LABEL_LENGTH = 24

# Icons the launcher can draw on its status bar; unknown names fall back to gesture-tap.
QUICK_ACTION_ICONS = [
    "gesture-tap",
    "movie",
    "television",
    "lightbulb",
    "lightbulb-off",
    "lamp",
    "ceiling-light",
    "bed",
    "weather-night",
    "power",
    "home",
    "door",
    "lock",
    "lock-open",
    "thermometer",
    "fan",
    "music",
    "play",
    "pause",
    "stop",
    "volume-high",
    "volume-off",
    "sofa",
    "star",
    "palette",
    "gamepad-variant",
    "coffee",
    "bell",
    "account",
    "blinds",
    "garage",
    "robot-vacuum",
]
