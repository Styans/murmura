"""Imports a large .skyc into Blender, exports it again and prints timings.

blender --background --factory-startup --python blender/tests/bench_large_show.py -- show.skyc
"""

import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import murmura_blender  # noqa: E402
from murmura_blender import scene as sc  # noqa: E402
from murmura_blender.core import engine  # noqa: E402


def main(source: str) -> None:
    murmura_blender.register()
    ctx = bpy.context

    started = time.perf_counter()
    bpy.ops.murmura.import_skyc(filepath=source)
    count = len(sc.get_drones(ctx))
    print(f"import: {count} drones in {time.perf_counter() - started:.1f} s")

    ctx.scene.murmura.sample_fps = 4.0
    target = Path(tempfile.gettempdir()) / "murmura-bench.skyc"
    started = time.perf_counter()
    bpy.ops.murmura.export_skyc(filepath=str(target), validate=False)
    size = target.stat().st_size // 1024
    print(f"export at 4 fps: {time.perf_counter() - started:.1f} s, {size} KiB")

    original, exported = engine.read_skyc(source), engine.read_skyc(target)
    times = np.linspace(0, original.end_time, 400)
    error = max(
        float(
            np.max(
                np.linalg.norm(
                    a.trajectory.position_at(times) - b.trajectory.position_at(times), axis=1
                )
            )
        )
        for a, b in zip(original.drones, exported.drones)
    )
    print(f"re-export deviation from the original file: {error * 100:.1f} cm")
    murmura_blender.unregister()


main(sys.argv[sys.argv.index("--") + 1])
