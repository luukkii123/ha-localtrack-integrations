"""Backfill the store from Home Assistant's own recorder.

Local Track starts empty: it only sees positions from the moment its config
entry exists. The recorder, however, has been writing `latitude`/`longitude`
into the attributes of every `person` and `device_tracker` all along — for as
long as `purge_keep_days` allows. That overlap is worth harvesting once.

Two things this module deliberately does **not** promise:

* **It cannot reach further back than the recorder.** Whatever the purge has
  already deleted is gone; no amount of querying brings it back. On the
  development instance the window was about a week.
* **It does not de-duplicate against itself row by row.** `points` has no
  unique key on (entity_id, ts), so the guard is coarser and more honest: a
  calendar day that already holds points is skipped unless the caller asks for
  `overwrite`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import IMPORT_CHUNK
from .sampling import PointThinner, read_position

_LOGGER = logging.getLogger(__name__)


class RecorderUnavailable(RuntimeError):
    """The recorder is not loaded, so there is nothing to import from."""


def _day_bounds(day_start: datetime) -> tuple[datetime, datetime]:
    """One chunk, half open at the end so two chunks cannot share a row."""
    return day_start, day_start + IMPORT_CHUNK


async def _fetch_states(
    hass: HomeAssistant, entity_id: str, start: datetime, end: datetime
) -> list[Any]:
    """Read one entity's raw recorder rows for one window.

    Runs on the recorder's own executor. Touching the recorder database from
    the event loop is the single most expensive mistake this integration could
    make — the same rule `store.py` states for its own SQLite file.

    `significant_changes_only=False` is the whole point: a person's *state* is
    the zone name and changes a handful of times a day, while the coordinates
    live in the attributes and change every few seconds. The significant-only
    filter would throw away exactly the rows worth importing.
    """
    # Imported lazily so the integration still loads on an installation that
    # runs without a recorder; the caller turns the ImportError into a clear
    # message rather than a traceback at setup time.
    #
    # `get_instance` is read twice on purpose. Checked against core-2026.8.3:
    # it is *defined* in `recorder.util` and only lands in the package
    # namespace through a plain `from .util import get_instance` — no `__all__`
    # entry, no `# noqa: F401` marking it as a re-export. The package path is
    # what integrations across core use and is tried first, but it is not a
    # promise, and a path that quietly disappears would fail at the user rather
    # than here.
    try:
        from homeassistant.components.recorder import history

        try:
            from homeassistant.components.recorder import get_instance
        except ImportError:  # pragma: no cover - depends on the HA version
            from homeassistant.components.recorder.util import get_instance
    except ImportError as err:  # pragma: no cover - depends on the installation
        raise RecorderUnavailable("Recorder integration is not available") from err

    if "recorder" not in hass.config.components:
        raise RecorderUnavailable("Recorder integration is not loaded")

    result = await get_instance(hass).async_add_executor_job(
        partial(
            history.get_significant_states,
            hass,
            start,
            end,
            [entity_id],
            include_start_time_state=False,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=False,
        )
    )
    return list(result.get(entity_id, []))


async def async_import_entity(
    hass: HomeAssistant,
    runtime: Any,
    entity_id: str,
    start: datetime,
    end: datetime,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Walk one entity's recorder history day by day and store what survives."""
    store = runtime.store
    # A thinner of its own, with the entry's live thresholds: imported days must
    # come out as dense as recorded ones, but the listener's reference point
    # must not be dragged back into last week.
    thinner = PointThinner(runtime.min_distance_m, runtime.min_interval_s)

    scanned = 0
    stored = 0
    days_written: list[str] = []
    days_skipped: list[str] = []
    days_empty: list[str] = []

    cursor = start
    while cursor < end:
        chunk_start, chunk_end = _day_bounds(cursor)
        if chunk_end > end:
            chunk_end = end
        cursor = chunk_end
        label = dt_util.as_local(chunk_start).date().isoformat()

        low = chunk_start.timestamp()
        # Inclusive upper bound in the store, so subtract a hair to keep the
        # chunks from overlapping on a point that sits exactly on midnight.
        high = chunk_end.timestamp() - 0.000001

        existing = await store.count_range(entity_id, low, high)
        if existing:
            if not overwrite:
                days_skipped.append(label)
                # Still seed the thinner from what is already there, otherwise
                # the first point of the next day would be measured against a
                # reference from two days ago.
                last = await store.last_point(entity_id)
                if last is not None:
                    thinner.seed(entity_id, last["ts"], last["lat"], last["lon"])
                continue
            if not dry_run:
                await store.delete_range(entity_id, low, high)

        states = await _fetch_states(hass, entity_id, chunk_start, chunk_end)
        rows: list[tuple[str, float, float, float, float | None]] = []
        for state in states:
            position = read_position(state.attributes)
            if position is None:
                continue
            scanned += 1
            lat, lon, accuracy = position
            timestamp = state.last_updated.timestamp()
            if not thinner.accept(entity_id, timestamp, lat, lon):
                continue
            rows.append((entity_id, timestamp, lat, lon, accuracy))

        if not rows:
            days_empty.append(label)
            continue
        if not dry_run:
            stored += await store.insert_points(rows)
        else:
            stored += len(rows)
        days_written.append(label)

    return {
        "entity_id": entity_id,
        "scanned": scanned,
        "stored": stored,
        "thinned_out": scanned - stored,
        "days_written": days_written,
        "days_skipped": days_skipped,
        "days_without_data": days_empty,
    }


async def async_import(
    hass: HomeAssistant,
    runtime: Any,
    entity_ids: list[str],
    days: int,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import several entities and summarise the run."""
    end = dt_util.utcnow()
    start = end - timedelta(days=days)

    results = []
    for entity_id in entity_ids:
        results.append(
            await async_import_entity(
                hass,
                runtime,
                entity_id,
                start,
                end,
                overwrite=overwrite,
                dry_run=dry_run,
            )
        )

    summary = {
        "dry_run": dry_run,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "scanned": sum(item["scanned"] for item in results),
        "stored": sum(item["stored"] for item in results),
        "entities": results,
    }
    _LOGGER.info(
        "Local Track import%s: %s positions read, %s stored, %s day(s) skipped",
        " (dry run)" if dry_run else "",
        summary["scanned"],
        summary["stored"],
        sum(len(item["days_skipped"]) for item in results),
    )
    return summary
