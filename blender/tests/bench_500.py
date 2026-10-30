"""Times every add-on step with 500 drones (background Blender).

blender --background --factory-startup --python blender/tests/bench_500.py
"""

import cProfile
import pstats
import sys
import tempfile
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import murmura_blender  # noqa: E402
from murmura_blender.core import engine  # noqa: E402


def timed(label, fn):
    started = time.perf_counter()
    profiler = cProfile.Profile()
    result = profiler.runcall(fn)
    elapsed = time.perf_counter() - started
    print(f"{label}: {elapsed:.1f} s -> {result}")
    if elapsed > 3:
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(12)
    return result


def main():
    murmura_blender.register()
    ctx = bpy.context
    s = ctx.scene.murmura
    s.drone_count, s.grid_spacing = 500, 3.0
    timed("create drones", bpy.ops.murmura.create_drones)
    pts = engine.formations.sphere(500, radius=30, center=(0, 0, 50))
    mesh = bpy.data.meshes.new("Ball")
    mesh.from_pydata(pts.tolist(), [], [])
    obj = bpy.data.objects.new("Ball", mesh)
    ctx.scene.collection.objects.link(obj)
    ctx.view_layer.objects.active = obj
    bpy.ops.murmura.storyboard_add()
    timed("build show", bpy.ops.murmura.build_show)
    for line in s.report:
        print("   ", line.text)
    out = Path(tempfile.gettempdir()) / "bench500.skyc"
    s.sample_fps = 8
    timed("export", lambda: bpy.ops.murmura.export_skyc(filepath=str(out), validate=True))


main()
