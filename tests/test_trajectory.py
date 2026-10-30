import numpy as np
import pytest

from murmura.trajectory import Trajectory


def _smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def test_fit_respects_tolerance_and_compresses():
    t = np.arange(0, 30.0001, 0.25)
    pos = np.zeros((len(t), 3))
    pos[:, 0] = 15 * _smoothstep((t - 2) / 6)
    pos[:, 2] = 10
    curve = t > 12
    pos[curve, 0] = 15 * np.cos((t[curve] - 12) * 0.4)
    pos[curve, 1] = 15 * np.sin((t[curve] - 12) * 0.4)
    traj = Trajectory.from_samples(t, pos, tolerance=0.03)
    error = np.linalg.norm(traj.position_at(t) - pos, axis=1)
    assert error.max() <= 0.03 + 1e-9
    assert len(traj) < len(t) / 4


def test_hover_sections_are_exact():
    t = np.arange(0, 10.0001, 0.25)
    pos = np.tile([1.0, 2.0, 3.0], (len(t), 1))
    pos[t > 5, 0] += (t[t > 5] - 5) * 0.5
    traj = Trajectory.from_samples(t, pos)
    dense = np.linspace(0, 5, 200)
    assert np.allclose(traj.position_at(dense), [1, 2, 3], atol=1e-9)


def test_velocity_is_continuous_at_joints():
    t = np.arange(0, 20.0001, 0.25)
    pos = np.column_stack([10 * np.sin(t * 0.7), 6 * np.cos(t * 0.3), 20 + t * 0.1])
    traj = Trajectory.from_samples(t, pos, tolerance=0.01)
    joints = np.array([p.t for p in traj.points[1:-1]])
    before = traj.velocity_at(joints - 1e-6)
    after = traj.velocity_at(joints + 1e-6)
    assert np.max(np.abs(before - after)) < 1e-3


def test_smooth_segment_is_exact_smoothstep():
    traj = Trajectory().start_at(0, (0, 0, 0)).smooth_to(4, (8, 0, 0))
    t = np.linspace(0, 4, 41)
    assert np.allclose(traj.position_at(t)[:, 0], 8 * _smoothstep(t / 4))
    assert traj.velocity_at([0.0])[0, 0] == pytest.approx(0.0)
    assert traj.velocity_at([2.0])[0, 0] == pytest.approx(1.5 * 8 / 4)
    assert traj.acceleration_at([0.0])[0, 0] == pytest.approx(6 * 8 / 16)


def test_positions_are_clamped_outside_the_trajectory():
    traj = Trajectory().start_at(2, (1, 1, 1)).line_to(4, (3, 1, 1))
    assert traj.position_at([0.0])[0].tolist() == [1, 1, 1]
    assert traj.position_at([10.0])[0].tolist() == [3, 1, 1]
    assert traj.velocity_at([10.0])[0].tolist() == [0, 0, 0]


def test_first_movement_time():
    traj = Trajectory().start_at(0, (0, 0, 0)).hold_until(5).smooth_to(9, (0, 0, 6))
    assert traj.first_movement_time() == 5
    assert Trajectory.stationary((1, 2, 0), 0, 10).first_movement_time() == 0


def test_cannot_jump_without_time():
    traj = Trajectory().start_at(0, (0, 0, 0))
    with pytest.raises(ValueError):
        traj.line_to(0, (1, 0, 0))
