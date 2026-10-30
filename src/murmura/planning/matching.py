"""Optimal assignment of drones to formation points and clearance analysis."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .._compat import cdist, linear_sum_assignment

__all__ = ("as_points", "match_points", "synchronized_clearance")


def as_points(points: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    arr = np.asarray(points, dtype=float)
    if arr.size == 0:
        return np.zeros((0, 3))
    if arr.ndim != 2 or arr.shape[1] not in (2, 3):
        raise ValueError("points must be a list of 2D or 3D coordinates")
    if arr.shape[1] == 2:
        arr = np.column_stack([arr, np.zeros(len(arr))])
    return arr


def match_points(
    source: Sequence[Sequence[float]] | np.ndarray,
    target: Sequence[Sequence[float]] | np.ndarray,
    *,
    cost: str = "squared",
) -> list[int | None]:
    """Assigns source points (drones) to target points (formation markers).

    With ``cost="squared"`` (default) the sum of squared distances is
    minimised. This keeps the relative structure of the swarm during a
    synchronised straight-line transition and produces far fewer near misses
    than minimising the plain travelled distance (``cost="distance"``),
    especially between 3D and planar formations.

    Returns:
        a list where the i-th item is the index of the source point assigned
        to the i-th target point, or ``None`` if the target stays unassigned
        (when there are fewer sources than targets)
    """
    src = as_points(source)
    dst = as_points(target)
    mapping: list[int | None] = [None] * len(dst)
    if len(src) == 0 or len(dst) == 0:
        return mapping
    if cost == "squared":
        matrix = cdist(dst, src, "sqeuclidean")
    elif cost == "distance":
        matrix = cdist(dst, src)
    else:
        raise ValueError(f"unknown matching cost: {cost!r}")
    rows, cols = linear_sum_assignment(matrix)
    for r, c in zip(rows, cols):
        mapping[int(r)] = int(c)
    return mapping


def synchronized_clearance(
    start: np.ndarray,
    end: np.ndarray,
    radius: float | Sequence[float] | None = None,
    *,
    chunk: int = 512,
) -> tuple[float, tuple[int, int] | None]:
    """Computes the minimum distance between drones that move along straight
    lines from ``start`` to ``end`` while all of them share the same
    normalised progress (i.e. a synchronised transition).

    For a pair ``(i, j)`` the separation is ``|D0 + s·D1|`` with
    ``D0 = A_i - A_j`` and ``D1 = (B_i - A_i) - (B_j - A_j)``, minimised over
    ``s ∈ [0, 1]`` in closed form.

    Returns:
        the minimum separation (minus the radii of the two drones, if given)
        and the index pair achieving it; ``(inf, None)`` for fewer than two drones
    """
    a = as_points(start)
    b = as_points(end)
    n = len(a)
    if n < 2:
        return float("inf"), None

    if radius is None:
        radii = np.zeros(n)
    else:
        radii = np.broadcast_to(np.asarray(radius, dtype=float), (n,))

    delta = b - a
    best = float("inf")
    best_pair: tuple[int, int] | None = None
    for lo in range(0, n, chunk):
        hi = min(n, lo + chunk)
        d0 = a[lo:hi, None, :] - a[None, :, :]
        d1 = delta[lo:hi, None, :] - delta[None, :, :]
        dd = np.einsum("ijk,ijk->ij", d1, d1)
        s = np.where(
            dd > 1e-12, -np.einsum("ijk,ijk->ij", d0, d1) / np.where(dd > 1e-12, dd, 1.0), 0.0
        )
        s = np.clip(s, 0.0, 1.0)
        closest = d0 + s[..., None] * d1
        dist = np.sqrt(np.einsum("ijk,ijk->ij", closest, closest))
        dist -= radii[lo:hi, None] + radii[None, :]
        rows = np.arange(lo, hi)
        # only consider j > i
        mask = np.arange(n)[None, :] <= rows[:, None]
        dist[mask] = np.inf
        idx = np.unravel_index(np.argmin(dist), dist.shape)
        if dist[idx] < best:
            best = float(dist[idx])
            best_pair = (int(rows[idx[0]]), int(idx[1]))
    return best, best_pair
