"""Skybrush-like storyboard workflow with 500 drones (background Blender).

blender --background --factory-startup --python blender/tests/test_storyboard_500.py
"""

import sys
import tempfile
import time
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import murmura_blender  # noqa: E402
from murmura_blender import i18n  # noqa: E402
from murmura_blender import scene as sc  # noqa: E402
from murmura_blender.core import engine  # noqa: E402

N = 500


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def select_only(*objects):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def points_object(name, points, colors=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(np.asarray(points).tolist(), [], [])
    if colors is not None:  # like Pointille: linear float colours in "drone_color"
        attr = mesh.color_attributes.new("drone_color", "FLOAT_COLOR", "POINT")
        rgba = np.column_stack([colors, np.ones(len(points))])
        attr.data.foreach_set("color_srgb", rgba.ravel())
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def textured_plane():
    """A 40x40 m vertical plane: left half red, right half blue (image texture)."""
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 60), rotation=(np.pi / 2, 0, 0))
    plane = bpy.context.active_object
    image = bpy.data.images.new("halves", 64, 64)
    pixels = np.zeros((64, 64, 4), dtype=np.float32)
    pixels[:, :32] = (1, 0, 0, 1)
    pixels[:, 32:] = (0, 0, 1, 1)
    image.pixels.foreach_set(pixels.ravel())
    mat = bpy.data.materials.new("Halves")
    tree = mat.node_tree
    bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    plane.data.materials.append(mat)
    return plane


def main():
    i18n.set_override("ru")
    murmura_blender.register()
    ctx = bpy.context
    scene = ctx.scene
    scene.render.fps = 24
    s = scene.murmura
    s.drone_count, s.grid_spacing, s.drone_size = N, 3.0, 0.6
    bpy.ops.murmura.create_drones()
    drones = sc.get_drones(ctx)
    check(abs(drones[0].scale[0] - 1.2) < 1e-6, "drone size applied")

    # formation 1: half of a sphere's vertices picked in Edit Mode
    sphere = points_object("Ball", engine.formations.sphere(2 * N, radius=40, center=(0, 0, 60)))
    select_only(sphere)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(sphere.data)
    for i, v in enumerate(bm.verts):
        v.select = i % 2 == 0
    bmesh.update_edit_mesh(sphere.data)
    check(bpy.ops.murmura.add_selection() == {"FINISHED"}, "formation from selected vertices")
    bpy.ops.object.mode_set(mode="OBJECT")
    entry = s.storyboard[-1]
    check(entry.source == "VERTEX_GROUP" and entry.vertex_group, "stored as a vertex group")

    # formation 2: Pointille-style points with their own colours
    disc = engine.formations.disc(N, radius=45, center=(0, 0, 60))
    colors = np.tile([0.0, 1.0, 0.0], (N, 1))
    pts = points_object("Disc_points", disc, colors)
    select_only(pts)
    bpy.ops.murmura.add_selection()

    # formation 3: dronegen-style points (no colours) lit by the textured parent object
    plane = textured_plane()
    grid = engine.formations.grid(N, spacing=2.4, columns=25)
    grid[:, 2] = 0
    flat = np.column_stack([grid[:, 0], np.zeros(N), grid[:, 1] + 60])
    pts2 = points_object("Plane_points", flat)
    pts2.parent = plane
    pts2.matrix_parent_inverse = plane.matrix_world.inverted()
    select_only(pts2)
    bpy.ops.murmura.add_selection()

    # formation 4: only a group of drones flies, the others wait
    select_only(*drones[:100])
    bpy.ops.murmura.group_add()
    sub = engine.formations.circle(100, radius=36, center=(0, 60, 80), plane="xy")
    ring = points_object("Ring", sub)
    select_only(ring)
    bpy.ops.murmura.add_selection()
    s.storyboard[-1].group = s.groups[0].name
    s.storyboard[-1].effect = "solid"

    for e in s.storyboard:
        e.hold = 3.0
    check(len(s.storyboard) == 4, "four formations in the storyboard (no takeoff / landing yet)")

    started = time.perf_counter()
    check(bpy.ops.murmura.recalculate() == {"FINISHED"}, "recalculated")
    print(f"     recalculate: {time.perf_counter() - started:.1f} s")
    for line in s.report:
        print("     ", "OK " if line.ok else "!! ", line.text)
    check(
        any("автоматически" in line.text for line in s.report),
        "takeoff / landing added automatically",
    )
    check(all(line.ok for line in s.report if line.text.startswith("[")), "safety check passed")

    def colours_at(entry_index):
        e = s.storyboard[entry_index]
        scene.frame_set(e.frame_end - 2)
        return np.array([o.color[:3] for o in drones]) * 255, np.array(
            [tuple(o.matrix_world.translation) for o in drones]
        )

    col, _ = colours_at(1)
    check(
        np.median(col[:, 1]) > 200 and np.median(col[:, 0]) < 50, "Pointille colours (green) used"
    )
    col, pos = colours_at(2)
    left = pos[:, 0] < -2
    right = pos[:, 0] > 2
    check(
        np.median(col[left, 0]) > 200 and np.median(col[right, 2]) > 200,
        "texture colours: red left, blue right",
    )
    col, pos = colours_at(3)
    group = np.array([o.name in s.groups[0].names() for o in drones])
    check(np.allclose(pos[group, 2], 80, atol=0.01), "the group flew into the ring")
    check(not np.any(np.isclose(pos[~group, 2], 80, atol=0.01)), "the other drones stayed put")

    # paint a few drones in the ring scene and recalculate
    s.storyboard_index = 3
    scene.frame_set(s.storyboard[3].frame_end - 2)
    select_only(*drones[:10])
    s.paint_color = (1.0, 0.0, 1.0)
    check(bpy.ops.murmura.paint() == {"FINISHED"}, "painted 10 drones")
    bpy.ops.murmura.recalculate()
    col, _ = colours_at(3)
    check(np.allclose(col[:10], [255, 0, 255], atol=2), "painted colour survives recalculation")

    # reorder: move the ring scene to the top and recalculate
    s.storyboard_index = 3
    for _ in range(3):
        bpy.ops.murmura.storyboard_move(direction="UP")
    check(s.storyboard[0].name == "Ring", "entry moved up")
    check(bpy.ops.murmura.recalculate() == {"FINISHED"}, "recalculated after reordering")
    for line in s.report:
        print("     ", "OK " if line.ok else "!! ", line.text)

    out = Path(tempfile.gettempdir()) / "storyboard-500.skyc"
    s.sample_fps = 4
    started = time.perf_counter()
    check(bpy.ops.murmura.export_skyc(filepath=str(out), validate=True) == {"FINISHED"}, "exported")
    print(f"     export: {time.perf_counter() - started:.1f} s")
    check(all(line.ok for line in s.report), "exported show passes the safety check")
    murmura_blender.unregister()
    print("STORYBOARD TEST PASSED")


try:
    main()
except Exception:
    traceback.print_exc()
    print("STORYBOARD TEST FAILED")
    sys.exit(1)
