"""SQLite layer for the long term location store.

Everything goes through `aiosqlite`. A plain `sqlite3` call would run inside the
event loop and freeze Home Assistant while the disk is busy — that is the single
most expensive mistake this integration could make (see the plan's "Fallstricke").

The file lives next to Home Assistant's own storage but is *not* the recorder
database: `purge_keep_days` never touches it, which is the whole point of the
integration.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiosqlite

_LOGGER = logging.getLogger(__name__)

# `ts` is a plain epoch float — no timezone ambiguity, cheap to compare and to
# bucket for downsampling. The index is what makes a day query a range scan
# instead of a full table scan.
SCHEMA = """
CREATE TABLE IF NOT EXISTS points (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id TEXT NOT NULL,
  ts REAL NOT NULL,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  accuracy REAL
);
CREATE INDEX IF NOT EXISTS idx_points_entity_ts ON points (entity_id, ts);
"""


class LocationStore:
    """One SQLite connection, serialised through a lock.

    SQLite handles a single writer anyway; the lock keeps the daily maintenance
    task from interleaving with an incoming GPS point mid-transaction.
    """

    def __init__(self, path: str) -> None:
        """Remember where the database file goes — no I/O yet."""
        self._path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def path(self) -> str:
        """Absolute path of the database file."""
        return self._path

    async def async_open(self) -> None:
        """Open the connection and make sure schema and pragmas are in place."""
        db = await aiosqlite.connect(self._path)
        db.row_factory = aiosqlite.Row
        # WAL keeps readers (the websocket query) from blocking the writer
        # (the state listener). NORMAL trades a fsync per commit for speed —
        # acceptable for GPS breadcrumbs, which are replaceable data.
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        # Only takes effect on a fresh file; on an existing one it is a no-op
        # until someone runs a full VACUUM. Harmless either way.
        await db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        await db.executescript(SCHEMA)
        await db.commit()
        self._db = db
        _LOGGER.debug("Location store opened at %s", self._path)

    async def async_close(self) -> None:
        """Close the connection. Safe to call twice."""
        db = self._db
        self._db = None
        if db is not None:
            async with self._lock:
                await db.close()

    def _require_db(self) -> aiosqlite.Connection:
        """Return the open connection or fail loudly."""
        if self._db is None:
            raise RuntimeError("Location store is not open")
        return self._db

    async def insert_point(
        self,
        entity_id: str,
        ts: float,
        lat: float,
        lon: float,
        accuracy: float | None,
    ) -> None:
        """Append one GPS point. Callers do the deduplication, not this method."""
        db = self._require_db()
        async with self._lock:
            await db.execute(
                "INSERT INTO points (entity_id, ts, lat, lon, accuracy)"
                " VALUES (?, ?, ?, ?, ?)",
                (entity_id, ts, lat, lon, accuracy),
            )
            await db.commit()

    async def insert_points(
        self, rows: list[tuple[str, float, float, float, float | None]]
    ) -> int:
        """Append many points in a single transaction. Returns the row count.

        Not a loop over `insert_point`: an import writes thousands of rows, and
        one `commit()` per row would fsync the disk thousands of times. That is
        the difference between a backfill that takes seconds and one that takes
        minutes while holding the store's lock.
        """
        if not rows:
            return 0
        db = self._require_db()
        async with self._lock:
            await db.executemany(
                "INSERT INTO points (entity_id, ts, lat, lon, accuracy)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            await db.commit()
        return len(rows)

    async def count_range(self, entity_id: str, start: float, end: float) -> int:
        """How many points of one entity already sit in [start, end].

        The import asks this before writing a day: `points` has no unique key on
        (entity_id, ts), so a second run over the same day would silently double
        it. Counting first is cheaper than adding a constraint to a table that
        may already hold duplicates from before.
        """
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "SELECT COUNT(*) AS n FROM points"
                " WHERE entity_id = ? AND ts >= ? AND ts <= ?",
                (entity_id, start, end),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return int(row["n"]) if row is not None else 0

    async def delete_range(self, entity_id: str, start: float, end: float) -> int:
        """Drop one entity's points in [start, end]. Returns rows deleted."""
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM points WHERE entity_id = ? AND ts >= ? AND ts <= ?",
                (entity_id, start, end),
            )
            deleted = cursor.rowcount
            await cursor.close()
            await db.commit()
        return max(0, deleted)

    async def query_range(
        self, entity_id: str, start: float, end: float
    ) -> list[dict[str, Any]]:
        """All points of one entity in [start, end], oldest first."""
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "SELECT ts, lat, lon, accuracy FROM points"
                " WHERE entity_id = ? AND ts >= ? AND ts <= ?"
                " ORDER BY ts ASC",
                (entity_id, start, end),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [
            {
                "ts": row["ts"],
                "lat": row["lat"],
                "lon": row["lon"],
                "accuracy": row["accuracy"],
            }
            for row in rows
        ]

    async def last_point(self, entity_id: str) -> dict[str, Any] | None:
        """Newest stored point of one entity, or None if there is none.

        Used once per entity at startup to seed the in-memory dedupe state, so a
        restart does not append a duplicate of the last point.
        """
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "SELECT ts, lat, lon, accuracy FROM points"
                " WHERE entity_id = ? ORDER BY ts DESC LIMIT 1",
                (entity_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        return {
            "ts": row["ts"],
            "lat": row["lat"],
            "lon": row["lon"],
            "accuracy": row["accuracy"],
        }

    async def delete_before(self, ts: float) -> int:
        """Drop every point older than `ts`. Returns the number of rows deleted."""
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute("DELETE FROM points WHERE ts < ?", (ts,))
            deleted = cursor.rowcount
            await cursor.close()
            await db.commit()
        return max(0, deleted)

    async def downsample(
        self, entity_id: str, older_than: float, min_interval: float
    ) -> int:
        """Thin out old points to at most one per `min_interval` seconds.

        Keeps the *first* point of every time bucket and deletes the rest. In
        SQLite a bare column next to `MIN()` is taken from the row that matched
        the aggregate, so the subquery yields exactly that row's id.
        """
        if min_interval <= 0:
            return 0
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM points"
                " WHERE entity_id = ? AND ts < ? AND id NOT IN ("
                "   SELECT id FROM ("
                "     SELECT id, MIN(ts) FROM points"
                "      WHERE entity_id = ? AND ts < ?"
                "      GROUP BY CAST(ts / ? AS INTEGER)"
                "   )"
                " )",
                (entity_id, older_than, entity_id, older_than, min_interval),
            )
            deleted = cursor.rowcount
            await cursor.close()
            await db.commit()
        return max(0, deleted)

    async def async_reclaim(self) -> None:
        """Give freed pages back to the filesystem, if the file supports it."""
        db = self._require_db()
        async with self._lock:
            try:
                await db.execute("PRAGMA incremental_vacuum")
                await db.commit()
            except aiosqlite.Error as err:  # pragma: no cover - best effort only
                _LOGGER.debug("incremental_vacuum skipped: %s", err)

    async def async_tracked_entities(self) -> list[str]:
        """Every entity_id that has at least one point stored."""
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "SELECT DISTINCT entity_id FROM points ORDER BY entity_id"
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [row["entity_id"] for row in rows]

    async def async_stats(self) -> dict[str, Any]:
        """Row counts and the covered time span, per entity and in total.

        The card uses this to tell "nothing recorded that day" apart from
        "nothing recorded at all", and to clamp its date picker.
        """
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "SELECT entity_id, COUNT(*) AS points,"
                "       MIN(ts) AS first_ts, MAX(ts) AS last_ts"
                "  FROM points GROUP BY entity_id ORDER BY entity_id"
            )
            rows = await cursor.fetchall()
            await cursor.close()

        entities = [
            {
                "entity_id": row["entity_id"],
                "points": row["points"],
                "first_ts": row["first_ts"],
                "last_ts": row["last_ts"],
            }
            for row in rows
        ]
        loop = asyncio.get_running_loop()
        return {
            "entities": entities,
            "points": sum(entry["points"] for entry in entities),
            # A stat() is cheap but it is still disk I/O, so keep it off the loop.
            "db_bytes": await loop.run_in_executor(None, self._file_size),
        }

    def _file_size(self) -> int:
        """Size of the database file in bytes, 0 while it does not exist yet."""
        try:
            return os.path.getsize(self._path)
        except OSError:
            return 0
