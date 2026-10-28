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
