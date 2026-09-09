"""Local Track — long term GPS history for person and device_tracker entities.

Home Assistant's recorder keeps positions for `purge_keep_days` and that setting
is global: either every entity is kept for years or none is. This integration
writes the positions it cares about into its own SQLite file, deduplicated and
thinned out, and hands them to the frontend over one websocket command.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DAYS,
    ATTR_DRY_RUN,
    ATTR_OVERWRITE,
    CONF_DOWNSAMPLE_AFTER_DAYS,
    CONF_DOWNSAMPLE_INTERVAL_S,
    CONF_ENTITIES,
    CONF_MIN_DISTANCE_M,
    CONF_MIN_INTERVAL_S,
    CONF_RETENTION_DAYS,
    DB_FILENAME,
    DEFAULT_DOWNSAMPLE_AFTER_DAYS,
    DEFAULT_DOWNSAMPLE_INTERVAL_S,
    DEFAULT_IMPORT_DAYS,
    DEFAULT_MAX_GAP_S,
    DEFAULT_MAX_POINTS,
    DEFAULT_MIN_DISTANCE_M,
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_MIN_VISIT_S,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    MAINTENANCE_INTERVAL,
    MAX_IMPORT_DAYS,
    MAX_GAP_LIMIT_S,
    MAX_MAX_POINTS,
    MAX_VISIT_LIMIT_S,
    MAX_ZONE_TIME_DAYS,
    MIN_IMPORT_DAYS,
    MIN_GAP_LIMIT_S,
    MIN_MAX_POINTS,
    MIN_VISIT_LIMIT_S,
    SERVICE_IMPORT_HISTORY,
    TRACKED_DOMAINS,
    WS_TYPE_HISTORY,
    WS_TYPE_STATS,
    WS_TYPE_ZONE_TIME,
)
from .geo import simplify_to_max
from .importer import RecorderUnavailable, async_import
from .sampling import PointThinner, read_position
from .store import LocationStore
from .zonetime import compute_zone_time

_LOGGER = logging.getLogger(__name__)

# Assignment instead of `type ...` (PEP 695) so the file still parses on the
# Python that happens to sit on the development machine.
LocalTrackConfigEntry = ConfigEntry["LocalTrackRuntime"]

_WS_REGISTERED = "websocket_registered"
_SERVICES_REGISTERED = "services_registered"

IMPORT_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Optional(ATTR_DAYS, default=DEFAULT_IMPORT_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_IMPORT_DAYS, max=MAX_IMPORT_DAYS)
        ),
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
        vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
    }
)


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

        # Shared with the recorder import, so a backfilled day comes out as
        # dense as a recorded one. This instance belongs to the listener alone.
        self.thinner = PointThinner(self.min_distance_m, self.min_interval_s)
        self._unsubscribe: list[Any] = []

    async def async_start(self) -> None:
        """Seed the dedupe state, then start listening and pruning."""
        for entity_id in self.entities:
            point = await self.store.last_point(entity_id)
            if point is not None:
                self.thinner.seed(
                    entity_id, point["ts"], point["lat"], point["lon"]
                )

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

        # A state change without coordinates is an attribute update such as
        # `last_time_reachable` — the noise the plan warns about. Drop it here,
        # before anything touches the database.
        position = read_position(new_state.attributes)
        if position is None:
            return
        lat, lon, accuracy = position

        timestamp = new_state.last_updated.timestamp()
        if not self.thinner.accept(entity_id, timestamp, lat, lon):
            return

        self.entry.async_create_background_task(
            self.hass,
            self.store.insert_point(entity_id, timestamp, lat, lon, accuracy),
            name=f"localtrack insert {entity_id}",
        )

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
    try:
        await store.async_open()
    except Exception as err:  # noqa: BLE001 - sqlite raises a wide family here
        # Quality scale `test-before-setup`: a locked or unreadable database
        # file has to become a retry, not a stack trace during startup.
        raise ConfigEntryNotReady(
            f"Local Track database could not be opened: {err}"
        ) from err

    runtime = LocalTrackRuntime(hass, entry, store)
    await runtime.async_start()

    entry.runtime_data = runtime
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    _async_register_websocket_api(hass)
    _async_register_services(hass)
    _async_schedule_initial_import(hass, entry, runtime)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


@callback
def _async_schedule_initial_import(
    hass: HomeAssistant, entry: LocalTrackConfigEntry, runtime: LocalTrackRuntime
) -> None:
    """Backfill entities that hold no points yet, once Home Assistant is up.

    "Has this entry ever been imported?" is deliberately **not** remembered in
    the entry: writing a flag into the options fires the update listener and
    reloads the entry, and the flag would then also have to be migrated. The
    data answers the question by itself — an entity with points has been
    covered, an entity without any has not. That is self-limiting (a successful
    import stops the next one) and does the right thing when the user adds a
    new person later or deletes the database on purpose.

    An empty recorder therefore means one wasted query per entity per restart.
    That is the honest price of not keeping a flag, and it is paid in
    milliseconds.
    """

    async def _run(_now: Any = None) -> None:
        pending = []
        for entity_id in sorted(runtime.entities):
            if await runtime.store.last_point(entity_id) is None:
                pending.append(entity_id)
        if not pending:
            return
        _LOGGER.info(
            "Local Track: no stored points for %s — importing from the recorder",
            ", ".join(pending),
        )
        try:
            await async_import(hass, runtime, pending, DEFAULT_IMPORT_DAYS)
        except RecorderUnavailable as err:
            _LOGGER.warning("Local Track: initial import skipped — %s", err)
        except Exception:  # noqa: BLE001 - a failed backfill must not kill setup
            _LOGGER.exception("Local Track: initial import failed")

    @callback
    def _start(_hass: HomeAssistant) -> None:
        # Not awaited inside setup: the recorder may still be catching up, and
        # a backfill of several days must never hold up Home Assistant's start.
        entry.async_create_background_task(
            hass, _run(), name="localtrack initial import"
        )

    entry.async_on_unload(async_at_started(hass, _start))


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the import service once per Home Assistant run."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_SERVICES_REGISTERED):
        return

    async def _handle_import(call: ServiceCall) -> ServiceResponse:
        runtime = _get_runtime(hass)
        if runtime is None:
            raise HomeAssistantError("Local Track is not set up")

        requested = call.data.get("entity_id") or sorted(runtime.entities)
        unknown = [item for item in requested if item not in runtime.entities]
        if unknown:
            # Importing an entity that nothing records afterwards would leave a
            # stub of history that never grows — almost certainly a typo.
            raise HomeAssistantError(
                "Local Track does not record " + ", ".join(unknown)
            )

        try:
            return await async_import(
                hass,
                runtime,
                list(requested),
                call.data[ATTR_DAYS],
                overwrite=call.data[ATTR_OVERWRITE],
                dry_run=call.data[ATTR_DRY_RUN],
            )
        except RecorderUnavailable as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        _handle_import,
        schema=IMPORT_HISTORY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    domain_data[_SERVICES_REGISTERED] = True


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
    websocket_api.async_register_command(hass, _ws_zone_time)
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_ZONE_TIME,
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("latitude"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Required("longitude"): vol.All(
            vol.Coerce(float), vol.Range(min=-180, max=180)
        ),
        vol.Required("radius"): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=100000)
        ),
        vol.Required("start"): cv.datetime,
        vol.Required("end"): cv.datetime,
        vol.Optional("min_visit_s", default=DEFAULT_MIN_VISIT_S): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_VISIT_LIMIT_S, max=MAX_VISIT_LIMIT_S)
        ),
        vol.Optional("max_gap_s", default=DEFAULT_MAX_GAP_S): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_GAP_LIMIT_S, max=MAX_GAP_LIMIT_S)
        ),
    }
)
@websocket_api.async_response
async def _ws_zone_time(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Verweildauer je Tag im Umkreis eines Punktes.

    Die Karte schickt Mittelpunkt und Radius mit, statt eine Zonen-ID: so muss
    diese Integration nichts ueber Zonen wissen, bleibt unabhaengig von deren
    Attributnamen — und derselbe Befehl beantwortet auch "wie lange war ich im
    Umkreis von 200 m um diesen Punkt", ohne dass es dafuer eine Zone braucht.

    Die Tagesgrenzen sind lokale Mitternacht des HA-Hosts, nicht des Browsers:
    ein Haushalt soll dieselbe Zahl sehen, egal von welchem Geraet.
    """
    runtime = _get_runtime(hass)
    if runtime is None:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            "Local Track is not set up",
        )
        return

    start = dt_util.as_utc(msg["start"])
    end = dt_util.as_utc(msg["end"])
    if end < start:
        start, end = end, start
    if (end - start) > timedelta(days=MAX_ZONE_TIME_DAYS):
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_INVALID_FORMAT,
            f"Range is longer than {MAX_ZONE_TIME_DAYS} days",
        )
        return

    points = await runtime.store.query_range(
        msg["entity_id"], start.timestamp(), end.timestamp()
    )
    # CPU-gebunden bei zehntausenden Punkten — gehoert in einen Ausfuehrer,
    # genau wie `simplify_to_max` bei `localtrack/history`.
    result = await hass.async_add_executor_job(
        partial(
            compute_zone_time,
            points,
            msg["latitude"],
            msg["longitude"],
            msg["radius"],
            dt_util.DEFAULT_TIME_ZONE,
            msg["min_visit_s"],
            msg["max_gap_s"],
        )
    )
    result["entity_id"] = msg["entity_id"]
    result["from"] = start.isoformat()
    result["to"] = end.isoformat()
    connection.send_result(msg["id"], result)
