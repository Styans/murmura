"""Add-on properties stored in the scene."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .core import engine
from .i18n import localize

SHAPES = [
    ("circle", "Circle", "Ring of drones"),
    ("heart", "Heart", "Heart outline"),
    ("star", "Star", "Five-pointed star outline"),
    ("polygon", "Polygon", "Regular polygon outline"),
    ("spiral", "Spiral", "Flat spiral"),
    ("line", "Line", "Straight line"),
    ("rectangle", "Rectangle", "Rectangle outline"),
    ("disc", "Disc", "Filled disc"),
    ("grid", "Grid", "Horizontal grid"),
    ("sphere", "Sphere", "Points on a sphere"),
    ("cube", "Cube", "Points on a cube"),
    ("torus", "Torus", "Points on a torus"),
    ("helix", "Helix", "3D helix"),
    ("text", "Text", "Text with the built-in font (Latin and Cyrillic)"),
    ("svg", "SVG", "Outline of an SVG drawing, with its colours"),
    ("image", "Image", "Bright pixels of an image, with their colours"),
]

PLANES = [
    ("xz", "Front (XZ)", "Vertical plane facing the -Y side"),
    ("yz", "Side (YZ)", "Vertical plane facing the +X side"),
    ("xy", "Ground (XY)", "Horizontal plane"),
]

KINDS = [
    ("TAKEOFF", "Takeoff", "Smooth vertical takeoff from the pad"),
    ("FORMATION", "Formation", "Fly into a formation and hold it"),
    ("LAND", "Return and land", "Return above the pad and land"),
]

SOURCES = [
    ("OBJECT", "Object", "All vertices of the object (other objects: their location)"),
    ("VERTEX_GROUP", "Vertex group", "Vertices of one vertex group of the object"),
    (
        "COLLECTION",
        "Collection",
        "Vertices of every mesh in the collection, locations of other objects",
    ),
]

EFFECTS = [
    (
        "object",
        "Object colours",
        "Colours of the points, or the colour / texture of the object under them",
    ),
    ("keep", "Keep colours", "Leave the lights as they are"),
    ("solid", "Solid", "One colour"),
    ("gradient", "Gradient", "Gradient between two colours along an axis"),
    ("rainbow", "Rainbow", "Moving rainbow"),
    ("pulse", "Pulse", "Breathing brightness"),
    ("wave", "Wave", "Colour wave travelling along an axis"),
    ("sparkle", "Sparkle", "Random twinkles"),
    ("fade", "Fade", "Fade from the first to the second colour"),
]

AXES = [("x", "X", ""), ("y", "Y", ""), ("z", "Z", ""), ("radial", "Radial", "")]

MOTIONS = [
    ("none", "None", "Static formation"),
    ("rotate", "Rotate", "Spin around the vertical axis (rate = rpm)"),
    ("breathe", "Breathe", "Scale in and out (rate = relative amplitude)"),
    ("wave", "Wave", "Vertical wave (rate = amplitude in metres)"),
]

LAND_ON = [
    (
        "home",
        "Own spot",
        "Every drone flies back the way it came to the point it took off from and lands there",
    ),
    ("nearest", "Nearest spot", "Drones land on the nearest free spots (shorter return)"),
]


ROWS = [
    ("0", "Auto", "As many rows as the minimum distance needs (2 on a dense square pad)"),
    ("2", "2 (checkerboard)", "At least two rows: every other drone, like a checkerboard"),
    ("4", "4", "At least four rows: every other drone in both directions"),
]

RETURN_STYLES = [
    (
        "petals",
        "Sakura petals",
        "Drones peel off the formation one by one and drift home swaying, like falling petals",
    ),
    ("direct", "Straight home", "Drones fly straight back the way they came"),
]

PETAL_ORDERS = [
    ("top", "From the top", "The highest drones leave first"),
    ("bottom", "From the bottom", "The lowest drones leave first"),
    ("outside", "From the edges", "Drones furthest from the centre leave first"),
    ("front", "From the front", "Drones nearest to home leave first"),
    ("random", "Random", "Drones leave in random order"),
]


def _hex(color) -> str:
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, c)) * 255)):02x}" for c in color[:3])


class MURMURA_DroneGroup(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Group")
    members: StringProperty(default="")

    def names(self) -> set[str]:
        return set(filter(None, self.members.split("\n")))


class MURMURA_ColorOverride(bpy.types.PropertyGroup):
    members: StringProperty(default="")
    color: FloatVectorProperty(
        name="Colour", subtype="COLOR", size=3, min=0, max=1, default=(1.0, 0.2, 0.2)
    )

    def names(self) -> set[str]:
        return set(filter(None, self.members.split("\n")))


class MURMURA_StoryboardEntry(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Scene")
    kind: EnumProperty(name="Type", items=KINDS, default="FORMATION")

    # formation source
    source: EnumProperty(name="Points from", items=SOURCES, default="OBJECT")
    target: PointerProperty(name="Object", type=bpy.types.Object)
    collection: PointerProperty(name="Collection", type=bpy.types.Collection)
    vertex_group: StringProperty(name="Vertex group", default="")
    group: StringProperty(
        name="Drone group", description="Only this group flies (empty = all drones)", default=""
    )

    # timing
    hold: FloatProperty(
        name="Hold",
        description="Time spent in the formation",
        default=6.0,
        min=0.0,
        unit="TIME_ABSOLUTE",
    )
    use_start: BoolProperty(
        name="Fixed start", description="Start the transition at a fixed time", default=False
    )
    start: FloatProperty(name="Start", default=0.0, min=0.0, unit="TIME_ABSOLUTE")
    transition: FloatProperty(
        name="Min. transition",
        description="Minimum transition duration (0 = as fast as the limits allow)",
        default=0.0,
        min=0.0,
        unit="TIME_ABSOLUTE",
    )

    # lights
    effect: EnumProperty(name="Lights", items=EFFECTS, default="object")
    color: FloatVectorProperty(
        name="Colour", subtype="COLOR", size=3, min=0, max=1, default=(1.0, 1.0, 1.0)
    )
    color2: FloatVectorProperty(
        name="Colour 2", subtype="COLOR", size=3, min=0, max=1, default=(0.1, 0.3, 1.0)
    )
    period: FloatProperty(
        name="Period", description="Period / speed of animated effects", default=4.0, min=0.1
    )
    axis: EnumProperty(name="Axis", items=AXES, default="x")
    color_object: PointerProperty(
        name="Colour from",
        description="Object whose colours / texture light the drones (empty = the formation object or its parent)",
        type=bpy.types.Object,
    )
    min_brightness: FloatProperty(
        name="Min. brightness",
        description="Dark parts of the object still glow a little so that drones stay visible at night",
        default=0.15,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    overrides: CollectionProperty(type=MURMURA_ColorOverride)

    # motion
    motion: EnumProperty(name="Motion", items=MOTIONS, default="none")
    motion_rate: FloatProperty(name="Rate", default=2.0, min=0.0)

    # takeoff / landing
    altitude: FloatProperty(name="Altitude", default=6.0, min=1.0, unit="LENGTH")
    climb_speed: FloatProperty(
        name="Climb speed",
        description="Calm climbing saves the batteries: about 1-1.5 m/s is efficient for most drones",
        default=1.2,
        min=0.2,
        unit="VELOCITY",
    )
    layered: BoolProperty(
        name="In turns",
        description=(
            "Drones standing closer than the minimum distance take off and land in turns "
            "(checkerboard): one wave climbs, then the next, each to its own height"
        ),
        default=True,
    )
    land_on: EnumProperty(name="Land on", items=LAND_ON, default="home")
    rows: EnumProperty(
        name="Rows",
        description="Drones take off and land row by row, each row after the previous one",
        items=ROWS,
        default="0",
    )
    return_style: EnumProperty(name="Return", items=RETURN_STYLES, default="petals")
    petal_order: EnumProperty(name="Petals fall", items=PETAL_ORDERS, default="top")
    petal_interval: FloatProperty(
        name="Petal interval",
        description="Time between drones leaving the formation",
        default=0.15,
        min=0.02,
        max=2.0,
        unit="TIME_ABSOLUTE",
    )
    sway: FloatProperty(
        name="Sway",
        description="How far the petals sway sideways on their way home",
        default=1.5,
        min=0.0,
        max=5.0,
        unit="LENGTH",
    )

    # filled in by Recalculate
    frame_start: IntProperty(default=0)
    frame_end: IntProperty(default=0)

    def make_effect(self):
        c1, c2 = _hex(self.color), _hex(self.color2)
        spec = {
            "object": {"effect": "formation", "fallback": c1},
            "solid": {"effect": "solid", "color": c1},
            "gradient": {"effect": "gradient", "colors": [c1, c2], "axis": self.axis},
            "rainbow": {"effect": "rainbow", "period": self.period, "axis": self.axis},
            "pulse": {"effect": "pulse", "color": c1, "period": self.period},
            "wave": {
                "effect": "wave",
                "colors": [c1, c2],
                "speed": 20.0 / self.period,
                "axis": self.axis,
            },
            "sparkle": {"effect": "sparkle", "color": c1, "background": c2},
            "fade": {"effect": "fade", "start": c1, "end": c2, "duration": self.period},
        }.get(self.effect)
        return engine.make_effect(spec) if spec else None

    def make_motion(self):
        if self.motion == "none":
            return None
        if self.motion == "rotate":
            return engine.Motion("rotate", rpm=self.motion_rate)
        return engine.Motion(self.motion, amplitude=self.motion_rate)


class MURMURA_ReportLine(bpy.types.PropertyGroup):
    text: StringProperty()
    ok: BoolProperty(default=True)


class MURMURA_Settings(bpy.types.PropertyGroup):
    # swarm
    drone_count: IntProperty(name="Drones", default=100, min=1, max=10000)
    grid_spacing: FloatProperty(
        name="Spacing",
        description="Distance between drones on the pad",
        default=3.0,
        min=0.5,
        unit="LENGTH",
    )
    grid_columns: IntProperty(name="Columns", description="0 = square grid", default=0, min=0)
    drone_size: FloatProperty(
        name="Drone size",
        description="Diameter of the drone spheres",
        default=0.5,
        min=0.05,
        unit="LENGTH",
    )
    groups: CollectionProperty(type=MURMURA_DroneGroup)
    group_index: IntProperty(default=0)

    # formation generator
    shape: EnumProperty(name="Shape", items=SHAPES, default="circle")
    size: FloatProperty(
        name="Size", description="Radius or overall size", default=15.0, min=0.1, unit="LENGTH"
    )
    plane: EnumProperty(name="Plane", items=PLANES, default="xz")
    center: FloatVectorProperty(
        name="Centre", size=3, default=(0.0, 0.0, 30.0), subtype="TRANSLATION", unit="LENGTH"
    )
    text: StringProperty(name="Text", default="HELLO")
    filepath: StringProperty(name="File", subtype="FILE_PATH")
    auto_scale: BoolProperty(
        name="Keep spacing",
        description="Enlarge the formation if its points are closer than the minimum distance",
        default=True,
    )

    # storyboard
    storyboard: CollectionProperty(type=MURMURA_StoryboardEntry)
    storyboard_index: IntProperty(default=0)
    paint_color: FloatVectorProperty(
        name="Paint colour", subtype="COLOR", size=3, min=0, max=1, default=(1.0, 0.2, 0.2)
    )

    # safety and movement
    max_velocity_xy: FloatProperty(name="Max speed XY", default=6.0, min=0.1, unit="VELOCITY")
    max_velocity_z: FloatProperty(name="Max speed Z", default=2.5, min=0.1, unit="VELOCITY")
    max_velocity_z_up: FloatProperty(name="Max climb", default=2.0, min=0.1, unit="VELOCITY")
    max_acceleration: FloatProperty(
        name="Max acceleration", default=3.0, min=0.1, unit="ACCELERATION"
    )
    min_distance: FloatProperty(name="Min distance", default=2.0, min=0.1, unit="LENGTH")
    max_altitude: FloatProperty(name="Max altitude", default=120.0, min=1.0, unit="LENGTH")
    min_nav_altitude: FloatProperty(name="Min show altitude", default=2.5, min=0.0, unit="LENGTH")
    tempo: FloatProperty(
        name="Transition tempo",
        description="Share of the speed limits used by transitions: lower is calmer and easier on the batteries",
        default=0.85,
        min=0.3,
        max=1.0,
        subtype="FACTOR",
    )
    landing_velocity: FloatProperty(name="Landing speed", default=1.0, min=0.1, unit="VELOCITY")
    spindown: FloatProperty(
        name="Spin-down", description="Time between touchdowns of neighbours", default=3.0, min=0.0
    )

    # export
    show_title: StringProperty(name="Title", default="")
    sample_fps: FloatProperty(
        name="Sampling rate",
        description="Samples per second taken from the animation (0 = every frame)",
        default=8.0,
        min=0.0,
    )
    light_fps: FloatProperty(
        name="Light rate",
        description="Light samples per second (0 = same as the sampling rate)",
        default=0.0,
        min=0.0,
    )
    fit_tolerance: FloatProperty(
        name="Accuracy", description="Max trajectory error", default=0.02, min=0.001, unit="LENGTH"
    )

    # results
    report: CollectionProperty(type=MURMURA_ReportLine)
    report_title: StringProperty(default="")
    first_violation: FloatProperty(default=-1.0)
    violation_drones: StringProperty(default="")

    def limits(self):
        return engine.SafetyLimits(
            max_velocity_xy=self.max_velocity_xy,
            max_velocity_z=self.max_velocity_z,
            max_velocity_z_up=self.max_velocity_z_up,
            max_acceleration_xy=self.max_acceleration,
            max_acceleration_z=self.max_acceleration,
            min_distance=self.min_distance,
            max_altitude=self.max_altitude,
            min_nav_altitude=self.min_nav_altitude,
        )

    def set_report(self, title: str, lines: list[tuple[str, bool]]) -> None:
        self.report.clear()
        self.report_title = title
        for text, ok in lines:
            item = self.report.add()
            item.text = text
            item.ok = ok


CLASSES = (
    MURMURA_DroneGroup,
    MURMURA_ColorOverride,
    MURMURA_StoryboardEntry,
    MURMURA_ReportLine,
    MURMURA_Settings,
)


def register():
    for cls in CLASSES:
        localize(cls)
        bpy.utils.register_class(cls)
    bpy.types.Scene.murmura = PointerProperty(type=MURMURA_Settings)


def unregister():
    del bpy.types.Scene.murmura
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
