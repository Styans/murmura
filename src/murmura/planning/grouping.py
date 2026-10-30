"""Grouping of drones for layered takeoff and decomposition of formations."""

from __future__ import annotations

import heapq
from collections.abc import Sequence

import numpy as np

from .._compat import KDTree as cKDTree
from .matching import as_points

__all__ = ("decompose_points", "plan_takeoff")


def _conflict_graph(points: np.ndarray, radius: float) -> list[set[int]]:
    """Adjacency sets of the graph connecting points closer than ``radius``."""
    n = len(points)
    adjacency: list[set[int]] = [set() for _ in range(n)]
    if n < 2 or radius <= 0:
        return adjacency
    tree = cKDTree(points)
    # query_pairs uses <=, we want strictly closer than radius
    for i, j in tree.query_pairs(np.nextafter(radius, 0.0)):
        adjacency[i].add(j)
        adjacency[j].add(i)
    return adjacency


def _dsatur(adjacency: list[set[int]]) -> list[int]:
    """Greedy DSatur graph colouring; returns a colour index per vertex."""
    n = len(adjacency)
    colors = [-1] * n
    saturation: list[set[int]] = [set() for _ in range(n)]
    degree = [len(a) for a in adjacency]
    heap = [(0, -degree[v], v) for v in range(n)]
    heapq.heapify(heap)
    while heap:
        neg_sat, _, v = heapq.heappop(heap)
        if colors[v] >= 0 or -neg_sat != len(saturation[v]):
            continue  # stale heap entry
        used = saturation[v]
        c = 0
        while c in used:
            c += 1
        colors[v] = c
        for w in adjacency[v]:
            if colors[w] < 0 and c not in saturation[w]:
                saturation[w].add(c)
                heapq.heappush(heap, (-len(saturation[w]), -degree[w], w))
    return colors


def _relabel_by_size(colors: list[int]) -> list[int]:
    """Renumbers groups so that group 0 is the largest one."""
    if not colors:
        return colors
    counts = np.bincount(colors)
    order = sorted(range(len(counts)), key=lambda c: (-counts[c], c))
    rank = {c: k for k, c in enumerate(order)}
    return [rank[c] for c in colors]


def _balance(colors: list[int], adjacency: list[set[int]], rounds: int = 4) -> list[int]:
    """Moves vertices from large groups to small ones when that keeps the
    colouring valid, to even out group sizes."""
    if not colors:
        return colors
    k = max(colors) + 1
    colors = list(colors)
    for _ in range(rounds):
        moved = False
        sizes = np.bincount(colors, minlength=k)
        for v in sorted(range(len(colors)), key=lambda u: -sizes[colors[u]]):
            sizes = np.bincount(colors, minlength=k)
            current = colors[v]
            forbidden = {colors[w] for w in adjacency[v]}
            options = [c for c in range(k) if c not in forbidden and sizes[c] + 1 < sizes[current]]
            if options:
                colors[v] = min(options, key=lambda c: sizes[c])
                moved = True
        if not moved:
            break
    return colors


def decompose_points(
    points: Sequence[Sequence[float]] | np.ndarray,
    *,
    min_distance: float,
    method: str = "greedy",
) -> list[int]:
    """Splits a point set into groups such that points within the same group
    are at least ``min_distance`` apart.

    ``greedy`` minimises the number of groups; ``balanced`` additionally
    evens out the group sizes.
    """
    pts = as_points(points)
    adjacency = _conflict_graph(pts, float(min_distance))
    colors = _dsatur(adjacency)
    if method == "balanced":
        colors = _balance(colors, adjacency)
    elif method != "greedy":
        raise ValueError(f"unknown decomposition method: {method!r}")
    return _relabel_by_size(colors)


def plan_takeoff(
    points: Sequence[Sequence[float]] | np.ndarray,
    *,
    min_distance: float,
    downwash_radius: float | None = None,
) -> list[int]:
    """Groups takeoff positions into waves for a layered takeoff.

    Drones of the same wave are at least ``min_distance`` apart horizontally,
    and also further apart than ``downwash_radius`` if given, so that no drone
    of a wave flies in the downwash column of another drone of the same wave.
    """
    pts = as_points(points)
    horizontal = np.column_stack([pts[:, 0], pts[:, 1]]) if len(pts) else np.zeros((0, 2))
    radius = max(float(min_distance), float(downwash_radius or 0.0))
    colors = _dsatur(_conflict_graph(horizontal, radius))
    return _relabel_by_size(colors)
