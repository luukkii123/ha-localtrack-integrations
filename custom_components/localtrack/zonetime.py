"""Wie lange war eine Entitaet in einem Umkreis — Tag fuer Tag.

Frei von Home-Assistant-Importen, wie `geo.py` und `sampling.py`, und aus
demselben Grund: was ohne Home Assistant pruefbar ist, wird auch geprueft.
Der Aufrufer schiebt `compute_zone_time` in einen Ausfuehrer — bei 90.000
Punkten ist das CPU-gebunden und hat im Ereignisschleifen-Faden nichts
verloren, genau wie `simplify_to_max`.

Warum ueberhaupt gerechnet und nicht die Zustandshistorie der `person`-Entitaet
gezaehlt wird: die flackert. An einer echten Installation gemessen wechselte
sie zwischen `SCN` und `not_home` innerhalb von drei Sekunden, weil mehrere
Zonen einander ueberlappen, Home Assistant die kleinste zeigt und GPS-Zittern
den Punkt ueber die Grenze schiebt. Aus solchen Zustaenden eine Verweildauer
zu bilden ergaebe Unsinn.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Any

from .geo import haversine_m


def _visits(
    points: list[dict[str, Any]],
    latitude: float,
    longitude: float,
    radius: float,
    max_gap_s: float,
) -> list[tuple[float, float]]:
    """Zusammenhaengende Aufenthalte als (start, ende) in Epoch-Sekunden.

    Zwei Regeln, beide dieselbe Haltung — lieber zu wenig als erfunden:

    * **Der Uebertritt zaehlt halb.** Liegt ein Punkt drin und der naechste
      draussen, lag die Grenze irgendwo dazwischen; gutgeschrieben wird die
      halbe Luecke. Bei 30-Sekunden-Takt sind das +/-15 s je Uebertritt.
    * **Eine Luecke groesser als `max_gap_s` trennt den Aufenthalt**, auch
      wenn beide Punkte drin liegen. Wer der Luecke nicht traut, darf auch
      keine durchgehende Anwesenheit behaupten. Jede Seite bekommt
      `max_gap_s / 2`, nach derselben Halbierungsregel.
    """
    inside = [
        haversine_m(p["lat"], p["lon"], latitude, longitude) <= radius
        for p in points
    ]
    result: list[tuple[float, float]] = []
    start: float | None = None
    last = len(points) - 1

    for i, point in enumerate(points):
        ts = point["ts"]

        if inside[i] and start is None:
            start = ts
            if i > 0:
                # Halbe Luecke zum Vorgaenger davor: der Eintritt lag dazwischen.
                start -= min(ts - points[i - 1]["ts"], max_gap_s) / 2.0

        if not inside[i] or i == last:
            if start is not None and inside[i]:
                # Letzter Punkt der Reihe, und er liegt drin: hier endet es.
                result.append((start, ts))
                start = None
            elif start is not None:
                previous = points[i - 1]["ts"]
                # Halbe Luecke zum ersten Punkt draussen.
                result.append(
                    (start, previous + min(ts - previous, max_gap_s) / 2.0)
                )
                start = None
            continue

        if inside[i + 1] and (points[i + 1]["ts"] - ts) > max_gap_s:
            result.append((start, ts + max_gap_s / 2.0))
            start = points[i + 1]["ts"] - max_gap_s / 2.0

    return result


def _local_day(ts: float, tz: tzinfo) -> str:
    """Kalendertag in der Zeitzone des Hosts, nicht des Browsers."""
    return datetime.fromtimestamp(ts, tz).date().isoformat()


def _midnight_after(ts: float, tz: tzinfo) -> float:
    """Naechste lokale Mitternacht nach `ts`."""
    local = datetime.fromtimestamp(ts, tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (day_start + timedelta(days=1)).timestamp()


def compute_zone_time(
    points: list[dict[str, Any]],
    latitude: float,
    longitude: float,
    radius: float,
    tz: tzinfo,
    min_visit_s: float,
    max_gap_s: float,
) -> dict[str, Any]:
    """Tagesweise Netto- und Bruttodauer im Umkreis eines Punktes.

    `net_s` summiert die tatsaechlichen Anteile, `gross_s` spannt vom ersten
    Ankommen bis zum letzten Gehen desselben Tages. Die Differenz macht Pausen
    und Datenloecher sichtbar, statt sie zu verstecken — deshalb stehen beide
    Zahlen nebeneinander und nicht nur eine.

    Nur Tage mit Anwesenheit stehen in `days`; die Karte fuellt den Monat auf.
    """
    visits = _visits(points, latitude, longitude, radius, max_gap_s)

    # Die Mindestdauer greift am GANZEN Besuch, vor jeder Tagesaufteilung.
    # Anders herum fiele ein langer Besuch an dem Tag heraus, an dem er nur ein
    # paar Minuten liegt — eine Nachtschicht verloere ihren ersten Abend.
    visits = [(a, b) for a, b in visits if (b - a) >= min_visit_s]

    per_day: dict[str, dict[str, Any]] = {}
    for start, end in visits:
        cursor = start
        while cursor < end:
            boundary = min(_midnight_after(cursor, tz), end)
            key = _local_day(cursor, tz)
            day = per_day.setdefault(
                key,
                {
                    "date": key,
                    "net_s": 0.0,
                    "visits": 0,
                    "first_ts": cursor,
                    "last_ts": boundary,
                },
            )
            day["net_s"] += boundary - cursor
            day["visits"] += 1
            day["first_ts"] = min(day["first_ts"], cursor)
            day["last_ts"] = max(day["last_ts"], boundary)
            cursor = boundary

    days = []
    for key in sorted(per_day):
        day = per_day[key]
        day["gross_s"] = day["last_ts"] - day["first_ts"]
        days.append(day)

    return {
        "days": days,
        "total_net_s": sum(d["net_s"] for d in days),
        "total_gross_s": sum(d["gross_s"] for d in days),
        "total_visits": sum(d["visits"] for d in days),
        "days_present": len(days),
    }
