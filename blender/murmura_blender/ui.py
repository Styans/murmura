"""Sidebar panels, organised like Skybrush Studio into three tabs:

* Murmura - drones and the show: storyboard of takeoff, formations, landing
* Murmura LEDs - lights of the selected storyboard entry, painting
* Murmura Export - safety limits, validation, export

Rarely used settings live in collapsed sub-panels.
"""

import bpy

from . import bl_info
from . import scene as sc
from .i18n import localize, tr

ADDON_VERSION = ".".join(map(str, bl_info["version"]))

TAB_SHOW = "Murmura"
TAB_LEDS = "Murmura LEDs"
TAB_EXPORT = "Murmura Export"

KIND_ICONS = {
    "TAKEOFF": "TRIA_UP_BAR",
    "FORMATION": "OUTLINER_OB_POINTCLOUD",
    "LAND": "TRIA_DOWN_BAR",
}


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = TAB_SHOW


def _split(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False
    return layout


def _drone_count() -> int:
    # cheap on every redraw: no sorting, no scene evaluation
    coll = bpy.data.collections.get(sc.DRONES_COLLECTION)
    return len(coll.all_objects) if coll is not None else 0


def _active_entry(s):
    if 0 <= s.storyboard_index < len(s.storyboard):
        return s.storyboard[s.storyboard_index]
    return None


def _clock(frame: int, fps: float) -> str:
    seconds = int(round(frame / fps))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ----------------------------------------------------------------------
# Tab "Murmura": drones and show
# ----------------------------------------------------------------------


class MURMURA_UL_groups(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="GROUP")
        row.label(text=str(len(item.names())))


class MURMURA_PT_drones(_Panel, bpy.types.Panel):
    bl_label = "Drones"
    bl_idname = "MURMURA_PT_drones"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        count = _drone_count()
        layout.label(
            text=tr("{count} drones in the scene", count=count) if count else tr("No drones yet"),
            icon="LIGHT_POINT",
        )
        col = _split(layout.column(align=True))
        col.prop(s, "drone_count")
        col.prop(s, "grid_spacing")
        col.prop(s, "drone_size")
        layout.operator("murmura.create_drones", icon="ADD")


class MURMURA_PT_drone_groups(_Panel, bpy.types.Panel):
    bl_label = "Drone Groups"
    bl_idname = "MURMURA_PT_drone_groups"
    bl_parent_id = "MURMURA_PT_drones"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        row = layout.row()
        row.template_list("MURMURA_UL_groups", "", s, "groups", s, "group_index", rows=3)
        col = row.column(align=True)
        col.operator("murmura.group_add", text="", icon="ADD")
        col.operator("murmura.group_remove", text="", icon="REMOVE")
        row = layout.row(align=True)
        row.operator("murmura.group_assign", text=tr("Add"), icon="ADD").action = "ADD"
        row.operator("murmura.group_assign", text=tr("Remove"), icon="REMOVE").action = "REMOVE"
        row.operator("murmura.group_select", text=tr("Select"), icon="RESTRICT_SELECT_OFF")
        layout.operator("murmura.select_drones", icon="RESTRICT_SELECT_OFF")


class MURMURA_UL_storyboard(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon=KIND_ICONS.get(item.kind, "DOT"))
        if item.frame_end:
            fps = context.scene.render.fps / context.scene.render.fps_base
            row.label(text=f"{_clock(item.frame_start, fps)}-{_clock(item.frame_end, fps)}")


def _draw_entry(layout, s, entry):
    """The few settings of a storyboard entry that matter every time."""
    col = _split(layout.column(align=True))
    if entry.kind == "TAKEOFF":
        col.prop(entry, "altitude")
        col.prop(entry, "climb_speed")
        col.prop(entry, "layered")
        return
    if entry.kind == "LAND":
        col.prop(entry, "return_style")
        if entry.return_style == "dissolve":
            col.prop(entry, "petal_order")
        if entry.return_style == "direct":
            col.prop(entry, "land_on")
        col.prop(entry, "layered")
        return
    if entry.source == "COLLECTION":
        col.prop(entry, "collection")
    else:
        col.prop(entry, "target", text=tr("Points"))
    if not entry.follow:
        col.prop(entry, "hold")
    col.prop_search(entry, "group", s, "groups", icon="GROUP")
    col.prop(entry, "follow")
    if entry.follow:
        sub = col.column(align=True)
        row = sub.row(align=True)
        row.prop(entry, "follow_start", text=tr("From"))
        row.prop(entry, "follow_end", text=tr("To"))
        row.operator("murmura.follow_auto", text="", icon="TIME")
        if not entry.follow_manual:
            sub.prop(entry, "hold", text=tr("Binding length"))


class MURMURA_PT_show(_Panel, bpy.types.Panel):
    bl_label = "Show"
    bl_idname = "MURMURA_PT_show"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("murmura.add_takeoff", text=tr("Takeoff"), icon="TRIA_UP_BAR")
        row.operator("murmura.add_selection", text=tr("Formation"), icon="ADD")
        row.operator("murmura.add_landing", text=tr("Landing"), icon="TRIA_DOWN_BAR")

        row = layout.row()
        row.template_list(
            "MURMURA_UL_storyboard", "", s, "storyboard", s, "storyboard_index", rows=5
        )
        col = row.column(align=True)
        col.operator("murmura.storyboard_remove", text="", icon="REMOVE")
        col.operator("murmura.storyboard_duplicate", text="", icon="DUPLICATE")
        col.separator()
        col.operator("murmura.storyboard_move", text="", icon="TRIA_UP").direction = "UP"
        col.operator("murmura.storyboard_move", text="", icon="TRIA_DOWN").direction = "DOWN"
        col.separator()
        col.operator("murmura.storyboard_jump", text="", icon="TIME")

        entry = _active_entry(s)
        if entry is None:
            box = layout.box().column(align=True)
            box.label(text=tr("Select an object with points"), icon="RESTRICT_SELECT_OFF")
            box.label(text=tr("and press Formation."))
        else:
            _draw_entry(layout, s, entry)

        big = layout.row()
        big.scale_y = 1.6
        big.operator("murmura.recalculate", icon="PLAY")
        if len(s.report):
            if all(line.ok for line in s.report):
                layout.label(text=tr("Show is safe"), icon="CHECKMARK")
            else:
                layout.label(text=tr("Problems found: see Murmura Export"), icon="ERROR")


class MURMURA_PT_show_more(_Panel, bpy.types.Panel):
    bl_label = "More Options"
    bl_idname = "MURMURA_PT_show_more"
    bl_parent_id = "MURMURA_PT_show"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.murmura
        layout = _split(self.layout)
        entry = _active_entry(s)
        if entry is not None:
            col = layout.column(align=True)
            if entry.kind in {"TAKEOFF", "LAND"}:
                sub = col.column(align=True)
                sub.enabled = entry.layered
                sub.prop(entry, "rows")
            if entry.kind == "LAND" and entry.return_style == "dissolve":
                col.prop(entry, "petal_interval")
            if entry.kind == "FORMATION":
                col.prop(entry, "source")
                if (
                    entry.source == "VERTEX_GROUP"
                    and entry.target is not None
                    and entry.target.type == "MESH"
                ):
                    col.prop_search(entry, "vertex_group", entry.target, "vertex_groups")
                col.prop(entry, "transition")
                col.prop(entry, "motion")
                if entry.motion != "none":
                    col.prop(entry, "motion_rate")
            row = col.row(heading=tr("Fixed start"))
            row.prop(entry, "use_start", text="")
            sub = row.row()
            sub.enabled = entry.use_start
            sub.prop(entry, "start", text="")
        layout.operator("murmura.clear_animation", icon="X")


class MURMURA_PT_shape_generator(_Panel, bpy.types.Panel):
    bl_label = "Shape Generator"
    bl_idname = "MURMURA_PT_shape_generator"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        layout.label(text=tr("Creates a new mesh; then add it as a formation."), icon="INFO")
        col = _split(layout.column(align=True))
        col.prop(s, "shape")
        if s.shape == "text":
            col.prop(s, "text")
        if s.shape in {"svg", "image"}:
            col.prop(s, "filepath")
        col.prop(s, "size", text=tr("Height") if s.shape == "text" else tr("Size"))
        if s.shape not in {"sphere", "cube", "torus", "helix", "grid"}:
            col.prop(s, "plane")
        col.prop(s, "center")
        col.prop(s, "auto_scale")
        layout.operator("murmura.add_formation", icon="MESH_DATA")


# ----------------------------------------------------------------------
# Tab "Murmura LEDs"
# ----------------------------------------------------------------------


class MURMURA_PT_lights(_Panel, bpy.types.Panel):
    bl_category = TAB_LEDS
    bl_label = "Lights"
    bl_idname = "MURMURA_PT_lights"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        entry = _active_entry(s)
        if entry is None or entry.kind != "FORMATION":
            layout.label(text=tr("Select a formation in the storyboard."), icon="INFO")
            return
        layout.label(text=entry.name, icon=KIND_ICONS["FORMATION"])
        col = _split(layout.column(align=True))
        col.prop(entry, "effect")
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


class MURMURA_PT_paint(_Panel, bpy.types.Panel):
    bl_category = TAB_LEDS
    bl_label = "Paint Drones"
    bl_idname = "MURMURA_PT_paint"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        layout.label(text=tr("Select drones, pick a colour, press Paint."), icon="INFO")
        row = layout.row(align=True)
        row.prop(s, "paint_color", text="")
        row.operator("murmura.paint", text=tr("Paint Selected"), icon="BRUSH_DATA")
        row.operator("murmura.paint_clear", text="", icon="X")
        entry = _active_entry(s)
        if entry is not None and len(entry.overrides):
            layout.label(
                text=tr("Painted drone sets: {count}", count=len(entry.overrides)),
                icon="BRUSH_DATA",
            )


# ----------------------------------------------------------------------
# Tab "Murmura Export"
# ----------------------------------------------------------------------


class MURMURA_PT_safety(_Panel, bpy.types.Panel):
    bl_category = TAB_EXPORT
    bl_label = "Safety"
    bl_idname = "MURMURA_PT_safety"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        col = _split(layout.column(align=True))
        col.prop(s, "min_distance")
        col.prop(s, "max_velocity_xy")
        col.prop(s, "max_altitude")
        col.prop(s, "tempo", slider=True)
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("murmura.validate", icon="CHECKMARK")
        row.operator("murmura.goto_violation", text="", icon="VIEWZOOM")


class MURMURA_PT_safety_more(_Panel, bpy.types.Panel):
    bl_category = TAB_EXPORT
    bl_label = "All Limits"
    bl_idname = "MURMURA_PT_safety_more"
    bl_parent_id = "MURMURA_PT_safety"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.murmura
        col = _split(self.layout.column(align=True))
        col.prop(s, "max_velocity_z")
        col.prop(s, "max_velocity_z_up")
        col.prop(s, "max_acceleration")
        col.prop(s, "min_nav_altitude")
        col.separator()
        col.prop(s, "landing_velocity")
        col.prop(s, "spindown")


class MURMURA_PT_export(_Panel, bpy.types.Panel):
    bl_category = TAB_EXPORT
    bl_label = "Export"
    bl_idname = "MURMURA_PT_export"

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        _split(layout).prop(s, "show_title")
        big = layout.row()
        big.scale_y = 1.6
        big.operator("murmura.export_skyc", icon="EXPORT")


class MURMURA_PT_export_more(_Panel, bpy.types.Panel):
    bl_category = TAB_EXPORT
    bl_label = "More Options"
    bl_idname = "MURMURA_PT_export_more"
    bl_parent_id = "MURMURA_PT_export"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.murmura
        layout = self.layout
        col = _split(layout.column(align=True))
        col.prop(s, "sample_fps")
        col.prop(s, "light_fps")
        col.prop(s, "fit_tolerance")
        row = layout.row(align=True)
        row.operator("murmura.export_csv", text=tr("CSV"), icon="FILE")
        row.operator("murmura.import_skyc", icon="IMPORT")
        row.operator("murmura.preview", icon="HIDE_OFF")
        layout.label(text=f"Murmura {ADDON_VERSION}")


class MURMURA_PT_report(_Panel, bpy.types.Panel):
    bl_category = TAB_EXPORT
    bl_label = "Report"
    bl_idname = "MURMURA_PT_report"

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
    MURMURA_PT_drones,
    MURMURA_PT_drone_groups,
    MURMURA_PT_show,
    MURMURA_PT_show_more,
    MURMURA_PT_shape_generator,
    MURMURA_PT_lights,
    MURMURA_PT_paint,
    MURMURA_PT_safety,
    MURMURA_PT_safety_more,
    MURMURA_PT_export,
    MURMURA_PT_export_more,
    MURMURA_PT_report,
)


def register():
    for cls in CLASSES:
        localize(cls)
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
