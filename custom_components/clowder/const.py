"""Constants for Clowder."""

DOMAIN = "clowder"
EVENT_VISIT = "esphome.clowder_visit"
EVENT_HELLO = "esphome.clowder_hello"
WINDOW_S = 7 * 86400
DEDUPE_KEYS = 64
MAX_SLOT = 6
CONF_MAX_WEIGHT_JUMP = "max_weight_jump"
DEFAULT_MAX_WEIGHT_JUMP = 3.0  # lb; the robots' cat_ble_max_weight_jump before Clowder
STORAGE_KEY = "clowder"
STORAGE_VERSION = 1
