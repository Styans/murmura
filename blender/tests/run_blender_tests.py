"""End-to-end test of the add-on inside Blender (no UI needed).

    blender --background --factory-startup --python blender/tests/run_blender_tests.py -- [addon.zip]

Without an argument the add-on is loaded from the repository; with a zip
built by ``blender/build_addon.py`` the packaged add-on (and its bundled
engine) is tested instead. Blender's own Python has no SciPy, so this also
exercises the NumPy fallbacks of the engine.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from types import SimpleNamespace

import bpy
import numpy as np

REPO = Path(__file__).resolve().parents[2]
ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
WORK = Path(tempfile.mkdtemp(prefix="murmura-blender-test-"))


def load_addon():
    if ARGS:
        target = WORK / "addon" / "murmura_blender"
        with zipfile.ZipFile(ARGS[0]) as zf:
            zf.extractall(target)
        sys.path.insert(0, str(target.parent))
    else:
        sys.path.insert(0, str(REPO / "blender"))
    addon = importlib.import_module("murmura_blender")
    addon.register()
    return addon


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


class LayoutProbe:
    """Stands in for ``UILayout`` and verifies every property and operator
    a panel refers to, since panels are not drawn in background mode."""

    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        if name in {"row", "column", "box", "split", "column_flow", "grid_flow"}:
            return lambda *a, **k: LayoutProbe(self.log)
        if name == "prop":
            return self._prop
        if name == "operator":
            return self._operator
        if name == "template_list":
            return self._template_list
        return lambda *a, **k: None

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def _prop(self, data, name, **kwargs):
        if name not in data.bl_rna.properties:
            raise AssertionError(f"panel refers to unknown property {name!r}")
        self.log.append(name)

    def _operator(self, idname, **kwargs):
        module, op = idname.split(".")
        if not hasattr(getattr(bpy.ops, module), op):
            raise AssertionError(f"panel refers to unknown operator {idname!r}")
        self.log.append(idname)
        return type("Props", (), {})()

    def _template_list(self, list_type, list_id, data, prop, active_data, active_prop, **kwargs):
        for name in (prop,):
            assert name in data.bl_rna.properties, name
        assert active_prop in active_data.bl_rna.properties, active_prop


def check_languages(addon, ctx):
    from murmura_blender import i18n, ops, ops_story, props

    s = ctx.scene.murmura
    names_before = [e.name for e in s.storyboard]

    i18n.set_override("en")
    addon.reload_language()
    entry_rna = props.MURMURA_StoryboardEntry.bl_rna
    check(
        ops_story.MURMURA_OT_recalculate.bl_label == "Recalculate Show", "English operator labels"
    )
    check(entry_rna.properties["hold"].name == "Hold", "English property names")

    i18n.set_override("ru")
    addon.reload_language()
    entry_rna = props.MURMURA_StoryboardEntry.bl_rna
    check(ops_story.MURMURA_OT_recalculate.bl_label == "Пересчитать шоу", "Russian operator labels")
    check(entry_rna.properties["hold"].name == "Удержание", "Russian property names")
    check(
        entry_rna.properties["effect"].enum_items["rainbow"].name == "Радуга", "Russian enum items"
    )
    check(
        ops.MURMURA_OT_export_skyc.bl_description.startswith("Экспортировать"),
        "Russian tooltips",
    )
    s = ctx.scene.murmura
    check([e.name for e in s.storyboard] == names_before, "storyboard survives a language switch")

    for entry in s.storyboard:
        entry.motion = "none"
    bpy.ops.murmura.create_drones()
    check(bpy.ops.murmura.recalculate() == {"FINISHED"}, "show builds with the Russian interface")
    texts = [line.text for line in s.report]
    check(any(text.startswith("Собрано за") for text in texts), "Russian report headline")
    check(any("Мин. дистанция в воздухе" in text for text in texts), "Russian safety summary")
    check(any(m.name.endswith("Взлёт") for m in ctx.scene.timeline_markers), "Russian cue names")
    check_panels(ctx)

    i18n.set_override(None)
    addon.reload_language()


def check_panels(ctx):
    from murmura_blender import props, ui

    s = ctx.scene.murmura
    if not len(s.storyboard):
        s.storyboard.add()
    drawn: list[str] = []
    for shape, *_ in props.SHAPES:
        s.shape = shape
        for effect, *_ in props.EFFECTS:
            s.storyboard[0].effect = effect
            for motion in ("none", "rotate"):
                s.storyboard[0].motion = motion
                for cls in ui.CLASSES:
                    if issubclass(cls, bpy.types.Panel):
                        cls.draw(SimpleNamespace(layout=LayoutProbe(drawn)), ctx)
    check(len(drawn) > 100, f"all panels draw for every shape / effect ({len(set(drawn))} widgets)")


def main():
    started = time.perf_counter()
    addon = load_addon()
    from murmura_blender import scene as sc
    from murmura_blender.core import engine

    print("engine:", engine.__file__, "scipy:", engine._compat.HAVE_SCIPY)
    ctx = bpy.context
    scene = ctx.scene
    scene.render.fps = 24
    s = scene.murmura

    # drones
    s.drone_count, s.grid_spacing = 16, 3.0
    bpy.ops.murmura.create_drones()
    drones = sc.get_drones(ctx)
    check(len(drones) == 16, "16 drones created")
    check(drones[0].active_material.name == sc.LED_MATERIAL, "drones use the LED material")

    # formations
    s.shape, s.size, s.center = "circle", 9.0, (0, 0, 20)
    bpy.ops.murmura.add_formation()
    ring = ctx.active_object
    s.shape, s.text, s.size = "text", "МИР", 8.0
    bpy.ops.murmura.add_formation()
    word = ctx.active_object
    s.shape, s.size, s.filepath = "svg", 22.0, str(REPO / "examples" / "logo.svg")
    bpy.ops.murmura.add_formation()
    logo = ctx.active_object
    check(
        len(ring.data.vertices) == 16 and len(word.data.vertices) == 16,
        "formations have one point per drone",
    )
    check(
        logo.data.color_attributes.get(sc.COLOR_ATTRIBUTE) is not None,
        "SVG colours stored on the formation",
    )
    sphere = bpy.data.meshes.new("Big sphere")
    sphere.from_pydata(engine.formations.sphere(60, radius=8, center=(0, 0, 25)).tolist(), [], [])
    big = bpy.data.objects.new("Big sphere", sphere)
    scene.collection.objects.link(big)

    # storyboard
    for obj in (ring, word, logo, big):
        for other in ctx.view_layer.objects:
            other.select_set(False)
        obj.select_set(True)
        ctx.view_layer.objects.active = obj
        bpy.ops.murmura.add_selection()
    sb = s.storyboard
    sb[0].effect, sb[0].motion, sb[0].motion_rate, sb[0].hold = "rainbow", "rotate", 2.0, 6.0
    sb[1].effect, sb[1].color, sb[1].hold = "pulse", (1.0, 0.1, 0.3), 4.0
    sb[2].effect, sb[2].hold = "object", 4.0
    sb[3].effect, sb[3].hold = "wave", 4.0
    check(len(sb) == 4 and sb[3].target == big, "storyboard has 4 entries")

    # build
    t0 = time.perf_counter()
    result = bpy.ops.murmura.recalculate()
    print(f"  build took {time.perf_counter() - t0:.1f} s")
    check(result == {"FINISHED"}, "show built")
    for line in s.report:
        print("     ", "OK " if line.ok else "!! ", line.text)
    check(
        all(line.ok for line in s.report if "[" in line.text), "built show passes the safety check"
    )
    markers = [m.name for m in scene.timeline_markers]
    check(any("МИР" in m for m in markers), "cues added as timeline markers")
    fps = scene.render.fps
    end_time = (scene.frame_end - scene.frame_start) / fps
    check(end_time > 30, f"frame range covers the show ({end_time:.1f} s)")

    ad = drones[0].animation_data
    check(ad is not None and ad.action is not None, "drones are animated")

    # export, read back and compare with Blender's own evaluation
    path = WORK / "blender-show.skyc"
    s.sample_fps = 12.0
    result = bpy.ops.murmura.export_skyc(filepath=str(path), validate=True)
    check(result == {"FINISHED"} and path.exists(), "exported .skyc")
    show = engine.read_skyc(path)
    check(show.num_drones == 16, "exported show has 16 drones")
    times, pos, col = sc.sample_drones(ctx, drones, fps=24)
    worst = max(
        float(np.max(np.linalg.norm(d.trajectory.position_at(times) - pos[:, j], axis=1)))
        for j, d in enumerate(show.drones)
    )
    check(
        worst < 0.06, f"exported trajectories follow the animation (max error {worst * 100:.1f} cm)"
    )
    st, _, scol = sc.sample_drones(ctx, drones, fps=s.sample_fps)

    # light key times are stored in 1/50 s frames: allow that much time shift
    def light_error(d, j):
        shifted = [
            np.abs(d.lights.color_at(st + dt) - scol[:, j]).max(axis=1) for dt in (-0.01, 0.0, 0.01)
        ]
        return float(np.max(np.min(shifted, axis=0)))

    cerr = max(light_error(d, j) for j, d in enumerate(show.drones))
    check(cerr <= 4, f"exported lights match the sampled colours (max deviation {cerr:.0f}/255)")

    result = bpy.ops.murmura.validate()
    check(result == {"FINISHED"}, "validate operator runs")

    # import the show back into a fresh set of drones
    bpy.ops.murmura.clear_animation()
    result = bpy.ops.murmura.import_skyc(filepath=str(path))
    check(result == {"FINISHED"}, "imported .skyc")
    drones = sc.get_drones(ctx)
    times2, pos2, _ = sc.sample_drones(ctx, drones, fps=24)
    err = max(
        float(np.max(np.linalg.norm(d.trajectory.position_at(times2) - pos2[:, j], axis=1)))
        for j, d in enumerate(show.drones)
    )
    check(
        err < 0.005,
        f"imported Bezier keyframes reproduce the file exactly (max error {err * 1000:.1f} mm)",
    )

    # an existing user show, if available
    user_show = Path.home() / "Documents" / "blend" / "test12.skyc"
    if user_show.exists():
        result = bpy.ops.murmura.import_skyc(filepath=str(user_show))
        check(result == {"FINISHED"}, f"imported {user_show.name}")

    csv_path = WORK / "show.zip"
    check(
        bpy.ops.murmura.export_csv(filepath=str(csv_path)) == {"FINISHED"} and csv_path.exists(),
        "CSV export",
    )

    check_panels(ctx)
    check_languages(addon, ctx)

    addon.unregister()
    print(f"ALL BLENDER TESTS PASSED in {time.perf_counter() - started:.1f} s")


try:
    main()
except Exception:
    traceback.print_exc()
    print("BLENDER TESTS FAILED")
    sys.exit(1)
