"""How a raw attribute bag becomes a point, and which points survive.

Kept free of Home Assistant imports, like `geo.py`, and for the same reason: the
live state listener and the recorder import must thin *identically*, or a day
that was backfilled would look denser or sparser than the day after it. A rule
that lives inside an event handler cannot be shared — nor tested on its own.
"""

from __future__ import annotations

from typing import Any, Mapping

from .geo import haversine_m

ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_GPS_ACCURACY = "gps_accuracy"


def read_position(
    attributes: Mapping[str, Any],
) -> tuple[float, float, float | None] | None:
    """Pull (lat, lon, accuracy) out of a state's attributes, or None.

    Returns None for every state that carries no usable position — that is the
    common case, not an error: most updates of a `person` entity are attribute
    changes such as `last_time_reachable`, and a tracker that has lost its fix
    reports no coordinates at all.
    """
    latitude = attributes.get(ATTR_LATITUDE)
    longitude = attributes.get(ATTR_LONGITUDE)
    if latitude is None or longitude is None:
        return None

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    try:
        raw_accuracy = attributes.get(ATTR_GPS_ACCURACY)
        accuracy = None if raw_accuracy is None else float(raw_accuracy)
    except (TypeError, ValueError):
        accuracy = None

    return lat, lon, accuracy


class PointThinner:
    """Keeps a point if it moved far enough *or* waited long enough.

    The distance half kills GPS jitter while standing still; the time half
    guarantees a heartbeat so a long stay still has points to draw.

    One instance owns the "last accepted point" per entity. The live listener
    and an import run therefore use *separate* instances: an import walks
    through last week, and letting it move the listener's idea of "the last
    point" would make the next live point look older than it is.
    """

    def __init__(self, min_distance_m: float, min_interval_s: float) -> None:
        """Thresholds are fixed for the lifetime of one instance."""
        self.min_distance_m = float(min_distance_m)
        self.min_interval_s = float(min_interval_s)
        self._last: dict[str, tuple[float, float, float]] = {}

    def seed(self, entity_id: str, ts: float, lat: float, lon: float) -> None:
        """Set the reference point without producing a decision.

        Used at startup from the newest stored point, so a restart does not
        append a duplicate of it.
        """
        self._last[entity_id] = (ts, lat, lon)

    def last(self, entity_id: str) -> tuple[float, float, float] | None:
        """The last accepted point of one entity, or None."""
        return self._last.get(entity_id)

    def accept(self, entity_id: str, ts: float, lat: float, lon: float) -> bool:
        """Decide, and on a yes remember the point as the new reference."""
        previous = self._last.get(entity_id)
        if previous is not None:
            last_ts, last_lat, last_lon = previous
            near_in_time = (ts - last_ts) < self.min_interval_s
            near_in_space = (
                haversine_m(last_lat, last_lon, lat, lon) < self.min_distance_m
            )
            if near_in_time and near_in_space:
                return False
        self._last[entity_id] = (ts, lat, lon)
        return True
