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
from localtrack.zonetime import compute_zone_time  # noqa: E402

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


# ── Verweildauer ───────────────────────────────────────────────────────────
# Zone fuer alle Faelle: Mittelpunkt (48.2, 16.35), Radius 100 m.
ZL, ZO, ZR = 48.2, 16.35, 100.0
DRIN = (48.2, 16.35)          # 0 m vom Mittelpunkt
DRAUSSEN = (48.21, 16.35)     # rund 1110 m entfernt
TZ = timezone(timedelta(hours=2))   # Europe/Vienna im Sommer


def _pts(spec):
    """spec: Liste (ts, drin?) -> Punktliste in der Form des Speichers."""
    out = []
    for ts, inside in spec:
        lat, lon = DRIN if inside else DRAUSSEN
        out.append({"ts": float(ts), "lat": lat, "lon": lon})
    return out


def _tag(ymd, h=0, m=0):
    return datetime(*ymd, h, m, tzinfo=TZ).timestamp()


def test_zonetime() -> None:
    # 1. Einfacher Besuch: 08:00-09:00, Takt 30 s, alles drin.
    spec = [(_tag((2026, 9, 3), 8, 0) + i * 30, True) for i in range(121)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 300, 900)
    check("zonetime: ein Tag", len(r["days"]) == 1, str(r["days"]))
    check("zonetime: netto = 3600 s", abs(r["days"][0]["net_s"] - 3600) < 1,
          str(r["days"][0]))
    check("zonetime: brutto = netto ohne Pause",
          r["days"][0]["gross_s"] == r["days"][0]["net_s"], str(r["days"][0]))
    check("zonetime: ein Besuch", r["days"][0]["visits"] == 1)
    check("zonetime: Datum lokal", r["days"][0]["date"] == "2026-09-03",
          r["days"][0]["date"])

    # 2. Durchfahrt unter der Mindestdauer faellt ganz weg.
    base = _tag((2026, 9, 4), 12, 0)
    spec = [(base - 30, False), (base, True), (base + 30, True), (base + 60, False)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 300, 900)
    check("zonetime: Durchfahrt faellt weg", r["days"] == [], str(r["days"]))

    # 3. Deckelung: zwei Punkte drin, zwei Stunden auseinander.
    base = _tag((2026, 9, 5), 9, 0)
    spec = [(base, True), (base + 7200, True)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 0, 900)
    check("zonetime: Luecke gedeckelt auf max_gap_s",
          abs(r["total_net_s"] - 900) < 1, f"{r['total_net_s']} statt 900")
    check("zonetime: Luecke teilt den Besuch", r["days"][0]["visits"] == 2,
          str(r["days"][0]))
    check("zonetime: brutto ueberspannt die Luecke",
          abs(r["days"][0]["gross_s"] - 7200) < 1, str(r["days"][0]))

    # 4. Uebertritt zaehlt halb: drin 30 s, je 30 s Nachbarluecke -> 60 s.
    base = _tag((2026, 9, 6), 9, 0)
    spec = [(base, False), (base + 30, True), (base + 60, True), (base + 90, False)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 0, 900)
    check("zonetime: Uebertritt haelftig", abs(r["total_net_s"] - 60) < 1,
          f"{r['total_net_s']} statt 60")

    # 5. Mitternacht: 23:00 bis 01:00, Takt 60 s.
    start = _tag((2026, 9, 7), 23, 0)
    spec = [(start + i * 60, True) for i in range(121)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 300, 900)
    check("zonetime: zwei Tage",
          [d["date"] for d in r["days"]] == ["2026-09-07", "2026-09-08"],
          str([d["date"] for d in r["days"]]))
    check("zonetime: Tag 1 bekommt 3600 s", abs(r["days"][0]["net_s"] - 3600) < 1,
          str(r["days"][0]))
    check("zonetime: Tag 2 bekommt 3600 s", abs(r["days"][1]["net_s"] - 3600) < 1,
          str(r["days"][1]))

    # 6. Mindestdauer greift am GANZEN Besuch: 23:58 bis 00:05 = 7 min.
    start = _tag((2026, 9, 9), 23, 58)
    spec = [(start + i * 30, True) for i in range(15)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 300, 900)
    check("zonetime: Besuch ueberlebt trotz kurzer Tagesanteile",
          [d["date"] for d in r["days"]] == ["2026-09-09", "2026-09-10"],
          str([d["date"] for d in r["days"]]))
    check("zonetime: Tag 1 haelt 120 s", abs(r["days"][0]["net_s"] - 120) < 1,
          str(r["days"][0]))

    # 7. brutto >= netto, immer: zwei Besuche am selben Tag mit Pause.
    base = _tag((2026, 9, 11), 8, 0)
    spec = ([(base + i * 30, True) for i in range(41)]
            + [(base + 3600, False)]
            + [(base + 7200 + i * 30, True) for i in range(41)])
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 300, 900)
    d = r["days"][0]
    check("zonetime: zwei Besuche", d["visits"] == 2, str(d))
    check("zonetime: brutto > netto bei Pause", d["gross_s"] > d["net_s"], str(d))

    # 8. Leerer Zeitraum.
    r = compute_zone_time([], ZL, ZO, ZR, TZ, 300, 900)
    check("zonetime: leere Eingabe", r["days"] == [] and r["total_net_s"] == 0)

    # 9. Zeitzone: 23:30 UTC gehoert bei +02:00 zum naechsten lokalen Tag.
    start = datetime(2026, 9, 12, 23, 30, tzinfo=timezone.utc).timestamp()
    spec = [(start + i * 60, True) for i in range(31)]
    r = compute_zone_time(_pts(spec), ZL, ZO, ZR, TZ, 300, 900)
    check("zonetime: Tagesgrenze ist HA-lokal",
          r["days"][0]["date"] == "2026-09-13", r["days"][0]["date"])

    # 10. brutto nie kleiner als netto - Invariante ueber alle Faelle oben.
    check("zonetime: Invariante brutto >= netto",
          all(d["gross_s"] >= d["net_s"] - 1e-6 for d in r["days"]))


async def main() -> int:
    test_read_position()
    test_thinner()
    test_zonetime()
    await test_store()
    await test_importer()
    await test_import_summary()

    print(f"{PASSED} Pruefungen bestanden, {len(FAILED)} gescheitert")
    for line in FAILED:
        print("  FEHLGESCHLAGEN:", line)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
