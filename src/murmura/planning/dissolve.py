"""Return "crumbling like after a snap".

The formation falls apart drone by drone: each drone leaves on its turn,
flies straight to its point above its landing spot and lands at once, without
waiting for the others, until the last one is down.

Drones are planned one at a time in the order they leave. A drone gets the
earliest departure (not before its turn) at which, during its whole flight,
it keeps the minimum distance to every drone planned before it and to every
drone still waiting in the formation, and touches down at least
``spindown`` seconds apart from its neighbours on the pad. Planned drones are
never changed afterwards, so a finished plan is safe by construction; if
some drone finds no such departure the planner gives up and reports it.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass

import numpy as np

from .transition import PROFILES, profile_progress

__all__ = ("DISSOLVE_ORDERS", "DissolvePlan", "plan_dissolve")

DISSOLVE_ORDERS = ("random", "top", "bottom", "outside", "front")


@dataclass
class DissolvePlan:
    start: np.ndarray  # (n, 3) points the drones leave from
    above: np.ndarray  # (n, 3) points above the landing spots
    ground: np.ndarray  # (n, 3) landing spots
    departures: np.ndarray  # (n,)
    flight: np.ndarray  # (n,) duration of the flight to ``above``
    descent: np.ndarray  # (n,) duration of the descent
    complete: bool  # every drone found a safe departure
    failure: str = ""
    track: tuple[np.ndarray, np.ndarray] | None = None  # motion before leaving

    @property
    def touchdowns(self) -> np.ndarray:
        return self.departures + self.flight + self.descent

    @property
    def total_duration(self) -> float:
        return float(np.max(self.touchdowns, initial=0.0))

    def waiting(self, idx: np.ndarray, times: np.ndarray) -> np.ndarray:
        """Where drones ``idx`` are before they leave: following ``track``
        (clamped to its ends) or at ``start``; shape ``(len(idx), len(times), 3)``."""
        return _waiting(self.track, self.start, np.asarray(idx), np.asarray(times, dtype=float))

    def positions(self, times: np.ndarray, idx: np.ndarray | None = None) -> np.ndarray:
        """Positions at ``times``, shape ``(len(idx), len(times), 3)``."""
        idx = np.arange(len(self.start)) if idx is None else np.asarray(idx)
        times = np.asarray(times, dtype=float)
        moving = _positions(
            self.start[idx],
            self.above[idx],
            self.ground[idx],
            self.departures[idx],
            self.flight[idx],
            self.descent[idx],
            times,
        )
        if self.track is None:
            return moving
        before = times[None, :] < self.departures[idx][:, None]
        return np.where(before[..., None], self.waiting(idx, times), moving)


def _waiting(track, start, idx, times) -> np.ndarray:
    if track is None:
        return np.repeat(start[idx][:, None, :], len(times), axis=1)
    t_track, frames = track
    rel = np.clip(times, t_track[0], t_track[-1])
    k = np.clip(np.searchsorted(t_track, rel), 1, len(t_track) - 1)
    w = ((rel - t_track[k - 1]) / np.maximum(t_track[k] - t_track[k - 1], 1e-12))[None, :, None]
    lo = np.swapaxes(frames[k - 1][:, idx], 0, 1)
    hi = np.swapaxes(frames[k][:, idx], 0, 1)
    return lo * (1 - w) + hi * w


def _positions(a, b, g, dep, fly, down, t) -> np.ndarray:
    tf = (t[None, :] - dep[:, None]) / np.maximum(fly[:, None], 1e-9)
    td = (t[None, :] - dep[:, None] - fly[:, None]) / np.maximum(down[:, None], 1e-9)
    u = profile_progress(tf, "smooth")[..., None]
    w = profile_progress(td, "smooth")[..., None]
    flying = a[:, None, :] + (b - a)[:, None, :] * u
    landing = b[:, None, :] + (g - b)[:, None, :] * w
    return np.where((td > 0)[..., None], landing, flying)


def _partners(paths: list[np.ndarray], radius: float) -> list[np.ndarray]:
    """For every drone, the drones whose paths (ignoring time) come within
    about ``radius``; nobody else can ever get that close. A voxel hash, so
    it stays fast without SciPy."""
    cells: dict[tuple[int, int, int], set[int]] = {}
    for i, pts in enumerate(paths):
        for key in {tuple(c) for c in np.floor(pts / radius).astype(int).tolist()}:
            cells.setdefault(key, set()).add(i)
    found: list[set[int]] = [set() for _ in paths]
    offsets = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
    for (cx, cy, cz), owners in cells.items():
        around: set[int] = set()
        for dx, dy, dz in offsets:
            around |= cells.get((cx + dx, cy + dy, cz + dz), set())
        for i in owners:
            found[i] |= around
    return [np.array(sorted(f - {i}), dtype=int) for i, f in enumerate(found)]


def _polyline(points: list[np.ndarray], step: float) -> np.ndarray:
    out = [points[0][None]]
    for p0, p1 in zip(points[:-1], points[1:]):
        m = max(1, int(np.ceil(np.linalg.norm(p1 - p0) / step)))
        out.append(p0 + (p1 - p0) * (np.arange(1, m + 1) / m)[:, None])
    return np.vstack(out)


def plan_dissolve(
    start,
    above,
    ground,
    *,
    min_distance: float,
    flight_durations: np.ndarray | None = None,
    landing_velocity: float,
    max_acceleration_z: float,
    airborne_altitude: float = 0.0,
    spindown: float = 0.0,
    order: str = "random",
    interval: float = 0.15,
    seed: int = 7,
    dt: float = 0.2,
    max_wait: float = 90.0,
    time_limit: float = 60.0,
    first: np.ndarray | None = None,
    track: tuple[np.ndarray, np.ndarray] | None = None,
    duration_fn=None,
) -> DissolvePlan:
    """Plans the "crumbling" return: drone ``i`` leaves ``start[i]`` on its
    turn (``order``: ``random``, ``top``, ``bottom``, ``outside`` or
    ``front``; about ``interval`` seconds apart), flies straight to
    ``above[i]`` in ``flight_durations[i]`` seconds and descends to
    ``ground[i]`` at once.

    With ``track = (times, frames)`` the drones do not wait still: until it
    leaves, drone ``i`` is at ``frames[k, i]`` at ``times[k]`` (following an
    animated model; clamped to the ends of the track), and it leaves from
    wherever it is then. ``duration_fn(delta)`` then gives the flight time of
    every move ``delta``.

    Drones in the ``first`` mask (for example those already waiting above
    the pad, not in the formation) go before all the others, lowest first.

    Pairs count while both drones are ``airborne_altitude`` above their
    landing spots. A drone may wait up to ``max_wait`` seconds past its turn;
    if one cannot find a safe departure, or planning takes longer than
    ``time_limit`` seconds, ``complete`` is false.
    """
    a = np.asarray(start, dtype=float).reshape(-1, 3)
    b = np.asarray(above, dtype=float).reshape(-1, 3)
    g = np.asarray(ground, dtype=float).reshape(-1, 3)
    n = len(a)
    if order not in DISSOLVE_ORDERS:
        raise ValueError(f"unknown order {order!r}; use one of {DISSOLVE_ORDERS}")
    if track is not None:
        track = (np.asarray(track[0], dtype=float), np.asarray(track[1], dtype=float))
        if duration_fn is None:
            raise ValueError("a track needs duration_fn")
    if flight_durations is None:
        if duration_fn is None:
            raise ValueError("give flight_durations or duration_fn")
        flight_durations = duration_fn(b - a)
    rng = np.random.default_rng(seed)
    fly = np.ceil(np.asarray(flight_durations, dtype=float) / dt) * dt
    kv, ka = PROFILES["smooth"]
    height = np.maximum(b[:, 2] - g[:, 2], 0.0)
    down = np.maximum(kv * height / landing_velocity, np.sqrt(ka * height / max_acceleration_z))
    down = np.ceil(down / dt) * dt

    if order == "random":
        key = rng.uniform(size=n)
    elif order == "top":
        key = -a[:, 2]
    elif order == "bottom":
        key = a[:, 2]
    elif order == "outside":
        key = -np.linalg.norm(a - a.mean(axis=0), axis=1)
    else:  # front: the drones nearest to the way home leave first
        direction = (b - a).mean(axis=0)
        key = -(a @ (direction / max(np.linalg.norm(direction), 1e-9)))
    if first is not None:
        early = np.asarray(first, dtype=bool)
        key = np.where(early, a[:, 2] - 1e9, key)  # before everybody, lowest first
    rank = np.empty(n)
    rank[np.argsort(key, kind="stable")] = np.arange(n)
    turn = np.round(rank * interval / dt) * dt

    plan = DissolvePlan(a.copy(), b, g, turn.copy(), fly, down, True, track=track)
    if n < 2 or min_distance <= 0:
        return plan

    # everything a drone can sweep: its way while waiting and its flight
    step_path = 0.5 * min_distance
    paths = []
    for i in range(n):
        pts = [_polyline([a[i], b[i], g[i]], step_path)]
        if track is not None:
            moved = track[1][:, i]
            pts.append(moved)
            pts.append(_polyline([moved[-1], b[i]], step_path))
        paths.append(np.vstack(pts))
    partners = _partners(paths, min_distance)
    pad = [np.flatnonzero(np.hypot(*(g[:, :2] - g[i, :2]).T) < min_distance) for i in range(n)]
    # a little margin: the checks sample the motion every ``dt`` seconds
    target = min_distance + 0.05
    step = 0.25
    scheduled = np.zeros(n, dtype=bool)
    postponed = np.zeros(n, dtype=int)
    deadline = time.perf_counter() + time_limit
    waits_for: dict[int, set[int]] = {}
    queue = [(float(turn[k]), int(k)) for k in range(n)]
    heapq.heapify(queue)
    departures = plan.departures
    one = np.zeros(1)

    def leave(k: int, s: float):
        """Departure point, flight time and the path (from the departure) of
        drone ``k`` leaving at ``s``."""
        if track is None:
            point, flight_k = a[k], fly[k]
        else:
            point = _waiting(track, a, np.array([k]), np.array([s]))[0, 0]
            flight_k = float(np.ceil(duration_fn((b[k] - point)[None])[0] / dt) * dt)
        rel = np.arange(0.0, flight_k + down[k] + dt, dt)
        path = _positions(
            point[None],
            b[k : k + 1],
            g[k : k + 1],
            one,
            np.array([flight_k]),
            down[k : k + 1],
            rel,
        )[0]
        return point, flight_k, rel, path

    while queue:
        if time.perf_counter() > deadline:
            plan.complete, plan.failure = False, "time limit"
            break
        first_time, k = heapq.heappop(queue)
        mates = partners[k]
        done = mates[scheduled[mates]]
        waiting = mates[~scheduled[mates]]
        waiting = waiting[waiting != k]
        base = max(first_time, float(turn[k]))
        # drones still in the formation stay there: k should leave after
        # those it would pass (unless they are already waiting for k)
        if len(waiting) and postponed[k] < 40:
            _, _, rel, own_path = leave(k, base)
            own_air = own_path[:, 2] - g[k, 2] >= airborne_altitude
            others = plan.waiting(waiting, base + rel)
            d = np.linalg.norm(others - own_path[None], axis=2)
            close = np.any((d < min_distance) & own_air[None], axis=1)
            blockers = [int(j) for j in waiting[close] if k not in waits_for.get(int(j), ())]
            if blockers:
                postponed[k] += 1
                waits_for.setdefault(k, set()).update(blockers)
                turn[k] = max(turn[k], float(np.max(turn[blockers])) + interval)
                heapq.heappush(queue, (float(turn[k]), k))
                continue
        found = False
        touch_near = [departures[j] + plan.flight[j] + down[j] for j in pad[k] if scheduled[j]]
        # the turn first, then a little later or earlier, then further away
        offsets = [0.0]
        for m in range(1, int(max_wait / step) + 1):
            offsets.append(m * step)
            if base - m * step >= 0:
                offsets.append(-m * step)
        for offset in offsets:
            s = base + offset
            point, flight_k, rel, own_path = leave(k, s)
            touch = s + flight_k + down[k]
            if any(abs(touch - tj) < spindown - 1e-9 for tj in touch_near):
                continue
            ok = True
            if len(done):
                own_air = own_path[:, 2] - g[k, 2] >= airborne_altitude
                # k flying against the drones planned so far
                other = plan.positions(s + rel, done)
                both = own_air[None] & (other[..., 2] - g[done, 2][:, None] >= airborne_altitude)
                if np.any(both & (np.linalg.norm(other - own_path[None], axis=2) < target)):
                    ok = False
                if ok and s > 0:
                    # k still in the formation while they fly past it
                    t0 = np.arange(0.0, s, dt)
                    other = plan.positions(t0, done)
                    mine = plan.waiting(np.array([k]), t0)[0]
                    up = other[..., 2] - g[done, 2][:, None] >= airborne_altitude
                    if np.any(up & (np.linalg.norm(other - mine[None], axis=2) < target)):
                        ok = False
            if ok:
                found = True
                break
        if found:
            departures[k] = s
            plan.start[k] = point
            plan.flight[k] = flight_k
        else:
            departures[k] = base
        scheduled[k] = True
        if not found:
            plan.complete = False
            plan.failure = (
                f"drone {k}: no safe departure within {max_wait:g} s (postponed {postponed[k]}x)"
            )
            break
    return plan
