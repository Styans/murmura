"""Command line interface: ``murmura <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .i18n import set_language, t

DEMO_SCRIPT = {
    "title": "Murmura demo",
    "drones": 100,
    "limits": {
        "max_velocity_xy": 6.0,
        "max_velocity_z": 2.5,
        "max_velocity_z_up": 2.0,
        "max_acceleration": 2.5,
        "min_distance": 2.0,
        "max_altitude": 120.0,
    },
    "home": {"grid": {"spacing": 2.5, "columns": 10}},
    "auto_scale": True,
    "takeoff": {"altitude": 6.0, "color": "#303030"},
    "scenes": [
        {
            "name": "Ring",
            "formation": {"shape": "circle", "radius": 38, "center": [0, 0, 30], "plane": "xy"},
            "hold": 12,
            "lights": {"effect": "rainbow", "period": 5, "axis": "x"},
            "motion": {"kind": "rotate", "rpm": 1.2},
        },
        {
            "name": "Heart",
            "formation": {"shape": "heart", "size": 62, "center": [0, 0, 42]},
            "hold": 8,
            "lights": {"effect": "pulse", "color": "#ff1744", "period": 1.6, "min": 0.25},
        },
        {
            "name": "Sphere",
            "formation": {"shape": "sphere", "radius": 12, "center": [0, 0, 32]},
            "hold": 12,
            "lights": {"effect": "wave", "colors": ["#00e5ff", "#7c4dff"], "speed": 6, "axis": "z"},
            "motion": {"kind": "rotate", "rpm": 2},
        },
        {
            "name": "Star",
            "formation": {"shape": "star", "radius": 36, "center": [0, 0, 44]},
            "hold": 8,
            "lights": {
                "effect": "sparkle",
                "color": "#fff3c4",
                "background": "#ff9100",
                "rate": 0.8,
            },
        },
        {
            "name": "Hello",
            "formation": {"shape": "text", "text": "HI!", "height": 20, "center": [0, 0, 30]},
            "hold": 8,
            "lights": {
                "effect": "gradient",
                "colors": ["#ff4081", "#ffd740", "#69f0ae"],
                "axis": "x",
            },
        },
    ],
    "landing": {"velocity": 1.2, "spindown": 3},
}


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def _validate_and_report(show, args) -> bool:
    from .validation import validate_show

    report = validate_show(show, dt=getattr(args, "dt", 0.25) or 0.25)
    _print(report.summary())
    if getattr(args, "report", None):
        from .report import render_report_pdf

        Path(args.report).write_bytes(render_report_pdf(show, report))
        _print(t("Validation report written to {path}", path=args.report))
    if getattr(args, "json_report", None):
        Path(args.json_report).write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    return report.passed


def _write_outputs(show, args) -> None:
    from .skyc import write_skyc

    out = Path(args.output)
    write_skyc(show, out)
    _print(
        t(
            "Wrote {path} ({size:.1f} KiB, {drones} drones, {duration:.1f} s)",
            path=out,
            size=out.stat().st_size / 1024,
            drones=show.num_drones,
            duration=show.duration,
        )
    )
    if getattr(args, "csv", None):
        from .csvio import write_csv_zip

        Path(args.csv).write_bytes(write_csv_zip(show, fps=args.csv_fps))
        _print(t("Wrote {path}", path=args.csv))
    if getattr(args, "preview", False):
        _preview(out)


def _preview(path: Path) -> None:
    from .viewer import ViewerNotFoundError, send_to_viewer

    try:
        url = send_to_viewer(path.read_bytes(), title=path.name)
        _print(t("Sent to the viewer at {url}", url=url))
    except (ViewerNotFoundError, RuntimeError) as ex:
        _print(t("Preview failed: {error}", error=ex))


def cmd_build(args) -> int:
    from .script import build_from_script

    started = time.perf_counter()
    show, notes = build_from_script(args.script)
    for note in notes:
        _print(f"{t('note')}: {note}")
    if not args.output:
        args.output = str(Path(args.script).with_suffix(".skyc"))
    _write_outputs(show, args)
    _print(t("Built in {seconds:.1f} s", seconds=time.perf_counter() - started))
    ok = True if args.no_validate else _validate_and_report(show, args)
    return 0 if ok or not args.strict else 1


def cmd_demo(args) -> int:
    from .script import build_from_script

    show, notes = build_from_script(json.loads(json.dumps(DEMO_SCRIPT)))
    for note in notes:
        _print(f"{t('note')}: {note}")
    _write_outputs(show, args)
    _validate_and_report(show, args)
    return 0


def cmd_serve(args) -> int:
    try:
        from .server import serve
    except ImportError:
        _print(t("The server needs extra packages: pip install murmura[server]"))
        return 2
    _print(
        t(
            "Murmura planning server {version} on http://{host}:{port}  (API docs: /docs)",
            version=__version__,
            host=args.host,
            port=args.port,
        )
    )
    serve(args.host, args.port, compat_version=args.compat_version)
    return 0


def cmd_inspect(args) -> int:
    from .render import load_show

    show = load_show(args.file)
    sec = t("s")

    def field(label: str) -> str:
        return f"{t(label):<14}"

    _print(f"{field('Title:')}{show.title}")
    _print(f"{field('Drones:')}{show.num_drones}")
    _print(f"{field('Duration:')}{show.duration:.2f} {sec}")
    if show.segments:
        for name, (a, b) in show.segments.items():
            _print(f"{field('Segment:')}{t(name):<8} {a:8.2f} - {b:8.2f} {sec}")
    if show.cues:
        _print(field("Cues:") + ", ".join(f"{c.name} @ {c.time:.2f}{sec}" for c in show.cues[:20]))
    if show.audio:
        _print(
            f"{field('Audio:')}{show.audio.filename} ({len(show.audio.data) / 1024:.0f} KiB) "
            f"@ {show.audio.start_time:.2f}{sec}"
        )
    if show.location:
        loc = show.location
        heading = t("heading {heading:.1f} deg", heading=loc.orientation)
        _print(f"{field('Location:')}{loc.latitude:.7f}, {loc.longitude:.7f}, {heading}")
    segments = sum(max(0, len(d.trajectory) - 1) for d in show.drones)
    keyframes = sum(len(d.lights) for d in show.drones)
    _print(
        t(
            "Trajectory segments: {segments}, light keyframes: {keyframes}",
            segments=segments,
            keyframes=keyframes,
        )
    )
    extras = [
        n
        for n, flag in (
            (t("yaw"), any(d.yaw for d in show.drones)),
            (t("pyro"), any(d.pyro for d in show.drones)),
        )
        if flag
    ]
    if extras:
        _print(field("Extras:") + ", ".join(extras))
    if args.validate:
        _validate_and_report(show, args)
    return 0


def cmd_validate(args) -> int:
    from .render import load_show

    show = load_show(args.file)
    for key in ("min_distance", "max_velocity_xy", "max_velocity_z", "max_altitude"):
        value = getattr(args, key)
        if value is not None:
            setattr(show.limits, key, value)
    if args.max_acceleration is not None:
        show.limits.max_acceleration_xy = show.limits.max_acceleration_z = args.max_acceleration
    return 0 if _validate_and_report(show, args) else 1


def cmd_convert(args) -> int:
    from .render import load_show, render_output

    show = load_show(args.input)
    fmt = {".skyc": "skyc", ".zip": "csv", ".pdf": "plot", ".json": "json"}.get(
        Path(args.output).suffix.lower()
    )
    if fmt is None:
        _print(t("Output must end with .skyc, .zip (CSV), .pdf (report) or .json"))
        return 2
    payload, _, _ = render_output(show, {"format": fmt, "parameters": {"fps": args.fps}})
    Path(args.output).write_bytes(payload)
    _print(t("Wrote {path}", path=args.output))
    return 0


def cmd_preview(args) -> int:
    _preview(Path(args.file))
    return 0


def cmd_formation(args) -> int:
    from .formations import make_formation

    spec = {"shape": args.shape}
    for item in args.param or []:
        key, _, value = item.partition("=")
        try:
            spec[key] = json.loads(value)
        except json.JSONDecodeError:
            spec[key] = value
    points, colors = make_formation(spec, args.n, base_dir=Path.cwd())
    lines = ["Name,x,y,z,Red,Green,Blue"]
    for i, p in enumerate(points):
        c = colors[i] if colors is not None else (255, 255, 255)
        lines.append(
            f"Drone {i + 1},{p[0]:.3f},{p[1]:.3f},{p[2]:.3f},{int(c[0])},{int(c[1])},{int(c[2])}"
        )
    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    _print(t("Wrote {count} points to {path}", count=len(points), path=args.output))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="murmura", description=t("Drone show choreography engine")
    )
    parser.add_argument("--version", action="version", version=f"murmura {__version__}")
    parser.add_argument("--lang", default="auto", help=t("interface language: auto, en or ru"))
    sub = parser.add_subparsers(dest="command", required=True)

    def outputs(p, default_output: str | None = None):
        p.add_argument("-o", "--output", default=default_output, help=t("output .skyc file"))
        p.add_argument("--csv", help=t("also write a CSV archive (.zip)"))
        p.add_argument(
            "--csv-fps", type=float, default=4.0, help=t("CSV sampling rate (default: 4)")
        )
        p.add_argument("--report", help=t("write a PDF validation report"))
        p.add_argument("--json-report", help=t("write the validation result as JSON"))
        p.add_argument(
            "--preview", action="store_true", help=t("open the result in a running show viewer")
        )

    p = sub.add_parser("build", help=t("compile a YAML/JSON show script into .skyc"))
    p.add_argument("script")
    outputs(p)
    p.add_argument("--no-validate", action="store_true")
    p.add_argument(
        "--strict", action="store_true", help=t("exit with status 1 if validation fails")
    )
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("demo", help=t("build the built-in 100-drone demo show"))
    outputs(p, "murmura-demo.skyc")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("serve", help=t("run the planning server for design plugins"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--compat-version", default="2.45.0", help=t("API level reported to clients"))
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("inspect", help=t("print a summary of a show file"))
    p.add_argument("file")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--report")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("validate", help=t("check a show against its safety limits"))
    p.add_argument("file")
    p.add_argument("--dt", type=float, default=0.25, help=t("sampling interval in seconds"))
    p.add_argument("--min-distance", type=float)
    p.add_argument("--max-velocity-xy", type=float)
    p.add_argument("--max-velocity-z", type=float)
    p.add_argument("--max-acceleration", type=float)
    p.add_argument("--max-altitude", type=float)
    p.add_argument("--report", help=t("write a PDF report"))
    p.add_argument("--json-report", help=t("write a JSON report"))
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("convert", help=t("convert between .skyc, CSV .zip, .json and PDF report"))
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--fps", type=float, default=4.0)
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("preview", help=t("send a .skyc file to a running show viewer"))
    p.add_argument("file")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("formation", help=t("export a formation as a static CSV (Name,x,y,z,R,G,B)"))
    p.add_argument("shape", help=t("circle, heart, star, sphere, text, svg, image, ..."))
    p.add_argument("-n", type=int, required=True, help=t("number of points"))
    p.add_argument(
        "-p",
        "--param",
        action="append",
        help=t("shape parameter, e.g. radius=15 or center=[0,0,30]"),
    )
    p.add_argument("-o", "--output", default="formation.csv")
    p.set_defaults(func=cmd_formation)
    return parser


def _language_from_argv(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
    return "auto"


def main(argv: list[str] | None = None) -> int:
    # never crash on characters the console encoding cannot show (e.g. piped cp1251 output)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    set_language(_language_from_argv(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (ValueError, OSError) as ex:
        _print(f"{t('error')}: {ex}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
