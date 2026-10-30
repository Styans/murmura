"""CSV export / import (one CSV per drone, bundled in a ZIP archive).

Each file is named ``<drone name>.csv`` and has the columns::

    Time [msec],x [m],y [m],z [m],Red,Green,Blue
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import numpy as np

from .lights import LightKeyframe, LightProgram
from .model import Drone, Show
from .skyc import _safe_name
from .trajectory import Trajectory
from .utils import natural_key

__all__ = ("HEADER", "read_csv_zip", "write_csv_zip")

HEADER = ["Time [msec]", "x [m]", "y [m]", "z [m]", "Red", "Green", "Blue"]


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def write_csv_zip(show: Show, *, fps: float = 4.0, light_fps: float | None = None) -> bytes:
    """Samples every drone at ``fps`` and returns a ZIP of CSV files."""
    end = max(show.end_time, max((d.lights.end_time for d in show.drones), default=0.0))
    times = np.arange(0.0, end + 1e-9, 1.0 / fps)
    if len(times) == 0 or times[-1] < end - 1e-9:
        times = np.append(times, end)
    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for drone in show.drones:
            name = _safe_name(drone.name)
            base, k = name, 2
            while name.lower() in used:
                name, k = f"{base}_{k}", k + 1
            used.add(name.lower())
            pos = (
                drone.trajectory.position_at(times)
                if drone.trajectory
                else np.zeros((len(times), 3))
            )
            col = drone.lights.color_at(times).round().astype(int)
            out = io.StringIO()
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(HEADER)
            for t, p, c in zip(times, pos, col):
                writer.writerow(
                    [int(round(t * 1000)), _fmt(p[0]), _fmt(p[1]), _fmt(p[2]), *c.tolist()]
                )
            zf.writestr(f"{name}.csv", out.getvalue())
    return buffer.getvalue()


def _read_one(name: str, text: str, *, tolerance: float, simplify: bool) -> Drone:
    rows = list(csv.reader(io.StringIO(text)))
    if rows and not _is_number(rows[0][0]):
        rows = rows[1:]
    data = np.array(
        [[float(v) for v in row[:7]] for row in rows if len(row) >= 4 and row[0].strip()],
        dtype=float,
    )
    if data.ndim != 2 or len(data) == 0:
        raise ValueError(f"CSV file {name!r} contains no samples")
    times = data[:, 0] / 1000.0
    positions = data[:, 1:4]
    if simplify:
        traj = Trajectory.from_samples(times, positions, tolerance=tolerance)
    else:
        traj = Trajectory().start_at(times[0], positions[0])
        for t, p in zip(times[1:], positions[1:]):
            if t > traj.end_time:
                traj.line_to(t, p)
    lights = LightProgram()
    if data.shape[1] >= 7:
        keyframes = [
            LightKeyframe(float(t), tuple(int(v) for v in c), True)
            for t, c in zip(times, data[:, 4:7])
        ]  # type: ignore[arg-type]
        lights = LightProgram(keyframes).simplified()
    return Drone(name=name, trajectory=traj, lights=lights)


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def read_csv_zip(
    source: str | Path | bytes,
    *,
    title: str = "Imported show",
    tolerance: float = 0.03,
    simplify: bool = True,
) -> Show:
    """Reads a ZIP of per-drone CSV files (or a directory of them)."""
    files: list[tuple[str, str]] = []
    if isinstance(source, (str, Path)) and Path(source).is_dir():
        for path in sorted(Path(source).glob("*.csv")):
            files.append((path.stem, path.read_text(encoding="utf-8-sig")))
    else:
        data = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.filename.lower().endswith(".csv") and not info.is_dir():
                    stem = info.filename.rsplit("/", 1)[-1][:-4]
                    files.append((stem, zf.read(info).decode("utf-8-sig")))
    if not files:
        raise ValueError("no CSV files found")
    files.sort(key=lambda f: natural_key(f[0]))
    drones = [_read_one(name, text, tolerance=tolerance, simplify=simplify) for name, text in files]
    return Show(drones=drones, title=title)
