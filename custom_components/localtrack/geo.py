"""Geometry helpers: distance on the sphere, and track simplification.

Kept free of Home Assistant imports so it can be reasoned about (and unit
tested) on its own. `simplify_to_max` is CPU bound and is called from an
executor, never directly from the event loop.
"""

from __future__ import annotations

from math import asin, cos, hypot, radians, sin, sqrt
from typing import Any

EARTH_RADIUS_M = 6371008.8

# Above this many rows the Douglas-Peucker pass is preceded by a stride thin-out.
# Douglas-Peucker degrades to O(n²) on pathological input; a hard bound keeps a
# careless `start`/`end` (a whole year in one query) from pinning a CPU core.
_HARD_CAP = 50_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = radians(lon2 - lon1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(min(1.0, a)))


def _project(points: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    """Local equirectangular projection to metres around the track's centre.

    Good to a fraction of a percent over the span of one day's travel, which is
    far below GPS accuracy — and it turns every distance in the simplification
    into plain arithmetic.
    """
    lat0 = sum(point["lat"] for point in points) / len(points)
    scale_x = cos(radians(lat0)) * EARTH_RADIUS_M
    xs = [radians(point["lon"]) * scale_x for point in points]
    ys = [radians(point["lat"]) * EARTH_RADIUS_M for point in points]
    return xs, ys


def _segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance from point p to the segment a-b, all in projected metres."""
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rdp_keep(xs: list[float], ys: list[float], epsilon: float) -> list[bool]:
    """Douglas-Peucker as an explicit stack — recursion would blow the limit."""
    count = len(xs)
    keep = [False] * count
    keep[0] = True
    keep[count - 1] = True
    stack: list[tuple[int, int]] = [(0, count - 1)]

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        ax, ay = xs[first], ys[first]
        bx, by = xs[last], ys[last]
        worst = -1.0
        worst_index = -1
        for index in range(first + 1, last):
            distance = _segment_distance(xs[index], ys[index], ax, ay, bx, by)
            if distance > worst:
                worst = distance
                worst_index = index
        if worst > epsilon and worst_index > 0:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))

    return keep


def _stride_thin(points: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Blunt every-Nth reduction. Only a guard rail, never the final answer."""
    if len(points) <= limit:
        return points
    step = len(points) / limit
    thinned = [points[int(index * step)] for index in range(limit)]
    if thinned[-1] is not points[-1]:
        thinned[-1] = points[-1]
    return thinned


def simplify_to_max(
    points: list[dict[str, Any]], max_points: int
) -> list[dict[str, Any]]:
    """Reduce a track to at most `max_points` points, keeping its shape.

    Douglas-Peucker rather than "every Nth point": a straight motorway stretch
    costs two points, a roundabout keeps its corners. First and last point are
    always kept, so the day's start and end never move.
    """
    limit = max(2, int(max_points))
    if len(points) <= limit:
        return points

    working = _stride_thin(points, _HARD_CAP)
    if len(working) <= limit:
        return working

    xs, ys = _project(working)

    # Exponential search for a tolerance that is coarse enough …
    epsilon = 5.0
    keep = _rdp_keep(xs, ys, epsilon)
    too_fine = 0.0
    attempts = 0
    while sum(keep) > limit and attempts < 40:
        too_fine = epsilon
        epsilon *= 2.0
        keep = _rdp_keep(xs, ys, epsilon)
        attempts += 1

    # … then a few bisections to spend the budget instead of undershooting it.
    best = keep
    coarse_enough = epsilon
    for _ in range(10):
        middle = (too_fine + coarse_enough) / 2.0
        if middle <= too_fine or middle >= coarse_enough:
            break
        candidate = _rdp_keep(xs, ys, middle)
        if sum(candidate) > limit:
            too_fine = middle
        else:
            best = candidate
            coarse_enough = middle

    result = [point for point, keeper in zip(working, best) if keeper]
    # Belt and braces: a track that refuses to simplify still has to fit.
    return _stride_thin(result, limit)
