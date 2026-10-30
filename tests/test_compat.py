import subprocess
import sys
import textwrap

import numpy as np
import pytest

from murmura._compat import _numpy_cdist, _numpy_lsa, _NumpyTree

scipy = pytest.importorskip("scipy")
from scipy.optimize import linear_sum_assignment  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402


@pytest.mark.parametrize("shape", [(1, 1), (5, 5), (7, 12), (12, 7), (60, 60)])
def test_assignment_fallback_matches_scipy(shape):
    rng = np.random.default_rng(sum(shape))
    cost = rng.uniform(0, 100, shape)
    rows, cols = _numpy_lsa(cost)
    ref_rows, ref_cols = linear_sum_assignment(cost)
    assert len(rows) == min(shape)
    assert len(set(cols.tolist())) == len(cols)
    assert cost[rows, cols].sum() == pytest.approx(cost[ref_rows, ref_cols].sum())


def test_tree_fallback_matches_scipy():
    rng = np.random.default_rng(5)
    pts = rng.uniform(0, 10, (300, 3))
    ours, ref = _NumpyTree(pts), cKDTree(pts)
    d1, i1 = ours.query(pts, k=2)
    d2, i2 = ref.query(pts, k=2)
    assert np.allclose(d1, d2)
    assert ours.query_pairs(1.0) == ref.query_pairs(1.0)
    got = [sorted(x) for x in ours.query_ball_point(pts[:20], 1.5)]
    want = [sorted(x) for x in ref.query_ball_point(pts[:20], 1.5)]
    assert got == want
    d, i = ours.query(pts[:5])
    assert np.allclose(d, 0) and i.tolist() == [0, 1, 2, 3, 4]


def test_cdist_fallback():
    a = np.random.default_rng(1).uniform(size=(20, 3))
    b = np.random.default_rng(2).uniform(size=(30, 3))
    from scipy.spatial.distance import cdist

    assert np.allclose(_numpy_cdist(a, b), cdist(a, b))
    assert np.allclose(_numpy_cdist(a, b, "sqeuclidean"), cdist(a, b, "sqeuclidean"))


def test_show_builds_without_scipy_and_yaml():
    code = textwrap.dedent(
        """
        import sys
        sys.modules["scipy"] = None
        sys.modules["yaml"] = None
        from murmura import _compat, ShowBuilder, validate_show, write_skyc, read_skyc
        from murmura.formations import circle, star
        assert not _compat.HAVE_SCIPY
        from murmura import SafetyLimits
        b = ShowBuilder(20, grid_spacing=3, limits=SafetyLimits(min_distance=2))
        b.takeoff()
        b.scene("Ring", circle(20, radius=10, center=(0, 0, 20)), hold=3)
        b.scene("Star", star(20, radius=14, center=(0, 0, 22)), hold=3)
        b.land()
        show = b.build()
        assert validate_show(show).passed
        assert read_skyc(write_skyc(show)).num_drones == 20
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
