"""Constants for KSLive."""

from datetime import timedelta

DOMAIN = "kslive"
NAME = "KSLive"

API_BASE_URL = "https://api.uscreen.io/api/v2"
STORE_ID = "123283"
# Public identifier embedded in the official KSLive subscriber application.
STORE_TOKEN = "Zhc7XK/8EDU0RA=="
APP_VERSION = "3.35.0"
APP_PLATFORM = "android"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"
CONF_DEVICE_ID = "device_id"
CONF_MEDIA_PLAYERS = "media_players"
CONF_SEARCH_QUERY = "search_query"
CONF_IDLE_SLEEP = "idle_sleep"

DEFAULT_SEARCH_QUERY = "Audio"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

PLATFORMS = ["sensor", "button", "media_player", "select", "number", "switch"]

ALL_SPEAKERS_SOURCE = "All configured speakers"
MEDIA_ID_PREFIX = "kslive:"

SERVICE_PLAY = "play"
ATTR_CONTENT_ID = "content_id"
ATTR_MEDIA_PLAYERS = "media_players"
