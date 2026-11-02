# Murmura

**Open drone show choreography engine.** Design formations, plan collision-aware
transitions, compose LED programs and export compiled `.skyc` show files - from a
YAML script, from Python, or inside Blender with the bundled add-on.

> A *murmuration* is a flock of starlings moving as one. Murmura does the same for drones.

```text
 takeoff grid ──► takeoff in waves ──► formations + transitions ──► staged return ──► landing in waves
                                         │            │
                                   LED effects   safety checks ──► .skyc / CSV / PDF report
```

## Features

- **`.skyc` export and import** - compiled show archives with Bézier trajectories,
  LED bytecode, yaw setpoints, pyro events, cues, cameras, geolocation and a
  soundtrack. Files load in existing `.skyc` viewers and ground control software.
- **Collision-aware transitions** - optimal drone-to-point assignment, then the
  fastest safe plan among synchronised, *staggered* (per-drone start delays) and
  *lane-based* (temporary depth/altitude layers) transitions, verified by simulation.
- **Takeoff and landing planning** - takeoff and landing in waves (checkerboard) that keep the minimum distance on dense pads, staged
  return-to-home, sequenced landing with spin-down time, smart RTH with neck paths.
- **Formations** - grid, line, circle, polygon, star, heart, spiral, disc,
  rectangle, sphere, cube, torus, helix, text (Latin + Cyrillic bitmap font),
  SVG drawings (paths, arcs, transforms, colours) and images.
- **LED effects** - solid, formation colours, gradient, rainbow, pulse, wave,
  sparkle, fade; automatic keyframe simplification; exact 50 fps bytecode.
- **Motion** - rotate, breathe and wave animations that are automatically
  softened to stay inside the velocity and acceleration envelope.
- **Safety validation** - altitude, horizontal / vertical speed, acceleration,
  minimum distance between airborne drones, minimum navigation altitude and yaw
  rate, with a PDF report.
- **Blender add-on** - drones, formations, a storyboard and one-click show
  building baked as exact Bézier keyframes, safety checks, `.skyc` export and
  import; runs on Blender's own Python with no extra packages.
- **Planning server** - an HTTP API compatible with the Skybrush Studio for
  Blender add-on: point the add-on to `http://localhost:8000` and keep using
  your Blender workflow for transitions, takeoff, landing, RTH, SVG formations,
  validation plots and `.skyc` / CSV export.
- **Live preview** - send a show to a running show viewer on the same machine.

## Install

Python 3.10 or newer.

```bash
git clone https://github.com/Styans/murmura.git
cd murmura
pip install -e ".[all]"
```

`pip install murmura` installs the core only; the extras are `server`
(FastAPI + Uvicorn), `plot` (matplotlib, for PDF reports) and `image` (Pillow).

## Quick start

Build the bundled 100-drone demo, a CSV export and a validation report:

```bash
murmura demo -o demo.skyc --csv demo.zip --report demo.pdf
```

```text
Wrote demo.skyc (148.2 KiB, 100 drones, 276.0 s)
Show: Murmura demo - 100 drones, 4:36.00
[ OK ] Max altitude: 99.36 m (limit 120 m)
[ OK ] Max horizontal speed: 4.82 m/s (limit 6 m/s)
[ OK ] Min distance (airborne): 2.00 m (limit 2 m)
...
RESULT: PASSED
```

Write your own show as a script ([reference](docs/show-script.md)):

```yaml
title: Hello sky
drones: 36
limits: {max_velocity_xy: 6, max_velocity_z: 2.5, max_acceleration: 3, min_distance: 2}
home: {grid: {spacing: 3, columns: 6}}
takeoff: {altitude: 6}
auto_scale: true
scenes:
  - name: Ring
    formation: {shape: circle, radius: 14, center: [0, 0, 25]}
    hold: 8
    lights: {effect: rainbow, period: 4}
    motion: {kind: rotate, rpm: 2}
  - name: Heart
    formation: {shape: heart, size: 26, center: [0, 0, 28]}
    hold: 6
    lights: "#ff1744"
landing: {velocity: 1.2}
```

```bash
murmura build examples/hello.yaml -o hello.skyc --report hello.pdf
```

## Command line

| Command | Purpose |
| --- | --- |
| `murmura build SCRIPT.yaml -o show.skyc` | compile a show script (also `--csv`, `--report`, `--preview`, `--strict`) |
| `murmura demo -o demo.skyc` | build the built-in demo |
| `murmura serve --port 8000` | run the planning server |
| `murmura inspect show.skyc --validate` | summary of any `.skyc`, CSV archive or script |
| `murmura validate show.skyc --min-distance 2.5` | safety checks with optional overrides |
| `murmura convert show.skyc show.zip` | convert between `.skyc`, CSV `.zip`, `.json` and `.pdf` |
| `murmura preview show.skyc` | open a show in a running show viewer |
| `murmura formation heart -n 200 -p size=60` | export a static formation as `Name,x,y,z,R,G,B` CSV |

## Blender add-on

```bash
python blender/build_addon.py        # -> dist/murmura-blender-0.1.1.zip
```

Install the zip in Blender 4.2+ via *Edit → Preferences → Get Extensions →
Install from Disk*. The **Murmura** tab in the 3D viewport sidebar lets you:

1. create drones on a takeoff grid (lit by their object colour),
2. add formations - shapes, text, SVG drawings, images or any mesh,
3. arrange them on a storyboard with hold times, light effects and motions,
4. **Build Show** - takeoff, collision-aware transitions, lights and landing
   are planned and baked as keyframes that reproduce the planned curves exactly,
5. validate the animation and export / import `.skyc` (also in *File → Export / Import*).

Everything runs on Blender's own Python; no server and no extra packages are
needed. Details: [docs/blender-addon.md](docs/blender-addon.md).

## Languages

The Blender add-on, the command line, validation reports and PDF reports are
available in English and Russian. The add-on has a language selector
(Auto / Русский / English) that works independently of Blender's own interface
language. The command line follows the system language or `MURMURA_LANG`, or
takes `--lang en|ru`. Russian documentation: [README.ru.md](README.ru.md),
[docs/blender-addon.ru.md](docs/blender-addon.ru.md),
[docs/show-script.ru.md](docs/show-script.ru.md).

## Using it with the Skybrush Studio add-on

The Skybrush Studio add-on for Blender talks to a planning backend over HTTP.
Murmura implements the same operations:

```bash
murmura serve --port 8000
```

In Blender open *Preferences → Add-ons → Skybrush Studio*, choose the local
server (`http://localhost:8000`) and use the add-on as usual. Supported
operations: render (`.skyc`, CSV, PDF validation plots, multi-render),
plan-transition, match-points, plan-takeoff, decompose, plan-landing,
plan-smart-rth and create-static-formation (SVG import). Interactive API docs
are served at `http://localhost:8000/docs`; see [docs/server-api.md](docs/server-api.md).

## Python API

```python
from murmura import ShowBuilder, SafetyLimits, validate_show, write_skyc
from murmura.effects import Rainbow, Pulse
from murmura.formations import circle, heart

limits = SafetyLimits(max_velocity_xy=6, max_velocity_z=2.5, min_distance=2)
show = (
    ShowBuilder(50, title="Python demo", limits=limits, grid_spacing=3)
    .takeoff(altitude=6)
    .scene("Ring", circle(50, radius=18, center=(0, 0, 25)), hold=8, effect=Rainbow(period=4))
    .scene("Heart", heart(50, size=40, center=(0, 0, 30)), hold=6, effect=Pulse(color="#ff1744"))
    .land()
    .build()
)
print(validate_show(show).summary())
write_skyc(show, "python-demo.skyc")
```

More in [examples/](examples/).

## How transitions stay safe

1. **Assignment** - drones are matched to the new formation by minimising the
   sum of *squared* distances (Hungarian algorithm). Compared with minimising
   plain distance this keeps the swarm's structure during the flight and
   removes most near misses, especially between 3D and planar shapes.
2. **Timing** - every drone flies a straight line with a smooth (cubic
   ease-in-out) profile; durations follow from the velocity and acceleration
   limits (peak speed = 1.5·d/T, peak acceleration = 6·d/T²). The resulting
   segment is stored *exactly* as a cubic Bézier curve.
3. **Conflict resolution** - if two paths come closer than `min_distance`, the
   planner simulates and compares a staggered plan (prioritised start delays
   plus local repair) and lane plans (conflicting drones fly through parallel
   layers), and keeps the fastest plan that stays safe.
4. **Landing** - the swarm forms an enlarged copy of the landing grid, then
   contracts uniformly onto it (an affine blend that cannot reduce spacing),
   then lands in sequence so that neighbours keep their distance and spin-down time.
5. **Validation** - the finished show is sampled and checked against the full
   flight envelope.

## The `.skyc` format

See [docs/skyc-format.md](docs/skyc-format.md) for the archive layout,
trajectory representation and the LED bytecode.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests blender && ruff format --check src tests blender
blender --background --factory-startup --python blender/tests/run_blender_tests.py
```

Murmura uses SciPy when it is installed and falls back to exact NumPy
implementations otherwise (this is what runs inside Blender).

## Disclaimer

Murmura is an independent project and is not affiliated with or endorsed by
CollMot Robotics or the Skybrush project. "Skybrush" is used only to describe
file and API compatibility. Drone shows are a high-risk activity: always
validate shows, keep safety margins, follow local regulations and test in a
safe area before any public performance.

## License

[MIT](LICENSE)
