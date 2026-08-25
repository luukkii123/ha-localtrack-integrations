#!/usr/bin/env python3
"""Eigenstaendiger Prueflauf fuer Ausduennung, Speicher und Recorder-Import.

    python3 tests/smoke_test.py

Braucht nur `aiosqlite` (dieselbe Version wie im Manifest), **kein** Home
Assistant: die HA-Module, die `importer.py` importiert, werden hier durch
Attrappen ersetzt. Das ist Absicht und keine Bequemlichkeit — auf dem
Unraid-Server ist kein Home Assistant installiert, und die Logik, um die es
geht (welcher Punkt ueberlebt, welcher Tag uebersprungen wird), haengt an
keinem einzigen HA-Aufruf.

Was der Lauf deshalb ausdruecklich NICHT belegt: dass
`history.get_significant_states` in der laufenden HA-Version genau diese
Signatur hat. Das entscheidet erst der Live-Test.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "localtrack"
sys.path.insert(0, str(ROOT / "custom_components"))

# Ein leeres Paket `localtrack`, das nur auf den Ordner zeigt. Sonst wuerde
# `from localtrack import importer` erst das echte `__init__.py` ausfuehren —
# und das zieht den halben Home-Assistant-Kern samt `voluptuous` herein, den
# dieser Lauf gerade nicht braucht. Die Untermodule bleiben die echten Dateien.
_pkg = types.ModuleType("localtrack")
_pkg.__path__ = [str(COMPONENT)]
sys.modules["localtrack"] = _pkg

# ── Attrappen fuer Home Assistant ──────────────────────────────────────────
_ha = types.ModuleType("homeassistant")
_core = types.ModuleType("homeassistant.core")
_core.HomeAssistant = object
_util = types.ModuleType("homeassistant.util")
_dt = types.ModuleType("homeassistant.util.dt")
_dt.utcnow = lambda: datetime.now(timezone.utc)
_dt.as_local = lambda value: value
_util.dt = _dt
_ha.core = _core
_ha.util = _util
sys.modules.setdefault("homeassistant", _ha)
sys.modules.setdefault("homeassistant.core", _core)
sys.modules.setdefault("homeassistant.util", _util)
sys.modules.setdefault("homeassistant.util.dt", _dt)

from localtrack import importer  # noqa: E402
from localtrack.sampling import PointThinner, read_position  # noqa: E402
from localtrack.store import LocationStore  # noqa: E402

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
    else:
        FAILED.append(f"{name}{(' — ' + detail) if detail else ''}")


class FakeState:
    """Genug von `homeassistant.core.State`, um den Importer zu fuettern."""

    def __init__(self, when: datetime, **attributes) -> None:
        self.last_updated = when
        self.attributes = attributes


class FakeRuntime:
    def __init__(self, store, min_distance_m=20.0, min_interval_s=30.0) -> None:
        self.store = store
        self.min_distance_m = min_distance_m
        self.min_interval_s = min_interval_s


# ── read_position ──────────────────────────────────────────────────────────
def test_read_position() -> None:
    check(
        "read_position: vollstaendig",
        read_position({"latitude": 48.2, "longitude": 16.35, "gps_accuracy": 8})
        == (48.2, 16.35, 8.0),
    )
    check(
        "read_position: ohne Genauigkeit",
        read_position({"latitude": 48.2, "longitude": 16.35}) == (48.2, 16.35, None),
    )
    check(
        "read_position: Attributsupdate ohne Koordinaten",
        read_position({"last_time_reachable": "2026-08-25"}) is None,
    )
    check("read_position: nur Breite", read_position({"latitude": 48.2}) is None)
    check(
        "read_position: unbrauchbarer Wert",
        read_position({"latitude": "keine Zahl", "longitude": 16.35}) is None,
    )
    check(
        "read_position: ausserhalb des Wertebereichs",
        read_position({"latitude": 91.0, "longitude": 16.35}) is None,
    )
    check(
        "read_position: kaputte Genauigkeit faellt auf None",
        read_position({"latitude": 48.2, "longitude": 16.35, "gps_accuracy": "?"})
        == (48.2, 16.35, None),
    )


# ── PointThinner ───────────────────────────────────────────────────────────
def test_thinner() -> None:
    thinner = PointThinner(min_distance_m=20, min_interval_s=30)
    check("Thinner: erster Punkt kommt durch", thinner.accept("p", 1000.0, 48.2, 16.35))
    check(
        "Thinner: Zittern am selben Ort faellt raus",
        not thinner.accept("p", 1005.0, 48.20001, 16.35001),
    )
    check(
        "Thinner: nach der Mindestzeit kommt ein Herzschlag durch",
        thinner.accept("p", 1040.0, 48.20001, 16.35001),
    )
    far = PointThinner(min_distance_m=20, min_interval_s=3600)
    far.accept("p", 0.0, 48.2000, 16.3500)
    check(
        "Thinner: weit genug bewegt schlaegt die Zeitsperre",
        far.accept("p", 5.0, 48.2010, 16.3500),
    )
    check(
        "Thinner: getrennte Entitaeten stoeren sich nicht",
        far.accept("q", 5.0, 48.2010, 16.3500),
    )
    seeded = PointThinner(min_distance_m=20, min_interval_s=30)
    seeded.seed("p", 1000.0, 48.2, 16.35)
    check(
        "Thinner: seed liefert kein Urteil, wirkt aber als Bezugspunkt",
        not seeded.accept("p", 1005.0, 48.20001, 16.35001),
    )
    check("Thinner: last() gibt den Bezugspunkt", seeded.last("p")[0] == 1000.0)


# ── Speicher ───────────────────────────────────────────────────────────────
async def test_store() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LocationStore(str(pathlib.Path(tmp) / "t.db"))
        await store.async_open()
        rows = [("person.a", 100.0 + i, 48.2, 16.35, 5.0) for i in range(5)]
        rows.append(("person.b", 100.0, 48.0, 16.0, None))
        written = await store.insert_points(rows)
        check("Store: insert_points meldet die Zeilenzahl", written == 6)
        check(
            "Store: count_range zaehlt nur die eine Entitaet",
            await store.count_range("person.a", 0, 1e12) == 5,
        )
        check(
            "Store: count_range achtet auf die Grenzen",
            await store.count_range("person.a", 101.0, 103.0) == 3,
        )
        check("Store: leere Liste schreibt nichts", await store.insert_points([]) == 0)
        deleted = await store.delete_range("person.a", 101.0, 103.0)
        check("Store: delete_range meldet die Zeilenzahl", deleted == 3)
        check(
            "Store: delete_range laesst die andere Entitaet in Ruhe",
            await store.count_range("person.b", 0, 1e12) == 1,
        )
        check(
            "Store: nach dem Loeschen bleiben die Randpunkte",
            await store.count_range("person.a", 0, 1e12) == 2,
        )
        await store.async_close()


# ── Importer ───────────────────────────────────────────────────────────────
def _fabricate(day: datetime, count: int, *, jitter: bool) -> list[FakeState]:
    """Ein Tag Rohdaten: dicht getaktet, entweder stehend oder fahrend."""
    states = []
    for i in range(count):
        when = day + timedelta(seconds=i * 5)
        if jitter:
            lat, lon = 48.2 + (i % 3) * 0.000005, 16.35 + (i % 2) * 0.000005
        else:
            lat, lon = 48.2 + i * 0.0009, 16.35 + i * 0.0009
        states.append(
            FakeState(when, latitude=lat, longitude=lon, gps_accuracy=8)
        )
    return states


async def test_importer() -> None:
    day0 = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
    plan = {
        day0: _fabricate(day0 + timedelta(hours=9), 60, jitter=True),
        day0 + timedelta(days=1): _fabricate(
            day0 + timedelta(days=1, hours=9), 40, jitter=False
        ),
        day0 + timedelta(days=2): [
            # Reines Attributsupdate ohne Koordinaten — muss folgenlos bleiben.
            FakeState(day0 + timedelta(days=2, hours=9), last_time_reachable="x"),
        ],
    }

    calls: list[tuple[str, datetime, datetime]] = []

    async def fake_fetch(hass, entity_id, start, end):
        calls.append((entity_id, start, end))
        return [
            state
            for chunk_start, states in plan.items()
            for state in states
            if start <= state.last_updated < end
        ]

    original = importer._fetch_states
    importer._fetch_states = fake_fetch
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocationStore(str(pathlib.Path(tmp) / "t.db"))
            await store.async_open()
            runtime = FakeRuntime(store)
            start = day0
            end = day0 + timedelta(days=3)

            # 1. Trockenlauf schreibt nichts.
            dry = await importer.async_import_entity(
                None, runtime, "person.a", start, end, dry_run=True
            )
            check("Import: Trockenlauf meldet gelesene Punkte", dry["scanned"] == 100)
            check("Import: Trockenlauf meldet, was ankaeme", dry["stored"] > 0)
            check(
                "Import: Trockenlauf laesst die Datenbank leer",
                await store.count_range("person.a", 0, 1e12) == 0,
            )

            # 2. Echter Lauf. Zaehler zuruecksetzen, sonst zaehlt die Pruefung
            # unten die Abfragen des Trockenlaufs mit.
            calls.clear()
            first = await importer.async_import_entity(
                None, runtime, "person.a", start, end
            )
            stored_rows = await store.count_range("person.a", 0, 1e12)
            check(
                "Import: schreibt genau, was er meldet",
                stored_rows == first["stored"],
                f"{stored_rows} in der Datenbank, {first['stored']} gemeldet",
            )
            check(
                "Import: Trockenlauf und echter Lauf kommen aufs Gleiche",
                dry["stored"] == first["stored"],
            )
            check(
                "Import: stehender Tag wird ausgeduennt",
                first["thinned_out"] > 0,
                f"gelesen {first['scanned']}, gespeichert {first['stored']}",
            )
            check(
                "Import: fahrender Tag behaelt jeden Punkt",
                first["stored"] >= 40,
                f"nur {first['stored']}",
            )
            check(
                "Import: Tag ohne Koordinaten steht unter days_without_data",
                "2026-08-22" in first["days_without_data"],
                str(first["days_without_data"]),
            )
            check(
                "Import: zwei Tage geschrieben",
                first["days_written"] == ["2026-08-20", "2026-08-21"],
                str(first["days_written"]),
            )
            check(
                "Import: tageweise gefragt, nicht am Stueck",
                len(calls) == 3,
                f"{len(calls)} Abfragen",
            )
            check(
                "Import: jedes Fenster ist genau ein Tag",
                all(
                    (window_end - window_start) == timedelta(days=1)
                    for _, window_start, window_end in calls
                ),
                str([(str(a), str(b)) for _, a, b in calls]),
            )
            check(
                "Import: Fenster stossen aneinander, ohne sich zu ueberlappen",
                all(
                    calls[i][2] == calls[i + 1][1] for i in range(len(calls) - 1)
                ),
            )

            # 3. Zweiter Lauf darf nichts verdoppeln.
            second = await importer.async_import_entity(
                None, runtime, "person.a", start, end
            )
            check("Import: zweiter Lauf schreibt nichts", second["stored"] == 0)
            check(
                "Import: zweiter Lauf ueberspringt die vollen Tage",
                second["days_skipped"] == ["2026-08-20", "2026-08-21"],
                str(second["days_skipped"]),
            )
            check(
                "Import: Zeilenzahl bleibt unveraendert",
                await store.count_range("person.a", 0, 1e12) == stored_rows,
            )

            # 4. overwrite=True ersetzt, statt zu verdoppeln.
            third = await importer.async_import_entity(
                None, runtime, "person.a", start, end, overwrite=True
            )
            check(
                "Import: overwrite schreibt wieder",
                third["stored"] == first["stored"],
                f"{third['stored']} statt {first['stored']}",
            )
            check(
                "Import: overwrite verdoppelt nicht",
                await store.count_range("person.a", 0, 1e12) == stored_rows,
            )

            # 5. Fremde Entitaet bleibt unberuehrt.
            check(
                "Import: schreibt nur die angefragte Entitaet",
                await store.count_range("person.b", 0, 1e12) == 0,
            )
            await store.async_close()
    finally:
        importer._fetch_states = original


async def test_import_summary() -> None:
    """async_import fasst mehrere Entitaeten zusammen."""

    async def fake_fetch(hass, entity_id, start, end):
        return [FakeState(start + timedelta(minutes=1), latitude=48.2, longitude=16.35)]

    original = importer._fetch_states
    importer._fetch_states = fake_fetch
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocationStore(str(pathlib.Path(tmp) / "t.db"))
            await store.async_open()
            runtime = FakeRuntime(store)
            summary = await importer.async_import(
                None, runtime, ["person.a", "person.b"], days=2
            )
            check("Zusammenfassung: beide Entitaeten dabei", len(summary["entities"]) == 2)
            check(
                "Zusammenfassung: Summen stimmen",
                summary["stored"]
                == sum(item["stored"] for item in summary["entities"]),
            )
            check(
                "Zusammenfassung: getrennt gespeichert",
                await store.count_range("person.a", 0, 1e12) > 0
                and await store.count_range("person.b", 0, 1e12) > 0,
            )
            await store.async_close()
    finally:
        importer._fetch_states = original


async def main() -> int:
    test_read_position()
    test_thinner()
    await test_store()
    await test_importer()
    await test_import_summary()

    print(f"{PASSED} Pruefungen bestanden, {len(FAILED)} gescheitert")
    for line in FAILED:
        print("  FEHLGESCHLAGEN:", line)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
