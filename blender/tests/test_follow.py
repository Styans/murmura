"""Drones following the vertices of an animated model (background Blender).

blender --background --factory-startup --python blender/tests/test_follow.py
"""

import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import murmura_blender  # noqa: E402
from murmura_blender import scene as sc  # noqa: E402
from murmura_blender import storyboard  # noqa: E402
from murmura_blender.core import engine  # noqa: E402

N = 24


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def vertices(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    mesh = obj.evaluated_get(deps).to_mesh()
    co = np.array([tuple(obj.matrix_world @ v.co) for v in mesh.vertices])
    obj.evaluated_get(deps).to_mesh_clear()
    return co


def main():
    murmura_blender.register()
    ctx = bpy.context
    scene = ctx.scene
    scene.render.fps = 24
    s = scene.murmura
    s.drone_count, s.grid_spacing = N, 3.0
    bpy.ops.murmura.create_drones()
    drones = sc.get_drones(ctx)

    # a ring of points that moves sideways and turns between frames 600 and 840
    ring = engine.formations.circle(N, radius=10, center=(0, 0, 0), plane="xy")
    mesh = bpy.data.meshes.new("Ring")
    mesh.from_pydata(ring.tolist(), [], [])
    obj = bpy.data.objects.new("Ring", mesh)
    scene.collection.objects.link(obj)
    obj.location = (0, 30, 25)
    obj.keyframe_insert("location", frame=600)
    obj.keyframe_insert("rotation_euler", frame=600)
    obj.location = (8, 30, 29)
    obj.rotation_euler = (0, 0, math.radians(30))
    obj.keyframe_insert("location", frame=840)
    obj.keyframe_insert("rotation_euler", frame=840)
    # ... and keeps drifting slowly while the drones go home
    obj.location = (20, 30, 29)
    obj.keyframe_insert("location", frame=2040)

    for o in ctx.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    ctx.view_layer.objects.active = obj
    bpy.ops.murmura.add_selection()
    entry = s.storyboard[-1]
    entry.follow = True
    entry.hold = 4.0

    # 1. automatic binding: from the arrival, for "hold" seconds
    check(bpy.ops.murmura.recalculate() == {"FINISHED"}, "recalculated with automatic binding")
    check(entry.follow_end - entry.follow_start == 96, "automatic binding lasts the hold time")
    names = [m.name for m in scene.timeline_markers]
    check(
        storyboard.START_MARK + entry.name in names and storyboard.END_MARK + entry.name in names,
        "binding start and end markers on the timeline",
    )

    # 2. the user drags the markers to the animated part
    scene.timeline_markers[storyboard.START_MARK + entry.name].frame = 600
    scene.timeline_markers[storyboard.END_MARK + entry.name].frame = 840
    check(bpy.ops.murmura.recalculate() == {"FINISHED"}, "recalculated after dragging the markers")
    check(
        (entry.follow_start, entry.follow_end) == (600, 840), "binding range taken from the markers"
    )
    check(entry.follow_manual, "dragged range is kept")
    for line in s.report:
        print("     ", "OK " if line.ok else "!! ", line.text)

    worst = 0.0
    for frame in (600, 660, 720, 780, 840):
        scene.frame_set(frame)
        target = vertices(obj)
        pos = np.array([tuple(d.matrix_world.translation) for d in drones])
        gap = np.linalg.norm(pos[:, None] - target[None], axis=2).min(axis=1)
        worst = max(worst, float(gap.max()))
    check(worst < 0.1, f"drones sit on the moving vertices (max {worst * 100:.1f} cm)")
    scene.frame_set(620)
    before = np.array([tuple(d.matrix_world.translation) for d in drones])
    scene.frame_set(820)
    after = np.array([tuple(d.matrix_world.translation) for d in drones])
    check(np.median(after[:, 0] - before[:, 0]) > 5, "the swarm moved with the model")
    check(all(line.ok for line in s.report if "[" in line.text), "safety check passed")

    # 3. during the return the drones still in the figure stay on the model
    landing = s.storyboard[-1] if s.storyboard[-1].kind == "LAND" else None
    check(entry.follow_until_leaving, "drones stay bound until they leave (default)")
    check(
        any("one by one" in line.text or "по одному" in line.text for line in s.report),
        "sakura petals return",
    )
    bound_late = 0
    for frame in range(900, 1300, 40):
        scene.frame_set(frame)
        target = vertices(obj)
        pos = np.array([tuple(d.matrix_world.translation) for d in drones])
        on = np.linalg.norm(pos[:, None] - target[None], axis=2).min(axis=1) < 0.1
        if 0 < on.sum() < N:
            bound_late += 1
    check(bound_late >= 2, f"drones not yet gone follow the moving model ({bound_late} checks)")
    del landing

    # 4. back to automatic
    bpy.ops.murmura.follow_auto()
    check(not entry.follow_manual, "binding back to the arrival")

    murmura_blender.unregister()
    print("FOLLOW TEST PASSED")


try:
    main()
except Exception:
    traceback.print_exc()
    print("FOLLOW TEST FAILED")
    sys.exit(1)
