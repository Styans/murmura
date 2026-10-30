"""Builds a show from Python and writes it as .skyc, CSV and a PDF report.

Run with:  python examples/python_api.py
"""

from pathlib import Path

from murmura import SafetyLimits, ShowBuilder, validate_show, write_skyc
from murmura.choreo import Motion
from murmura.csvio import write_csv_zip
from murmura.effects import Gradient, Pulse, Rainbow
from murmura.formations import circle, heart, scale_to_spacing, sphere, text

N = 50
limits = SafetyLimits(
    max_velocity_xy=6,
    max_velocity_z=2.5,
    max_velocity_z_up=2,
    max_acceleration_xy=3,
    max_acceleration_z=3,
    min_distance=2,
)

builder = ShowBuilder(N, title="Python API demo", limits=limits, grid_spacing=3)
builder.takeoff(altitude=6, color="#303030")
builder.scene(
    "Ring",
    circle(N, radius=18, center=(0, 0, 25)),
    hold=8,
    effect=Rainbow(period=4),
    motion=Motion("rotate", rpm=2),
)
builder.scene(
    "Heart",
    scale_to_spacing(heart(N, size=36, center=(0, 0, 30)), 2.3),
    hold=6,
    effect=Pulse(color="#ff1744", period=1.5),
)
builder.scene("Ball", sphere(N, radius=8, center=(0, 0, 28)), hold=6, effect=Rainbow(axis="z"))
builder.scene(
    "Text",
    scale_to_spacing(text(N, text="2026", height=10, center=(0, 0, 28)), 2.3),
    hold=6,
    effect=Gradient(colors_=["#40c4ff", "#e040fb"], axis="x"),
)
builder.land(velocity=1.2)

show = builder.build()
for note in builder.log:
    print("note:", note)

report = validate_show(show)
print(report.summary())

out = Path("python-demo")
out.mkdir(exist_ok=True)
write_skyc(show, out / "show.skyc")
(out / "show.zip").write_bytes(write_csv_zip(show, fps=4))
try:
    from murmura.report import render_report_pdf

    (out / "report.pdf").write_bytes(render_report_pdf(show, report))
except RuntimeError as ex:  # matplotlib not installed
    print(ex)
print(f"Files written to {out.resolve()}")
