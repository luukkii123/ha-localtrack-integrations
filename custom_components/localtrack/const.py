"""Constants for the Local Track integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "localtrack"

# Config / options keys.
CONF_ENTITIES: Final = "entities"
CONF_RETENTION_DAYS: Final = "retention_days"
CONF_MIN_DISTANCE_M: Final = "min_distance_m"
CONF_MIN_INTERVAL_S: Final = "min_interval_s"
CONF_DOWNSAMPLE_AFTER_DAYS: Final = "downsample_after_days"
CONF_DOWNSAMPLE_INTERVAL_S: Final = "downsample_interval_s"

# Defaults, taken from docs/brainstorm/location-timeline-plan.md.
DEFAULT_RETENTION_DAYS: Final = 400
DEFAULT_MIN_DISTANCE_M: Final = 20
DEFAULT_MIN_INTERVAL_S: Final = 30
DEFAULT_DOWNSAMPLE_AFTER_DAYS: Final = 30
DEFAULT_DOWNSAMPLE_INTERVAL_S: Final = 300

# Bounds for the config flow. Wide enough to be useful, narrow enough that a
# typo cannot fill the disk or freeze the event loop.
MIN_RETENTION_DAYS: Final = 1
MAX_RETENTION_DAYS: Final = 3650
MIN_DISTANCE_LIMIT_M: Final = 0
MAX_DISTANCE_LIMIT_M: Final = 5000
MIN_INTERVAL_LIMIT_S: Final = 1
MAX_INTERVAL_LIMIT_S: Final = 86400
MIN_DOWNSAMPLE_AFTER_DAYS: Final = 1
MAX_DOWNSAMPLE_AFTER_DAYS: Final = 3650
MIN_DOWNSAMPLE_INTERVAL_S: Final = 10
MAX_DOWNSAMPLE_INTERVAL_S: Final = 86400

# Only these domains carry a person's position. Everything else is ignored
# before a single attribute is read.
TRACKED_DOMAINS: Final = ("person", "device_tracker")

# One SQLite file next to Home Assistant's own storage, independent of the
# recorder database and therefore untouched by `purge_keep_days`.
DB_FILENAME: Final = ".storage/localtrack.db"

# Retention and downsampling run once a day; neither is time critical.
MAINTENANCE_INTERVAL: Final = timedelta(hours=24)

WS_TYPE_HISTORY: Final = "localtrack/history"
WS_TYPE_STATS: Final = "localtrack/stats"

# ── Import aus dem Recorder ────────────────────────────────────────────────
SERVICE_IMPORT_HISTORY: Final = "import_history"

ATTR_DAYS: Final = "days"
ATTR_OVERWRITE: Final = "overwrite"
ATTR_DRY_RUN: Final = "dry_run"

# How far back an import may reach. The recorder's own `purge_keep_days`
# usually cuts in long before this — measured on the development instance the
# window was about seven days — but the service must not depend on a setting it
# cannot read, so it simply asks for the range and takes what comes back.
DEFAULT_IMPORT_DAYS: Final = 30
MIN_IMPORT_DAYS: Final = 1
MAX_IMPORT_DAYS: Final = 400

# The recorder is queried one calendar day at a time. A dense tracker produces
# tens of thousands of rows per day; asking for a whole month in one go would
# hold all of them in memory at once for no gain.
IMPORT_CHUNK = timedelta(days=1)

DEFAULT_MAX_POINTS: Final = 2000
MIN_MAX_POINTS: Final = 2
MAX_MAX_POINTS: Final = 50000
