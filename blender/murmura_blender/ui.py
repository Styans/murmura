"""Sidebar panels (View3D > Sidebar > Murmura)."""

import bpy

from . import bl_info
from . import scene as sc
from .i18n import localize, tr
from .prefs import preferences

ADDON_VERSION = ".".join(map(str, bl_info["version"]))

KIND_ICONS = {
    "TAKEOFF": "TRIA_UP_BAR",
    "FORMATION": "OUTLINER_OB_POINTCLOUD",
    "LAND": "TRIA_DOWN_BAR",
}


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Murmura"


def _drone_count() -> int:
    # cheap on every redraw: no sorting, no scene evaluation
    coll = bpy.data.collections.get(sc.DRONES_COLLECTION)
    return len(coll.all_objects) if coll is not None else 0


class MURMURA_UL_groups(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="GROUP")
        row.label(text=str(len(item.names())))


class MURMURA_PT_swarm(_Panel, bpy.types.Panel):
    bl_label = "Swarm"
    bl_idname = "MURMURA_PT_swarm"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        prefs = preferences()
        layout.label(text=f"Murmura {ADDON_VERSION}")
        if prefs is not None:
            layout.prop(prefs, "language", text=tr("Language"))
        count = _drone_count()
        layout.label(
            text=tr("{count} drones in the scene", count=count) if count else tr("No drones yet"),
            icon="LIGHT_POINT",
        )
        col = layout.column(align=True)
        col.prop(s, "drone_count")
        col.prop(s, "grid_spacing")
        col.prop(s, "grid_columns")
        col.prop(s, "drone_size")
        layout.operator("murmura.create_drones", icon="ADD")
        row = layout.row(align=True)
        row.operator("murmura.select_drones", icon="RESTRICT_SELECT_OFF")
        row.operator("murmura.clear_animation", text=tr("Clear Animation"), icon="X")

        layout.label(text=tr("Drone groups"), icon="GROUP")
        row = layout.row()
        row.template_list("MURMURA_UL_groups", "", s, "groups", s, "group_index", rows=3)
        col = row.column(align=True)
        col.operator("murmura.group_add", text="", icon="ADD")
        col.operator("murmura.group_remove", text="", icon="REMOVE")
        row = layout.row(align=True)
        row.operator("murmura.group_assign", text=tr("Add"), icon="ADD").action = "ADD"
        row.operator("murmura.group_assign", text=tr("Remove"), icon="REMOVE").action = "REMOVE"
        row.operator("murmura.group_select", text=tr("Select"), icon="RESTRICT_SELECT_OFF")


SOURCE_ICONS = {
    "OBJECT": "OBJECT_DATA",
    "VERTEX_GROUP": "GROUP_VERTEX",
    "COLLECTION": "OUTLINER_COLLECTION",
}


class MURMURA_PT_formations(_Panel, bpy.types.Panel):
    bl_label = "Formations"
    bl_idname = "MURMURA_PT_formations"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        col = layout.column(align=True)
        col.label(text=tr("1. Select an object, several objects,"), icon="RESTRICT_SELECT_OFF")
        col.label(text=tr("   a collection or vertices (Tab)."))
        col.label(text=tr("2. Press the button - drones will fly to its points."))
        big = layout.row()
        big.scale_y = 1.6
        big.operator("murmura.add_selection", text=tr("Add Selected as Formation"), icon="ADD")
        formations = [e for e in s.storyboard if e.kind == "FORMATION"]
        if formations:
            box = layout.box()
            for e in formations:
                box.label(text=e.name, icon=SOURCE_ICONS.get(e.source, "DOT"))
            layout.label(text=tr("Order, timing and lights: Storyboard."), icon="INFO")


class MURMURA_PT_shape_generator(_Panel, bpy.types.Panel):
    bl_label = "Generate Shape Mesh"
    bl_idname = "MURMURA_PT_shape_generator"
    bl_parent_id = "MURMURA_PT_formations"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        layout.label(text=tr("Creates a new mesh; then add it as a formation."), icon="INFO")
        layout.prop(s, "shape")
        col = layout.column(align=True)
        if s.shape == "text":
            col.prop(s, "text")
        if s.shape in {"svg", "image"}:
            col.prop(s, "filepath")
        col.prop(s, "size", text=tr("Height") if s.shape == "text" else tr("Size"))
        if s.shape not in {"sphere", "cube", "torus", "helix", "grid"}:
            col.prop(s, "plane")
        layout.prop(s, "center")
        layout.prop(s, "auto_scale")
        layout.operator("murmura.add_formation", icon="MESH_DATA")


class MURMURA_UL_storyboard(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon=KIND_ICONS.get(item.kind, "DOT"))
        if item.frame_end:
            row.label(text=f"{item.frame_start}-{item.frame_end}")


def _draw_entry(layout, s, entry):
    box = layout.box()
    box.prop(entry, "kind")
    if entry.kind == "TAKEOFF":
        col = box.column(align=True)
        col.prop(entry, "altitude")
        col.prop(entry, "climb_speed")
        col.prop(entry, "layered")
        row = col.row(align=True)
        row.prop(entry, "use_start")
        sub = row.row()
        sub.enabled = entry.use_start
        sub.prop(entry, "start", text="")
        return
    if entry.kind == "LAND":
        box.prop(entry, "land_on")
        box.label(text=tr("Speeds and spin-down: Safety tab."), icon="INFO")
        return

    box.prop(entry, "source")
    if entry.source == "COLLECTION":
        box.prop(entry, "collection")
    else:
        box.prop(entry, "target")
        if (
            entry.source == "VERTEX_GROUP"
            and entry.target is not None
            and entry.target.type == "MESH"
        ):
            box.prop_search(entry, "vertex_group", entry.target, "vertex_groups")
    box.prop_search(entry, "group", s, "groups", icon="GROUP")
    col = box.column(align=True)
    col.prop(entry, "hold")
    col.prop(entry, "transition")
    row = col.row(align=True)
    row.prop(entry, "use_start")
    sub = row.row()
    sub.enabled = entry.use_start
    sub.prop(entry, "start", text="")

    box.prop(entry, "effect")
    col = box.column(align=True)
    if entry.effect == "object":
        col.prop(entry, "color_object")
        col.prop(entry, "min_brightness")
        col.prop(entry, "color", text=tr("Colour if none"))
    if entry.effect in {"solid", "pulse", "gradient", "wave", "sparkle", "fade"}:
        col.prop(entry, "color")
    if entry.effect in {"gradient", "wave", "sparkle", "fade"}:
        col.prop(entry, "color2")
    if entry.effect in {"rainbow", "pulse", "wave", "fade"}:
        col.prop(entry, "period")
    if entry.effect in {"gradient", "rainbow", "wave"}:
        col.prop(entry, "axis")
    row = box.row(align=True)
    row.prop(entry, "motion")
    if entry.motion != "none":
        row.prop(entry, "motion_rate")
    if len(entry.overrides):
        box.label(
            text=tr("Painted drone sets: {count}", count=len(entry.overrides)), icon="BRUSH_DATA"
        )


class MURMURA_PT_storyboard(_Panel, bpy.types.Panel):
    bl_label = "Storyboard"
    bl_idname = "MURMURA_PT_storyboard"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        row = layout.row(align=True)
        row.operator("murmura.add_takeoff", text=tr("Takeoff"), icon="TRIA_UP_BAR")
        row.operator("murmura.add_selection", text=tr("Formation"), icon="ADD")
        row.operator("murmura.add_landing", text=tr("Landing"), icon="TRIA_DOWN_BAR")
        layout.label(
            text=tr("Formation: select vertices (Tab) or objects, then press +."), icon="INFO"
        )

        row = layout.row()
        row.template_list(
            "MURMURA_UL_storyboard", "", s, "storyboard", s, "storyboard_index", rows=6
        )
        col = row.column(align=True)
        col.operator("murmura.storyboard_remove", text="", icon="REMOVE")
        col.operator("murmura.storyboard_duplicate", text="", icon="DUPLICATE")
        col.separator()
        col.operator("murmura.storyboard_move", text="", icon="TRIA_UP").direction = "UP"
        col.operator("murmura.storyboard_move", text="", icon="TRIA_DOWN").direction = "DOWN"
        col.separator()
        col.operator("murmura.storyboard_jump", text="", icon="TIME")

        if 0 <= s.storyboard_index < len(s.storyboard):
            _draw_entry(layout, s, s.storyboard[s.storyboard_index])

        big = layout.row()
        big.scale_y = 1.6
        big.operator("murmura.recalculate", icon="PLAY")

        layout.label(text=tr("Paint"), icon="BRUSH_DATA")
        row = layout.row(align=True)
        row.prop(s, "paint_color", text="")
        row.operator("murmura.paint", text=tr("Paint Selected"))
        row.operator("murmura.paint_clear", text="", icon="X")


class MURMURA_PT_safety(_Panel, bpy.types.Panel):
    bl_label = "Safety"
    bl_idname = "MURMURA_PT_safety"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, "min_distance")
        col.prop(s, "max_velocity_xy")
        col.prop(s, "max_velocity_z")
        col.prop(s, "max_velocity_z_up")
        col.prop(s, "max_acceleration")
        col.prop(s, "max_altitude")
        col.prop(s, "min_nav_altitude")
        col = layout.column(align=True)
        col.prop(s, "tempo", slider=True)
        col.prop(s, "landing_velocity")
        col.prop(s, "spindown")
        col.prop(s, "staging_spread")
        row = layout.row(align=True)
        row.operator("murmura.validate", icon="CHECKMARK")
        row.operator("murmura.goto_violation", text="", icon="VIEWZOOM")


class MURMURA_PT_export(_Panel, bpy.types.Panel):
    bl_label = "Export"
    bl_idname = "MURMURA_PT_export"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, "show_title")
        col.prop(s, "sample_fps")
        col.prop(s, "light_fps")
        col.prop(s, "fit_tolerance")
        big = layout.row()
        big.scale_y = 1.4
        big.operator("murmura.export_skyc", icon="EXPORT")
        row = layout.row(align=True)
        row.operator("murmura.export_csv", text=tr("CSV"), icon="FILE")
        row.operator("murmura.import_skyc", icon="IMPORT")
        row.operator("murmura.preview", icon="HIDE_OFF")


class MURMURA_PT_report(_Panel, bpy.types.Panel):
    bl_label = "Report"
    bl_idname = "MURMURA_PT_report"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.murmura.report) > 0

    def draw(self, context):
        s = context.scene.murmura
        col = self.layout.column(align=True)
        for line in s.report:
            col.label(text=line.text, icon="CHECKMARK" if line.ok else "ERROR")


CLASSES = (
    MURMURA_UL_groups,
    MURMURA_UL_storyboard,
    MURMURA_PT_swarm,
    MURMURA_PT_formations,
    MURMURA_PT_shape_generator,
    MURMURA_PT_storyboard,
    MURMURA_PT_safety,
    MURMURA_PT_export,
    MURMURA_PT_report,
)


def register():
    for cls in CLASSES:
        localize(cls)
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
