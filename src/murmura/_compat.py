"""Optional SciPy acceleration with pure NumPy fallbacks.

Murmura runs inside environments that ship NumPy but not SciPy (for example
the Python bundled with Blender). This module exposes the few SciPy
primitives Murmura needs and falls back to NumPy implementations when SciPy
is not installed. The fallbacks are exact but scale quadratically, which is
fine for swarms of a few thousand drones.
"""

from __future__ import annotations

import numpy as np

__all__ = ("HAVE_SCIPY", "KDTree", "cdist", "linear_sum_assignment")

try:  # pragma: no cover - exercised implicitly when SciPy is available
    from scipy.optimize import linear_sum_assignment as _scipy_lsa
    from scipy.spatial import cKDTree as _ScipyTree
    from scipy.spatial.distance import cdist as _scipy_cdist

    HAVE_SCIPY = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_SCIPY = False


def _numpy_cdist(a: np.ndarray, b: np.ndarray, metric: str = "euclidean") -> np.ndarray:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.empty((len(a), len(b)))
    for lo in range(0, len(a), 1024):
        diff = a[lo : lo + 1024, None, :] - b[None, :, :]
        out[lo : lo + 1024] = np.einsum("ijk,ijk->ij", diff, diff)
    if metric == "euclidean":
        np.sqrt(out, out=out)
    elif metric != "sqeuclidean":
        raise ValueError(f"unsupported metric: {metric!r}")
    return out


def _numpy_lsa(cost: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Minimum-cost assignment (Hungarian method with potentials).

    Returns row and column indices like :func:`scipy.optimize.linear_sum_assignment`.
    """
    cost = np.asarray(cost, dtype=float)
    if cost.size == 0:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=int)
    transposed = cost.shape[0] > cost.shape[1]
    a = cost.T if transposed else cost
    n, m = a.shape
    u = np.zeros(n + 1)
    v = np.zeros(m + 1)
    p = np.zeros(m + 1, dtype=int)  # p[j]: row (1-based) assigned to column j
    way = np.zeros(m + 1, dtype=int)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(m + 1, np.inf)
        used = np.zeros(m + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            free = ~used[1:]
            current = a[i0 - 1] - u[i0] - v[1:]
            better = free & (current < minv[1:])
            minv[1:][better] = current[better]
            way[1:][better] = j0
            masked = np.where(free, minv[1:], np.inf)
            j1 = int(np.argmin(masked)) + 1
            delta = masked[j1 - 1]
            u[p[used]] += delta
            v[used] -= delta
            minv[1:][free] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    cols = np.flatnonzero(p[1:]) + 0
    rows = p[1:][cols] - 1
    if transposed:
        rows, cols = cols, rows
    order = np.argsort(rows)
    return rows[order], cols[order]


class _NumpyTree:
    """Brute-force replacement for the parts of ``cKDTree`` Murmura uses."""

    def __init__(self, data):
        self.data = np.asarray(data, dtype=float)
        self._norms = np.einsum("ij,ij->i", self.data, self.data)

    def _sqdist(self, x: np.ndarray) -> np.ndarray:
        # |x|² + |y|² - 2 x·y uses a matrix product, far faster than broadcasting
        d2 = np.einsum("ij,ij->i", x, x)[:, None] + self._norms[None, :] - 2.0 * (x @ self.data.T)
        return np.maximum(d2, 0.0, out=d2)

    def query(self, x, k: int = 1):
        x = np.atleast_2d(np.asarray(x, dtype=float))
        n = len(self.data)
        kk = min(k, n)
        dist = np.empty((len(x), kk))
        idx = np.empty((len(x), kk), dtype=int)
        rows = np.arange(min(512, len(x)))
        for lo in range(0, len(x), 512):
            d2 = self._sqdist(x[lo : lo + 512])
            if kk <= 2:
                # nearest one or two neighbours: two argmin passes beat a partition
                r = rows[: len(d2)]
                chunk = x[lo : lo + 512]
                first = np.argmin(d2, axis=1)
                idx[lo : lo + 512, 0] = first
                # exact distances for the chosen neighbours
                dist[lo : lo + 512, 0] = np.linalg.norm(chunk - self.data[first], axis=1)
                if kk == 2:
                    d2[r, first] = np.inf
                    second = np.argmin(d2, axis=1)
                    idx[lo : lo + 512, 1] = second
                    dist[lo : lo + 512, 1] = np.linalg.norm(chunk - self.data[second], axis=1)
                continue
            if kk < n:
                part = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
            else:
                part = np.tile(np.arange(n), (len(d2), 1))
            sub = np.take_along_axis(d2, part, axis=1)
            order = np.argsort(sub, axis=1, kind="stable")
            idx[lo : lo + 512] = np.take_along_axis(part, order, axis=1)
            dist[lo : lo + 512] = np.sqrt(np.take_along_axis(sub, order, axis=1))
        if k == 1:
            return dist[:, 0], idx[:, 0]
        return dist, idx

    def query_pairs(self, r: float) -> set[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        r2 = r * r
        for lo in range(0, len(self.data), 512):
            d2 = self._sqdist(self.data[lo : lo + 512])
            rows, cols = np.nonzero(d2 <= r2)
            for i, j in zip(rows + lo, cols):
                if i < j:
                    pairs.add((int(i), int(j)))
        return pairs

    def query_ball_point(self, x, r: float) -> list[list[int]]:
        x = np.atleast_2d(np.asarray(x, dtype=float))
        out: list[list[int]] = []
        for lo in range(0, len(x), 512):
            d2 = self._sqdist(x[lo : lo + 512])
            out.extend(np.flatnonzero(row <= r * r).tolist() for row in d2)
        return out


if HAVE_SCIPY:
    KDTree = _ScipyTree
    cdist = _scipy_cdist
    linear_sum_assignment = _scipy_lsa
else:  # pragma: no cover - depends on the environment
    KDTree = _NumpyTree  # type: ignore[misc,assignment]
    cdist = _numpy_cdist
    linear_sum_assignment = _numpy_lsa
