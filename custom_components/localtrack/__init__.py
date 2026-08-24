"""Local Track — long term GPS history for person and device_tracker entities.

Home Assistant's recorder keeps positions for `purge_keep_days` and that setting
is global: either every entity is kept for years or none is. This integration
writes the positions it cares about into its own SQLite file, deduplicated and
thinned out, and hands them to the frontend over one websocket command.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DOWNSAMPLE_AFTER_DAYS,
    CONF_DOWNSAMPLE_INTERVAL_S,
    CONF_ENTITIES,
    CONF_MIN_DISTANCE_M,
    CONF_MIN_INTERVAL_S,
    CONF_RETENTION_DAYS,
    DB_FILENAME,
    DEFAULT_DOWNSAMPLE_AFTER_DAYS,
    DEFAULT_DOWNSAMPLE_INTERVAL_S,
    DEFAULT_MAX_POINTS,
    DEFAULT_MIN_DISTANCE_M,
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    MAINTENANCE_INTERVAL,
    MAX_MAX_POINTS,
    MIN_MAX_POINTS,
    TRACKED_DOMAINS,
    WS_TYPE_HISTORY,
    WS_TYPE_STATS,
)
from .geo import haversine_m, simplify_to_max
from .store import LocationStore

_LOGGER = logging.getLogger(__name__)

# Assignment instead of `type ...` (PEP 695) so the file still parses on the
# Python that happens to sit on the development machine.
LocalTrackConfigEntry = ConfigEntry["LocalTrackRuntime"]

_WS_REGISTERED = "websocket_registered"

ATTR_GPS_ACCURACY = "gps_accuracy"


def _setting(entry: LocalTrackConfigEntry, key: str, default: Any) -> Any:
    """Options win over data — options are what the user edits afterwards."""
    return entry.options.get(key, entry.data.get(key, default))


class LocalTrackRuntime:
    """Everything one config entry owns: the store, the listener, the timer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: LocalTrackConfigEntry,
        store: LocationStore,
    ) -> None:
        """Read the settings once — a reload rebuilds this object anyway."""
        self.hass = hass
        self.entry = entry
        self.store = store

        self.entities: set[str] = {
            entity_id
            for entity_id in _setting(entry, CONF_ENTITIES, [])
            if entity_id.split(".", 1)[0] in TRACKED_DOMAINS
        }
        self.retention_days: int = int(
            _setting(entry, CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
        )
        self.min_distance_m: float = float(
            _setting(entry, CONF_MIN_DISTANCE_M, DEFAULT_MIN_DISTANCE_M)
        )
        self.min_interval_s: float = float(
            _setting(entry, CONF_MIN_INTERVAL_S, DEFAULT_MIN_INTERVAL_S)
        )
        self.downsample_after_days: int = int(
            _setting(entry, CONF_DOWNSAMPLE_AFTER_DAYS, DEFAULT_DOWNSAMPLE_AFTER_DAYS)
        )
        self.downsample_interval_s: float = float(
            _setting(entry, CONF_DOWNSAMPLE_INTERVAL_S, DEFAULT_DOWNSAMPLE_INTERVAL_S)
        )

        # entity_id -> (ts, lat, lon) of the last point actually written.
        self._last: dict[str, tuple[float, float, float]] = {}
        self._unsubscribe: list[Any] = []

    async def async_start(self) -> None:
        """Seed the dedupe state, then start listening and pruning."""
        for entity_id in self.entities:
            point = await self.store.last_point(entity_id)
            if point is not None:
                self._last[entity_id] = (point["ts"], point["lat"], point["lon"])

        self._unsubscribe.append(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._handle_state_changed)
        )
        self._unsubscribe.append(
            async_track_time_interval(
                self.hass, self._async_maintain, MAINTENANCE_INTERVAL
            )
        )
        _LOGGER.debug(
            "Local Track watching %s (retention %s d, dedupe %s m / %s s)",
            sorted(self.entities),
            self.retention_days,
            self.min_distance_m,
            self.min_interval_s,
        )

    async def async_stop(self) -> None:
        """Detach from the bus and close the database."""
        while self._unsubscribe:
            self._unsubscribe.pop()()
        await self.store.async_close()

    # ── Listener ──────────────────────────────────────────────────────────

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        """Filter, deduplicate, and hand the survivor to a background task.

        Stays a plain callback: the event bus must not wait for a disk write.
        """
        entity_id = event.data.get("entity_id")
        if entity_id not in self.entities:
            return

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        attributes = new_state.attributes
        latitude = attributes.get(ATTR_LATITUDE)
        longitude = attributes.get(ATTR_LONGITUDE)
        # A state change without coordinates is an attribute update such as
        # `last_time_reachable` — the noise the plan warns about. Drop it here,
        # before anything touches the database.
        if latitude is None or longitude is None:
            return

        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            return
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return

        timestamp = new_state.last_updated.timestamp()
        if not self._should_store(entity_id, timestamp, lat, lon):
            return

        accuracy: float | None
        try:
            raw_accuracy = attributes.get(ATTR_GPS_ACCURACY)
            accuracy = None if raw_accuracy is None else float(raw_accuracy)
        except (TypeError, ValueError):
            accuracy = None

        self._last[entity_id] = (timestamp, lat, lon)
        self.entry.async_create_background_task(
            self.hass,
            self.store.insert_point(entity_id, timestamp, lat, lon, accuracy),
            name=f"localtrack insert {entity_id}",
        )

    def _should_store(
        self, entity_id: str, timestamp: float, lat: float, lon: float
    ) -> bool:
        """Keep a point if it moved far enough *or* waited long enough.

        The distance half kills GPS jitter while standing still; the time half
        guarantees a heartbeat so a long stay still has points to draw.
        """
        previous = self._last.get(entity_id)
        if previous is None:
            return True
        last_ts, last_lat, last_lon = previous
        elapsed = timestamp - last_ts
        if elapsed >= self.min_interval_s:
            return True
        return haversine_m(last_lat, last_lon, lat, lon) >= self.min_distance_m

    # ── Retention and downsampling ────────────────────────────────────────

    async def _async_maintain(self, now: datetime | None = None) -> None:
        """Daily housekeeping: drop the ancient, thin out the merely old."""
        current = time.time()
        try:
            deleted = await self.store.delete_before(
                current - self.retention_days * 86400
            )
            older_than = current - self.downsample_after_days * 86400
            thinned = 0
            for entity_id in await self.store.async_tracked_entities():
                thinned += await self.store.downsample(
                    entity_id, older_than, self.downsample_interval_s
                )
            if deleted or thinned:
                await self.store.async_reclaim()
                _LOGGER.debug(
                    "Local Track maintenance: %s expired, %s thinned out",
                    deleted,
                    thinned,
                )
        except Exception:  # noqa: BLE001 - a failed prune must not kill the timer
            _LOGGER.exception("Local Track maintenance failed")


async def async_setup_entry(hass: HomeAssistant, entry: LocalTrackConfigEntry) -> bool:
    """Open the store, start the listener, publish the websocket command."""
    store = LocationStore(hass.config.path(DB_FILENAME))
    await store.async_open()

    runtime = LocalTrackRuntime(hass, entry, store)
    await runtime.async_start()

    entry.runtime_data = runtime
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    _async_register_websocket_api(hass)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LocalTrackConfigEntry) -> bool:
    """Stop listening and close the file. The data stays on disk."""
    runtime: LocalTrackRuntime | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if runtime is not None:
        await runtime.async_stop()
    return True


async def async_reload_entry(hass: HomeAssistant, entry: LocalTrackConfigEntry) -> None:
    """Options changed (entities, retention, dedupe) — rebuild the runtime."""
    await hass.config_entries.async_reload(entry.entry_id)


# ── Websocket API ─────────────────────────────────────────────────────────


@callback
def _async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the commands once per Home Assistant run."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_WS_REGISTERED):
        return
    websocket_api.async_register_command(hass, _ws_history)
    websocket_api.async_register_command(hass, _ws_stats)
    domain_data[_WS_REGISTERED] = True


@callback
def _get_runtime(hass: HomeAssistant) -> LocalTrackRuntime | None:
    """The single loaded runtime, or None while the entry is unloaded."""
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, LocalTrackRuntime):
            return value
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_HISTORY,
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("start"): cv.datetime,
        vol.Required("end"): cv.datetime,
        vol.Optional("max_points", default=DEFAULT_MAX_POINTS): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_MAX_POINTS, max=MAX_MAX_POINTS)
        ),
    }
)
@websocket_api.async_response
async def _ws_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the stored track of one entity for one time range.

    `start`/`end` may be naive — those are read as the Home Assistant host's
    local time, which is what "a day" has to mean for a timeline.
    """
    runtime = _get_runtime(hass)
    if runtime is None:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            "Local Track is not set up",
        )
        return

    start = dt_util.as_utc(msg["start"]).timestamp()
    end = dt_util.as_utc(msg["end"]).timestamp()
    if end < start:
        start, end = end, start

    points = await runtime.store.query_range(msg["entity_id"], start, end)
    total = len(points)
    max_points = msg["max_points"]
    if total > max_points:
        # Douglas-Peucker is CPU bound; keep it off the event loop.
        points = await hass.async_add_executor_job(
            simplify_to_max, points, max_points
        )

    connection.send_result(
        msg["id"],
        {
            "entity_id": msg["entity_id"],
            "points": points,
            "total": total,
            "simplified": total != len(points),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): WS_TYPE_STATS})
@websocket_api.async_response
async def _ws_stats(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Row counts and covered time span, so a card can tell empty from missing."""
    runtime = _get_runtime(hass)
    if runtime is None:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            "Local Track is not set up",
        )
        return

    stats = await runtime.store.async_stats()
    stats["tracked"] = sorted(runtime.entities)
    connection.send_result(msg["id"], stats)
