"""Transition planning between two formations."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .matching import as_points, match_points, synchronized_clearance

__all__ = (
    "PROFILES",
    "TransitionPlan",
    "min_transition_durations",
    "plan_transition",
    "profile_progress",
    "stagger_transition",
)

# (peak velocity factor, peak acceleration factor) for a move of length d in time T:
#   v_peak = kv * d / T,  a_peak = ka * d / T²
PROFILES: dict[str, tuple[float, float]] = {
    "smooth": (1.5, 6.0),
    "linear": (1.0, 0.0),
    "ease_in": (2.0, 2.0),
    "ease_out": (2.0, 2.0),
}


def profile_progress(tau: np.ndarray, profile: str = "smooth") -> np.ndarray:
    """Normalised progress along the path for normalised time ``tau ∈ [0, 1]``."""
    tau = np.clip(tau, 0.0, 1.0)
    if profile == "smooth":
        return tau * tau * (3.0 - 2.0 * tau)
    if profile == "linear":
        return tau
    if profile == "ease_in":
        return tau * tau
    if profile == "ease_out":
        return tau * (2.0 - tau)
    raise ValueError(f"unknown velocity profile: {profile!r}")


@dataclass
class TransitionPlan:
    start_times: list[float] = field(default_factory=list)
    """Start time of the drone travelling to the i-th target, relative to the
    start of the transition."""
    durations: list[float] = field(default_factory=list)
    """Travel time of the drone travelling to the i-th target."""
    mapping: list[int | None] | None = None
    """Index of the source point assigned to the i-th target."""
    clearance: float | None = None

    @property
    def total_duration(self) -> float:
        return max((s + d for s, d in zip(self.start_times, self.durations)), default=0.0)

    def to_json(self) -> dict:
        result: dict = {
            "start_times": [round(v, 6) for v in self.start_times],
            "durations": [round(v, 6) for v in self.durations],
            "version": 1,
        }
        if self.mapping is not None:
            result["mapping"] = self.mapping
        if self.clearance is not None:
            result["clearance"] = round(self.clearance, 3)
        return result


def min_transition_durations(
    delta: np.ndarray,
    *,
    max_velocity_xy: float,
    max_velocity_z: float,
    max_acceleration: float,
    max_velocity_z_up: float | None = None,
    max_acceleration_z: float | None = None,
    profile: str = "smooth",
) -> np.ndarray:
    """Shortest admissible travel time of each straight-line move."""
    if profile not in PROFILES:
        raise ValueError(f"unknown velocity profile: {profile!r}")
    if max_velocity_xy <= 0 or max_velocity_z <= 0 or max_acceleration <= 0:
        raise ValueError("velocity and acceleration limits must be positive")
    kv, ka = PROFILES[profile]
    delta = np.asarray(delta, dtype=float).reshape(-1, 3)
    dxy = np.hypot(delta[:, 0], delta[:, 1])
    dz = delta[:, 2]
    vz = np.where(dz > 0, max_velocity_z_up or max_velocity_z, max_velocity_z)
    t = np.maximum(kv * dxy / max_velocity_xy, kv * np.abs(dz) / vz)
    if ka > 0:
        az = max_acceleration_z or max_acceleration
        t = np.maximum(t, np.sqrt(ka * dxy / max_acceleration))
        t = np.maximum(t, np.sqrt(ka * np.abs(dz) / az))
    # Round up to whole milliseconds so that limits hold after serialisation
    return np.ceil(t * 1000.0 - 1e-6) / 1000.0


def _candidate_pairs(
    a: np.ndarray, b: np.ndarray, margin: float, chunk: int = 1024
) -> list[np.ndarray]:
    """For every drone, the drones whose swept path bounding boxes come within
    ``margin`` of each other."""
    lo = np.minimum(a, b) - margin / 2
    hi = np.maximum(a, b) + margin / 2
    n = len(a)
    result: list[np.ndarray] = []
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        overlap = np.all(
            (lo[s:e, None, :] <= hi[None, :, :]) & (hi[s:e, None, :] >= lo[None, :, :]), axis=2
        )
        for k, row in enumerate(overlap):
            row[s + k] = False
            result.append(np.flatnonzero(row))
    return result


def segment_distances(a1: np.ndarray, b1: np.ndarray, a2: np.ndarray, b2: np.ndarray) -> np.ndarray:
    """Closest distance between pairs of 3D segments ``a1-b1`` and ``a2-b2``
    (vectorised over the first axis)."""
    d1, d2, r = b1 - a1, b2 - a2, a1 - a2
    aa = np.einsum("ij,ij->i", d1, d1)
    ee = np.einsum("ij,ij->i", d2, d2)
    ff = np.einsum("ij,ij->i", d2, r)
    cc = np.einsum("ij,ij->i", d1, r)
    bb = np.einsum("ij,ij->i", d1, d2)
    eps = 1e-12
    safe_a = np.where(aa > eps, aa, 1.0)
    safe_e = np.where(ee > eps, ee, 1.0)
    denom = aa * ee - bb * bb
    s = np.where(
        denom > eps, np.clip((bb * ff - cc * ee) / np.where(denom > eps, denom, 1.0), 0, 1), 0.0
    )
    t = (bb * s + ff) / safe_e
    s = np.where(
        t < 0, np.clip(-cc / safe_a, 0, 1), np.where(t > 1, np.clip((bb - cc) / safe_a, 0, 1), s)
    )
    t = np.clip(t, 0, 1)
    # degenerate segments (stationary drones)
    s = np.where(aa <= eps, 0.0, s)
    t = np.where(ee <= eps, 0.0, np.where(aa <= eps, np.clip(ff / safe_e, 0, 1), t))
    s = np.where((ee <= eps) & (aa > eps), np.clip(-cc / safe_a, 0, 1), s)
    diff = (a1 + d1 * s[:, None]) - (a2 + d2 * t[:, None])
    return np.sqrt(np.einsum("ij,ij->i", diff, diff))


def _conflict_pairs(
    a: np.ndarray, b: np.ndarray, min_distance: float
) -> tuple[np.ndarray, np.ndarray]:
    """Pairs ``(i, j)``, ``i < j``, whose straight paths come closer than
    ``min_distance`` at some point, i.e. pairs that could collide for some
    choice of start delays."""
    neighbours = _candidate_pairs(a, b, min_distance)
    ii = (
        np.concatenate([np.full(len(nb), i) for i, nb in enumerate(neighbours)])
        if neighbours
        else np.zeros(0, int)
    )
    jj = np.concatenate(neighbours) if neighbours else np.zeros(0, int)
    keep = ii < jj
    ii, jj = ii[keep].astype(int), jj[keep].astype(int)
    if len(ii) == 0:
        return ii, jj
    close = segment_distances(a[ii], b[ii], a[jj], b[jj]) < min_distance
    return ii[close], jj[close]


def stagger_transition(
    start: np.ndarray,
    end: np.ndarray,
    durations: np.ndarray,
    min_distance: float,
    *,
    profile: str = "smooth",
    max_delay: float | None = None,
    step: float | None = None,
    max_iterations: int | None = None,
    time_limit: float = 4.0,
) -> np.ndarray:
    """Delays individual drones so that straight-line moves keep at least
    ``min_distance`` between every pair (best effort).

    Only pairs whose paths come within ``min_distance`` of each other can
    conflict. Planning runs in two stages:

    1. prioritised scheduling: drones are taken in a priority order and each
       gets the earliest delay (a multiple of ``step``) that keeps it clear
       of the drones scheduled before it. Several orders are tried (drones
       at the front of the swarm's motion first, longest paths first,
       shortest paths first) and the best schedule is kept;
    2. local repair: the closest remaining conflict is resolved by delaying
       one of its two drones if that reduces the total separation deficit.

    Returns:
        the start delay of every drone
    """
    a = as_points(start)
    b = as_points(end)
    dur = np.asarray(durations, dtype=float)
    n = len(a)
    delays = np.zeros(n)
    if n < 2 or min_distance <= 0:
        return delays

    if np.allclose(dur, dur[0]):
        clearance, _ = synchronized_clearance(a, b)
        if clearance >= min_distance:
            return delays

    deadline = time.perf_counter() + time_limit
    ii, jj = _conflict_pairs(a, b, min_distance)
    if len(ii) == 0:
        return delays

    window = float(np.max(dur))
    step = step or max(0.2, window / 10.0)
    max_delay = window * 2.0 if max_delay is None else max_delay
    dt = float(np.clip(window / 80.0, 0.04, 0.2))
    times = np.arange(0.0, window + max_delay + dt, dt)
    span = np.maximum(dur, 1e-9)

    def separation(pi: np.ndarray, pj: np.ndarray, chunk: int = 2048) -> np.ndarray:
        out = np.empty(len(pi))
        for s0 in range(0, len(pi), chunk):
            i, j = pi[s0 : s0 + chunk], pj[s0 : s0 + chunk]
            si = profile_progress((times[None, :] - delays[i, None]) / span[i, None], profile)
            sj = profile_progress((times[None, :] - delays[j, None]) / span[j, None], profile)
            pi_pos = a[i, None, :] + (b[i] - a[i])[:, None, :] * si[..., None]
            pj_pos = a[j, None, :] + (b[j] - a[j])[:, None, :] * sj[..., None]
            out[s0 : s0 + chunk] = np.min(np.linalg.norm(pi_pos - pj_pos, axis=2), axis=1)
        return out

    pairs_of: list[list[int]] = [[] for _ in range(n)]
    for p, (i, j) in enumerate(zip(ii, jj)):
        pairs_of[i].append(p)
        pairs_of[j].append(p)
    pairs_idx = [np.asarray(p, dtype=int) for p in pairs_of]
    target = min_distance - 1e-6
    max_steps = int(np.floor(max_delay / step + 1e-9))

    # Stage 1: prioritised scheduling with a few candidate orders
    direction = b - a
    lengths = np.linalg.norm(direction, axis=1)
    unit = direction / np.where(lengths > 1e-9, lengths, 1.0)[:, None]
    lead = np.einsum("ij,ij->i", a - a.mean(axis=0), unit)
    involved = np.flatnonzero([len(p) > 0 for p in pairs_idx])
    orders = [
        involved[np.argsort(-lead[involved], kind="stable")],
        involved[np.argsort(-lengths[involved], kind="stable")],
        involved[np.argsort(lengths[involved], kind="stable")],
    ]
    best_plan: tuple[float, float, np.ndarray] | None = None
    for order in orders:
        delays[:] = 0.0
        scheduled = np.zeros(n, dtype=bool)
        for k in order:
            if time.perf_counter() > deadline:
                break
            idx = pairs_idx[k]
            partners = np.where(ii[idx] == k, jj[idx], ii[idx])
            sub = idx[scheduled[partners]]
            scheduled[k] = True
            if len(sub) == 0:
                continue
            chosen, chosen_sep = 0.0, -np.inf
            for m in range(max_steps + 1):
                delays[k] = m * step
                worst = float(np.min(separation(ii[sub], jj[sub])))
                if worst >= target:
                    chosen = m * step
                    break
                if worst > chosen_sep + 1e-9:
                    chosen, chosen_sep = m * step, worst
            delays[k] = chosen
        sep_all = separation(ii, jj)
        deficit = float(np.sum(np.maximum(0.0, target - sep_all)))
        candidate = (deficit, float(np.max(delays)), delays.copy())
        if best_plan is None or candidate[:2] < best_plan[:2]:
            best_plan = candidate
        if deficit <= 0.0:
            break
    assert best_plan is not None
    delays[:] = best_plan[2]

    # Stage 2: local repair of the remaining conflicts
    sep = separation(ii, jj)
    blocked = np.zeros(len(ii), dtype=bool)

    for _ in range(max_iterations or 20 * n):
        if time.perf_counter() > deadline:
            break
        bad = np.flatnonzero((sep < target) & ~blocked)
        if len(bad) == 0:
            break
        p = int(bad[np.argmin(sep[bad])])
        best: tuple | None = None
        for k in (int(ii[p]), int(jj[p])):
            idx = pairs_idx[k]
            before = float(np.sum(np.maximum(0.0, target - sep[idx])))
            original = delays[k]
            for m in range(1, 9):
                trial = original + m * step
                if trial > max_delay + 1e-9:
                    break
                delays[k] = trial
                s = separation(ii[idx], jj[idx])
                deficit = float(np.sum(np.maximum(0.0, target - s)))
                gain = before - deficit
                score = (gain, float(np.min(s)), -trial)
                if gain > 1e-9 and (best is None or score > best[0]):
                    best = (score, k, trial, s)
                if deficit <= 0.0:
                    break
            delays[k] = original
        if best is None:
            blocked[p] = True
            continue
        _, k, trial, s = best
        delays[k] = trial
        sep[pairs_idx[k]] = s
    return delays


@dataclass
class MovePlan:
    """Straight-line moves through a sequence of waypoints.

    Drone ``i`` travels from ``waypoints[i, k]`` to ``waypoints[i, k + 1]``
    between ``starts[i, k]`` and ``starts[i, k] + durations[i, k]`` (times
    relative to the beginning of the plan), each leg with the same velocity
    profile.
    """

    waypoints: np.ndarray  # (n, m + 1, 3)
    starts: np.ndarray  # (n, m)
    durations: np.ndarray  # (n, m)
    profile: str = "smooth"
    label: str = "synchronised"

    @property
    def total_duration(self) -> float:
        return float(np.max(self.starts + self.durations)) if self.starts.size else 0.0

    def positions(self, times: np.ndarray) -> np.ndarray:
        """Positions at ``times``, shape ``(len(times), n, 3)``."""
        t = np.asarray(times, dtype=float)
        out = np.repeat(self.waypoints[None, :, 0, :], len(t), axis=0)
        for k in range(self.starts.shape[1]):
            leg = self.waypoints[:, k + 1] - self.waypoints[:, k]
            tau = (t[:, None] - self.starts[None, :, k]) / np.maximum(
                self.durations[None, :, k], 1e-9
            )
            out += leg[None] * profile_progress(tau, self.profile)[..., None]
        return out

    def min_separation(self, dt: float = 0.1) -> float:
        """Smallest distance between any two drones during the plan."""
        from .._compat import KDTree as cKDTree

        n = self.waypoints.shape[0]
        if n < 2:
            return float("inf")
        times = np.arange(0.0, self.total_duration + dt, dt)
        best = float("inf")
        for chunk in range(0, len(times), 64):
            frames = self.positions(times[chunk : chunk + 64])
            for frame in frames:
                d, _ = cKDTree(frame).query(frame, k=2)
                best = min(best, float(np.min(d[:, 1])))
        return best


def synchronised_plan(
    a: np.ndarray, b: np.ndarray, window: float, profile: str = "smooth"
) -> MovePlan:
    n = len(a)
    return MovePlan(
        np.stack([a, b], axis=1), np.zeros((n, 1)), np.full((n, 1), window), profile, "synchronised"
    )


def staggered_plan(
    a: np.ndarray, b: np.ndarray, window: float, min_distance: float, profile: str = "smooth"
) -> MovePlan:
    delays = stagger_transition(a, b, np.full(len(a), window), min_distance, profile=profile)
    return MovePlan(
        np.stack([a, b], axis=1),
        delays[:, None],
        np.full((len(a), 1), window),
        profile,
        "staggered",
    )


def conflict_lanes(a: np.ndarray, b: np.ndarray, min_distance: float) -> np.ndarray:
    """Colours drones so that any two drones whose synchronised straight-line
    paths come closer than ``min_distance`` get different colours (lanes).
    Lane 0 is the largest group."""
    from .grouping import _dsatur, _relabel_by_size

    a = as_points(a)
    b = as_points(b)
    n = len(a)
    adjacency: list[set[int]] = [set() for _ in range(n)]
    delta = b - a
    for lo in range(0, n, 512):
        hi = min(n, lo + 512)
        d0 = a[lo:hi, None, :] - a[None, :, :]
        d1 = delta[lo:hi, None, :] - delta[None, :, :]
        dd = np.einsum("ijk,ijk->ij", d1, d1)
        s = np.clip(-np.einsum("ijk,ijk->ij", d0, d1) / np.where(dd > 1e-12, dd, 1.0), 0, 1)
        dist = np.linalg.norm(d0 + s[..., None] * d1, axis=2)
        for r, c in zip(*np.nonzero(dist < min_distance)):
            i = lo + int(r)
            if i != c:
                adjacency[i].add(int(c))
                adjacency[int(c)].add(i)
    if not any(adjacency):
        return np.zeros(n, dtype=int)
    return np.asarray(_relabel_by_size(_dsatur(adjacency)))


def lane_plan(
    a: np.ndarray,
    b: np.ndarray,
    min_distance: float,
    duration_fn,
    *,
    profile: str = "smooth",
    axis: np.ndarray | None = None,
    spacing: float | None = None,
) -> MovePlan | None:
    """Three-phase transition through parallel lanes.

    Drones whose synchronised straight paths would conflict are coloured into
    different lanes. Every drone first moves sideways along ``axis`` to its
    lane offset, then all drones fly the transition in their lanes, then
    they move back. For formations lying in planes perpendicular to
    ``axis`` the lanes keep conflicting drones ``spacing`` apart.

    ``duration_fn(delta)`` must return the minimum duration of each move.
    Returns ``None`` if no lanes are needed.
    """
    n = len(a)
    if n < 2:
        return None
    if axis is None:
        pts = np.vstack([a, b])
        _, _, vt = np.linalg.svd(pts - pts.mean(axis=0), full_matrices=False)
        axis = vt[-1]
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    spacing = spacing or min_distance * 1.1

    lanes = conflict_lanes(a, b, min_distance)
    if not np.any(lanes):
        return None
    # lane 0 stays in place, then +1, -1, +2, -2, ...
    rank = np.where(lanes % 2 == 1, (lanes + 1) // 2, -(lanes // 2))
    offsets = rank[:, None] * spacing * axis[None, :]

    w1 = a + offsets
    w2 = b + offsets
    p1 = float(np.max(duration_fn(offsets), initial=0.0))
    p2 = float(np.max(duration_fn(w2 - w1), initial=0.0))
    starts = np.tile(np.array([0.0, p1, p1 + p2]), (n, 1))
    durations = np.tile(np.array([p1, p2, p1]), (n, 1))
    return MovePlan(
        np.stack([a, w1, w2, b], axis=1),
        starts,
        durations,
        profile,
        f"{int(lanes.max()) + 1} lanes",
    )


def plan_safe_moves(
    a: np.ndarray,
    b: np.ndarray,
    *,
    min_distance: float,
    duration_fn,
    profile: str = "smooth",
    minimum_window: float = 0.0,
    allow_lanes: bool = True,
    time_limit: float = 12.0,
    allow_two_leg: bool = True,
) -> tuple[MovePlan, float]:
    """Picks the fastest of synchronised, staggered and lane-based transitions
    that keeps ``min_distance`` (or the safest one if none does).

    The search stops after ``time_limit`` seconds and returns the best plan
    found so far. If the end positions themselves are closer than
    ``min_distance`` no plan can help, so the synchronised one is returned
    straight away.

    Returns the plan and its verified minimum separation.
    """
    started = time.perf_counter()
    a = as_points(a)
    b = as_points(b)
    window = max(float(np.max(duration_fn(b - a), initial=0.0)), minimum_window)
    plan = synchronised_plan(a, b, window, profile)
    if len(a) < 2 or window <= 0:
        return plan, float("inf")
    clearance, _ = synchronized_clearance(a, b)
    if clearance >= min_distance - 1e-6:
        return plan, clearance

    from .._compat import KDTree

    end_spacing = float(np.min(KDTree(b).query(b, k=2)[0][:, 1]))
    if end_spacing < min_distance - 1e-6:
        return plan, min(clearance, end_spacing)

    candidates = [(plan, clearance)]

    def done() -> bool:
        if time.perf_counter() - started > time_limit:
            return True
        return any(c[1] >= min_distance - 1e-3 for c in candidates)

    staggered = staggered_plan(a, b, window, min_distance, profile)
    if np.any(staggered.starts > 0):
        candidates.append((staggered, staggered.min_separation()))
    if allow_lanes and allow_two_leg and not done():
        # vertical moves keep the horizontal spacing, so a vertical leg is safe
        # and only the horizontal leg can need staggering
        up_first = b.copy()
        up_first[:, :2] = a[:, :2]
        side_first = b.copy()
        side_first[:, 2] = a[:, 2]
        rising = float(np.mean(b[:, 2] - a[:, 2])) >= 0
        for mid, horizontal_leg, label in (
            (
                (up_first, 1, "vertical first"),
                (side_first, 0, "horizontal first"),
            )
            if rising
            else (
                (side_first, 0, "horizontal first"),
                (up_first, 1, "vertical first"),
            )
        ):
            legs = _two_leg_plan(
                a, mid, b, horizontal_leg, min_distance, duration_fn, profile, label
            )
            candidates.append((legs, legs.min_separation()))
            if done():
                break
    if allow_lanes and not done():
        for factor in (1.6, 2.2):
            via = _via_expanded_plan(a, b, factor, min_distance, duration_fn, profile)
            candidates.append((via, via.min_separation()))
            if done():
                break
    if allow_lanes and not done():
        pts = np.vstack([a, b])
        _, _, vt = np.linalg.svd(pts - pts.mean(axis=0), full_matrices=False)
        axes = [
            vt[-1],
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
            np.array([1.0, 0.0, 0.0]),
        ]
        for axis in axes:
            lanes = lane_plan(a, b, min_distance, duration_fn, profile=profile, axis=axis)
            if lanes is None:
                break
            candidates.append((lanes, lanes.min_separation()))
            if done():
                break
            hybrid = _stagger_lane_phase(lanes, min_distance)
            if hybrid is not None:
                candidates.append((hybrid, hybrid.min_separation()))
                if done():
                    break

    safe = [c for c in candidates if c[1] >= min_distance - 1e-3]
    if safe:
        return min(safe, key=lambda c: c[0].total_duration)
    return max(candidates, key=lambda c: c[1])


def _two_leg_plan(a, mid, b, free_leg: int, min_distance, duration_fn, profile, label) -> MovePlan:
    """``a`` -> ``mid`` -> ``b``. The leg ``free_leg`` (0 or 1) is planned
    with every conflict-resolution strategy; the other one is a plain vertical
    move, which cannot bring drones closer horizontally."""
    plans = []
    for k, (start, end) in enumerate(((a, mid), (mid, b))):
        if k == free_leg:
            plans.append(
                plan_safe_moves(
                    start,
                    end,
                    min_distance=min_distance,
                    duration_fn=duration_fn,
                    profile=profile,
                    allow_two_leg=False,
                    time_limit=5.0,
                )[0]
            )
        else:
            window = float(np.max(duration_fn(end - start), initial=0.0))
            plans.append(synchronised_plan(start, end, window, profile))
    first, second = plans
    offset = first.total_duration
    return MovePlan(
        np.concatenate([first.waypoints, second.waypoints[:, 1:]], axis=1),
        np.concatenate([first.starts, second.starts + offset], axis=1),
        np.concatenate([first.durations, second.durations], axis=1),
        profile,
        label,
    )


def _via_expanded_plan(
    a: np.ndarray,
    b: np.ndarray,
    factor: float,
    min_distance: float,
    duration_fn,
    profile: str,
) -> MovePlan:
    """Two-leg transition through a horizontally enlarged copy of the target.

    The first leg has more room to resolve conflicts (it is staggered if
    needed). The second leg scales the formation horizontally back to its
    final size around its centre; along that leg every pairwise offset is
    ``diag(k, k, 1)`` times its final value with ``k`` shrinking from
    ``factor`` to 1, so no distance can drop below the target spacing.
    """
    centre = b.mean(axis=0)
    wide = b.copy()
    wide[:, :2] = centre[:2] + (b[:, :2] - centre[:2]) * factor
    first_window = float(np.max(duration_fn(wide - a), initial=0.0))
    first = synchronised_plan(a, wide, first_window, profile)
    if synchronized_clearance(a, wide)[0] < min_distance - 1e-6:
        first = staggered_plan(a, wide, first_window, min_distance, profile)
    second = float(np.max(duration_fn(b - wide), initial=0.0))
    end_first = first.starts[:, 0] + first.durations[:, 0]
    starts = np.column_stack([first.starts[:, 0], np.full(len(a), float(np.max(end_first)))])
    durations = np.column_stack([first.durations[:, 0], np.full(len(a), second)])
    return MovePlan(
        np.stack([a, wide, b], axis=1), starts, durations, profile, f"via {factor:g}x spread"
    )


def _stagger_lane_phase(plan: MovePlan, min_distance: float) -> MovePlan | None:
    """Adds per-drone delays to the in-lane phase of a lane plan."""
    w1, w2 = plan.waypoints[:, 1], plan.waypoints[:, 2]
    p1, p2 = float(plan.durations[0, 0]), float(plan.durations[0, 1])
    delays = stagger_transition(w1, w2, np.full(len(w1), p2), min_distance, profile=plan.profile)
    if not np.any(delays > 0):
        return None
    starts = plan.starts.copy()
    starts[:, 1] = p1 + delays
    starts[:, 2] = p1 + float(np.max(delays)) + p2
    return MovePlan(
        plan.waypoints, starts, plan.durations.copy(), plan.profile, plan.label + " + staggered"
    )


def plan_transition(
    source: Sequence[Sequence[float]] | np.ndarray,
    target: Sequence[Sequence[float]] | np.ndarray,
    *,
    max_velocity_xy: float,
    max_velocity_z: float,
    max_acceleration: float,
    max_velocity_z_up: float | None = None,
    matching_method: str = "optimal",
    radius: float | Sequence[float] | None = None,
    min_distance: float | None = None,
    profile: str = "smooth",
) -> TransitionPlan:
    """Plans a transition from the ``source`` points to the ``target`` points.

    All drones move along straight lines with the same velocity profile.
    By default the transition is synchronised: every drone starts at the
    same time and arrives at the same time, which keeps the relative geometry
    of the swarm an affine blend of the two formations. If ``min_distance``
    is given and the synchronised plan would bring two drones closer than
    that, some drones are delayed to resolve the conflict.
    """
    src = as_points(source)
    dst = as_points(target)
    if len(src) == 0 or len(dst) == 0:
        return TransitionPlan(mapping=[] if matching_method != "fixed" else None)

    if matching_method == "optimal":
        mapping = match_points(src, dst)
    elif matching_method == "fixed":
        mapping = [i if i < len(src) else None for i in range(len(dst))]
    else:
        raise ValueError(f"unknown matching method: {matching_method!r}")

    targets = [i for i, m in enumerate(mapping) if m is not None]
    sources = [mapping[i] for i in targets]
    a = src[sources]
    b = dst[targets]

    own = min_transition_durations(
        b - a,
        max_velocity_xy=max_velocity_xy,
        max_velocity_z=max_velocity_z,
        max_velocity_z_up=max_velocity_z_up,
        max_acceleration=max_acceleration,
        profile=profile,
    )
    window = float(np.max(own)) if len(own) else 0.0
    durations = np.full(len(a), window)

    delays = np.zeros(len(a))
    if min_distance:
        delays = stagger_transition(a, b, durations, float(min_distance), profile=profile)

    start_times = [0.0] * len(dst)
    all_durations = [0.0] * len(dst)
    for k, i in enumerate(targets):
        start_times[i] = float(delays[k])
        all_durations[i] = float(durations[k])

    clearance = None
    if radius is not None and len(a) >= 2:
        clearance, _ = synchronized_clearance(a, b, radius)

    return TransitionPlan(
        start_times=start_times,
        durations=all_durations,
        mapping=mapping if matching_method != "fixed" else None,
        clearance=clearance,
    )
