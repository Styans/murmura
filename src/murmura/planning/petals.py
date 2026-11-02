"""Return "like falling petals".

The drones leave the formation one after another, in a chosen order, and
drift home swaying sideways like sakura petals in the wind.

The effect is laid over a return plan that is already known to be safe
(straight moves with start times, see :class:`MovePlan`). That plan is first
slowed down uniformly, which keeps it safe and leaves time to spare. Then,
drone by drone in the petal order, the departure is moved to the drone's turn
in the cascade while its arrival time stays as planned (so the order in
which drones reach the pad, which is what keeps them apart there, does not
change), and a sideways sway is added. A change is kept only if the drone
still keeps the minimum distance to every other drone; otherwise a smaller
change is tried. Every accepted change keeps the plan safe, so the result is
as safe as the plan it started from.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .transition import MovePlan, profile_progress

__all__ = ("PETAL_ORDERS", "PetalPlan", "petalize")

PETAL_ORDERS = ("top", "bottom", "outside", "front", "random")


@dataclass
class PetalPlan:
    """Single straight moves ``start -> end`` with a sideways sway.

    Drone ``i`` waits at ``start[i]`` until ``departures[i]``, flies for
    ``durations[i]`` seconds and then stays at ``end[i]``; times are relative
    to the beginning of the plan.
    """

    start: np.ndarray  # (n, 3)
    end: np.ndarray  # (n, 3)
    departures: np.ndarray  # (n,)
    durations: np.ndarray  # (n,)
    amplitude: np.ndarray  # (n,)
    cycles: np.ndarray  # (n,)
    phase: np.ndarray  # (n,)
    delayed: int = 0  # drones whose departure moved later
    swaying: int = 0  # drones that sway

    @property
    def total_duration(self) -> float:
        return float(np.max(self.departures + self.durations, initial=0.0))

    def positions(self, times: np.ndarray, idx: np.ndarray | None = None) -> np.ndarray:
        """Positions at ``times``, shape ``(len(idx), len(times), 3)``."""
        idx = np.arange(len(self.start)) if idx is None else np.asarray(idx)
        return _positions(
            self.start[idx],
            self.end[idx],
            self.departures[idx],
            self.durations[idx],
            self.amplitude[idx],
            self.cycles[idx],
            self.phase[idx],
            np.asarray(times, dtype=float),
        )


def _perpendicular(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Horizontal unit vectors perpendicular to the moves ``a -> b``."""
    d = b - a
    perp = np.column_stack([-d[:, 1], d[:, 0], np.zeros(len(d))])
    norm = np.linalg.norm(perp, axis=1)
    perp[norm < 1e-6] = (1.0, 0.0, 0.0)
    norm[norm < 1e-6] = 1.0
    return perp / norm[:, None]


def _positions(a, b, dep, dur, amp, cycles, phase, t) -> np.ndarray:
    tau = (t[None, :] - dep[:, None]) / np.maximum(dur[:, None], 1e-9)
    u = profile_progress(tau, "smooth")
    w = np.clip(tau, 0.0, 1.0)
    sway = (
        amp[:, None]
        * np.sin(np.pi * w)
        * np.sin(2.0 * np.pi * cycles[:, None] * w + phase[:, None])
    )
    return (
        a[:, None, :]
        + (b - a)[:, None, :] * u[..., None]
        + sway[..., None] * _perpendicular(a, b)[:, None, :]
    )


def _sway_durations(a, b, amp, cycles, phase, base, limits) -> np.ndarray:
    """Shortest durations (at least ``base``) that keep the swaying moves
    within the speed and acceleration limits."""
    vxy, vup, vdown, axy, az = limits
    tau = np.linspace(0.0, 1.0, 241)
    pos = _positions(a, b, np.zeros(len(a)), np.ones(len(a)), amp, cycles, phase, tau)
    h = tau[1] - tau[0]
    vel = np.gradient(pos, h, axis=1)
    acc = np.gradient(vel, h, axis=1)
    need = np.max(np.linalg.norm(vel[..., :2], axis=2), axis=1) / vxy
    need = np.maximum(need, np.max(np.maximum(vel[..., 2], 0), axis=1) / vup)
    need = np.maximum(need, np.max(np.maximum(-vel[..., 2], 0), axis=1) / vdown)
    need = np.maximum(need, np.sqrt(np.max(np.linalg.norm(acc[..., :2], axis=2), axis=1) / axy))
    need = np.maximum(need, np.sqrt(np.max(np.abs(acc[..., 2]), axis=1) / az))
    return np.maximum(base, need)


def _tube_partners(a: np.ndarray, b: np.ndarray, radius: float) -> list[np.ndarray]:
    """For every drone, the drones whose straight paths come within about
    ``radius`` of its own (a voxel hash, fast without SciPy)."""
    cells: dict[tuple[int, int, int], set[int]] = {}
    for i in range(len(a)):
        m = int(np.ceil(np.linalg.norm(b[i] - a[i]) / (0.5 * radius))) + 1
        pts = a[i] + (b[i] - a[i]) * np.linspace(0.0, 1.0, m)[:, None]
        for key in {tuple(c) for c in np.floor(pts / radius).astype(int).tolist()}:
            cells.setdefault(key, set()).add(i)
    found: list[set[int]] = [set() for _ in range(len(a))]
    offsets = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
    for (cx, cy, cz), owners in cells.items():
        around: set[int] = set()
        for dx, dy, dz in offsets:
            around |= cells.get((cx + dx, cy + dy, cz + dz), set())
        for i in owners:
            found[i] |= around
    return [np.array(sorted(f - {i}), dtype=int) for i, f in enumerate(found)]


def petalize(
    plan: MovePlan,
    *,
    min_distance: float,
    ground_z: np.ndarray,
    airborne_altitude: float,
    max_velocity_xy: float,
    max_velocity_z_up: float,
    max_velocity_z_down: float,
    max_acceleration: float,
    max_acceleration_z: float | None = None,
    order: str = "top",
    interval: float = 0.15,
    sway: float = 1.5,
    sway_margin: float = 0.0,
    seed: int = 7,
    dt: float = 0.2,
) -> PetalPlan | None:
    """Turns a safe single-leg return plan into a "falling petals" one.

    Drones leave in ``order`` (``top``: highest first, ``bottom``,
    ``outside``: furthest from the centre first, ``front``: those furthest
    along the way home first, ``random``) about ``interval`` seconds apart and
    sway sideways by up to ``sway`` metres, as far as the minimum distance
    allows (pairs count while both drones are ``airborne_altitude`` above
    ``ground_z``). Swaying moves keep ``sway_margin`` more, for the error
    of fitting them with curves.

    Returns ``None`` if the plan has more than one leg.
    """
    if plan.waypoints.shape[1] != 2:
        return None
    if order not in PETAL_ORDERS:
        raise ValueError(f"unknown petal order {order!r}; use one of {PETAL_ORDERS}")
    a = plan.waypoints[:, 0].copy()
    b = plan.waypoints[:, 1].copy()
    n = len(a)
    rng = np.random.default_rng(seed)
    moving = np.linalg.norm(b - a, axis=1) > 1e-6
    count = int(np.sum(moving))

    # slow the safe plan down so that the cascade fits in: still safe
    stretch = 1.0 + count * interval / max(plan.total_duration, 1e-9)
    base_dep = plan.starts[:, 0] * stretch
    base_dur = plan.durations[:, 0] * stretch
    arrival = base_dep + base_dur

    az = max_acceleration_z or max_acceleration
    limits = (max_velocity_xy, max_velocity_z_up, max_velocity_z_down, max_acceleration, az)
    cycles = rng.uniform(1.0, 2.0, n)
    phase = rng.uniform(0.0, 2.0 * np.pi, n)
    wanted_amp = np.where(moving, sway * rng.uniform(0.6, 1.0, n), 0.0)
    wanted_amp = np.minimum(wanted_amp, 0.2 * np.linalg.norm(b - a, axis=1))
    zeros = np.zeros(n)
    fastest = _sway_durations(a, b, zeros, cycles, phase, zeros, limits)
    fastest_swaying = _sway_durations(a, b, wanted_amp, cycles, phase, zeros, limits)

    if order == "top":
        key = -a[:, 2]
    elif order == "bottom":
        key = a[:, 2]
    elif order == "outside":
        key = -np.linalg.norm(a - a.mean(axis=0), axis=1)
    elif order == "front":
        direction = (b - a).mean(axis=0)
        key = -(a @ (direction / max(np.linalg.norm(direction), 1e-9)))
    else:
        key = rng.uniform(size=n)
    key = np.where(moving, key, np.inf)  # drones already home do not take part
    rank = np.empty(n)
    rank[np.argsort(key, kind="stable")] = np.arange(n)
    turn = (rank + rng.uniform(0.0, 0.5, n)) * interval

    petal = PetalPlan(a, b, base_dep.copy(), base_dur.copy(), np.zeros(n), cycles, phase)
    if n < 2:
        return petal

    partners = _tube_partners(a, b, min_distance + 2.0 * sway)
    all_times = np.arange(0.0, float(np.max(arrival)) + 1.0 + dt, dt)
    target = min_distance - 1e-6

    def clear(k: int, dep: float, dur: float, amp: float) -> bool:
        """Whether drone ``k`` flying the changed move keeps the distance to
        every partner (outside the changed time window it is where it already
        was). Where either drone sways, ``sway_margin`` more is needed, as
        swaying paths are later fitted with curves."""
        mates = partners[k]
        if len(mates) == 0:
            return True
        lo = int(np.floor(min(dep, petal.departures[k]) / dt))
        times = all_times[lo : int(np.ceil(arrival[k] / dt)) + 1]
        own = _positions(
            a[k : k + 1],
            b[k : k + 1],
            np.array([dep]),
            np.array([dur]),
            np.array([amp]),
            cycles[k : k + 1],
            phase[k : k + 1],
            times,
        )[0]
        other = petal.positions(times, mates)
        both = (own[:, 2] - ground_z[k] >= airborne_altitude)[None] & (
            other[..., 2] - ground_z[mates, None] >= airborne_altitude
        )
        if not np.any(both):
            return True
        swaying = (amp > 0) & (times >= dep) & (times <= dep + dur)
        mates_swaying = (
            (petal.amplitude[mates, None] > 0)
            & (times[None, :] >= petal.departures[mates, None])
            & (times[None, :] <= (petal.departures + petal.durations)[mates, None])
        )
        need = target + sway_margin * (swaying[None, :] | mates_swaying)
        d = np.linalg.norm(other - own[None], axis=2)
        return bool(np.all(~both | (d >= need)))

    for k in np.argsort(rank, kind="stable"):
        if not moving[k]:
            continue
        for fraction in (1.0, 0.75, 0.5, 0.25, 0.0):
            # leave at the turn in the cascade, arrive when the safe plan does
            dep = base_dep[k] + (turn[k] - base_dep[k]) * fraction
            found = False
            for amp, quickest in ((wanted_amp[k], fastest_swaying[k]), (0.0, fastest[k])):
                dep_k = min(dep, arrival[k] - quickest)
                if fraction == 0.0 and amp == 0.0:
                    found = True  # the slowed-down original move, safe
                    break
                if dep_k < 0 or arrival[k] - dep_k < quickest - 1e-9:
                    continue
                if clear(k, dep_k, arrival[k] - dep_k, amp):
                    petal.departures[k] = dep_k
                    petal.durations[k] = arrival[k] - dep_k
                    petal.amplitude[k] = amp
                    found = True
                    break
            if found:
                break
    petal.delayed = int(np.sum(np.abs(petal.departures - base_dep) > 1e-6))
    petal.swaying = int(np.sum(petal.amplitude > 0))
    return petal
