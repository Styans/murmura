import itertools

import numpy as np
import pytest

from murmura.formations import circle, grid
from murmura.planning import (
    decompose_points,
    match_points,
    min_transition_durations,
    plan_landing,
    plan_safe_moves,
    plan_smart_rth,
    plan_takeoff,
    plan_transition,
    synchronized_clearance,
)

SOURCE = [[0, 0, 10], [3, 0, 10], [6, 0, 10], [0, 3, 10]]
TARGET = [[6, 3, 15], [0, 6, 12], [3, 6, 12], [6, 6, 12]]


def test_matching_is_optimal():
    rng = np.random.default_rng(0)
    src = rng.uniform(0, 10, (6, 3))
    dst = rng.uniform(0, 10, (6, 3))
    mapping = match_points(src, dst)
    cost = sum(np.sum((dst[t] - src[s]) ** 2) for t, s in enumerate(mapping))
    best = min(
        sum(np.sum((dst[t] - src[p[t]]) ** 2) for t in range(6))
        for p in itertools.permutations(range(6))
    )
    assert cost == pytest.approx(best)


def test_transition_timing_and_clearance():
    plan = plan_transition(
        SOURCE, TARGET, max_velocity_xy=8, max_velocity_z=2, max_acceleration=4, radius=0.5
    )
    assert plan.durations == [3.75] * 4  # 1.5 * 5 m / 2 m/s
    assert plan.start_times == [0.0] * 4
    assert round(plan.clearance, 3) == 1.121
    assert sorted(plan.mapping) == [0, 1, 2, 3]


def test_fixed_matching_omits_mapping():
    plan = plan_transition(
        SOURCE,
        TARGET,
        max_velocity_xy=8,
        max_velocity_z=2,
        max_acceleration=4,
        matching_method="fixed",
    )
    assert plan.mapping is None


def test_min_durations_respect_limits():
    delta = np.array([[10.0, 0, 0], [0, 0, 6.0], [0, 0, -6.0]])
    t = min_transition_durations(
        delta, max_velocity_xy=5, max_velocity_z=3, max_velocity_z_up=2, max_acceleration=100
    )
    assert t.tolist() == pytest.approx([3.0, 4.5, 3.0])


def test_takeoff_groups_are_safe():
    pts = grid(64, spacing=1.5)
    groups = np.asarray(plan_takeoff(pts, min_distance=2.0))
    for g in np.unique(groups):
        members = pts[groups == g]
        d = np.linalg.norm(members[:, None, :2] - members[None, :, :2], axis=2)
        d[np.diag_indices(len(members))] = np.inf
        assert d.min() >= 2.0


def test_balanced_decomposition_is_valid_and_even():
    pts = np.random.default_rng(1).uniform(0, 20, (120, 3))
    groups = np.asarray(decompose_points(pts, min_distance=4.0, method="balanced"))
    sizes = np.bincount(groups)
    assert sizes.max() - sizes.min() <= max(3, sizes.mean() * 0.5)
    for g in np.unique(groups):
        members = pts[groups == g]
        if len(members) > 1:
            d = np.linalg.norm(members[:, None] - members[None], axis=2)
            d[np.diag_indices(len(members))] = np.inf
            assert d.min() >= 4.0


def test_landing_keeps_spindown_and_separation():
    # a stacked column: horizontally close, vertically separated
    pts = np.array([[0, 0, 10], [1, 0, 14], [2, 0, 18], [0.5, 1, 22]], dtype=float)
    starts, durations = plan_landing(pts, min_distance=3, velocity=1.5, spindown_time=5)
    touch = np.array(starts) + np.array(durations)
    order = np.argsort(touch)
    assert np.all(np.diff(touch[order]) >= 5 - 1e-6)
    t = np.linspace(0, touch.max(), 2000)
    z = np.array(
        [np.where(t < s, p[2], np.maximum(0, p[2] - 1.5 * (t - s))) for p, s in zip(pts, starts)]
    )
    for i, j in itertools.combinations(range(4), 2):
        airborne = (z[i] > 0) & (z[j] > 0)
        h = np.hypot(*(pts[i, :2] - pts[j, :2]))
        d = np.sqrt(h**2 + (z[i] - z[j]) ** 2)
        assert np.all(d[airborne] >= 3 - 1e-6)


def test_smart_rth_returns_inner_points_and_staggers_crossing_paths():
    plan = plan_smart_rth(
        [[0, 0, 20], [10, 0, 20], [20, 0, 25]],
        [[20, 0, 0], [10, 3, 0], [0, 0, 0]],
        max_velocity_xy=5,
        max_velocity_z=2,
        max_acceleration=3,
        min_distance=3,
    )
    assert len(plan.start_times) == 3 and len(plan.inner_points) == 3
    assert max(plan.start_times) > 0
    for d, inner in zip(plan.durations, plan.inner_points):
        assert all(0 < p[0] < d for p in inner)


def test_safe_moves_resolve_grid_to_ring():
    home = grid(100, spacing=2.5, columns=10)
    home[:, 2] = 6
    ring = circle(100, radius=38, center=(0, 0, 30), plane="xy")
    mapping = match_points(home, ring)
    target = np.zeros_like(home)
    for t, d in enumerate(mapping):
        target[d] = ring[t]
    assert synchronized_clearance(home, target)[0] < 2.0

    def durations(delta):
        return min_transition_durations(
            delta, max_velocity_xy=6, max_velocity_z=2.5, max_acceleration=2.5
        )

    plan, separation = plan_safe_moves(home, target, min_distance=2.0, duration_fn=durations)
    assert separation >= 2.0 - 1e-3
    assert plan.min_separation(dt=0.05) >= 2.0 - 2e-3


def test_takeoff_layers_checkerboard():
    from murmura.planning import takeoff_layers

    xs, ys = np.meshgrid(np.arange(6) * 1.5, np.arange(6) * 1.5)
    pts = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(36)])
    groups, gap = takeoff_layers(pts, min_distance=2.0)
    assert groups.max() == 1
    assert groups[0] != groups[1] and groups[0] == groups[7]
    assert np.hypot(1.5, gap) >= 2.0
    groups, gap = takeoff_layers(pts * 2, min_distance=2.0)
    assert groups.max() == 0 and gap == 0.0


def test_plan_waves_keeps_the_gap():
    from murmura.planning import plan_waves, profile_progress

    starts, durations = plan_waves([7.4, 6.0], gap=1.4, velocity=1.2, max_acceleration=3)
    assert starts[0] == 0 and starts[1] > 0
    t = np.linspace(starts[1], starts[1] + durations[1], 500)
    z0 = 7.4 * profile_progress((t - starts[0]) / durations[0])
    z1 = 6.0 * profile_progress((t - starts[1]) / durations[1])
    assert np.all(z0 - z1 >= 1.4 - 1e-6)
    # the next wave does not wait for the previous one to finish
    assert starts[1] < durations[0]
    spaced, _ = plan_waves([7.4, 6.0], gap=1.4, velocity=1.2, max_acceleration=3, min_offset=10)
    assert spaced[1] == 10
