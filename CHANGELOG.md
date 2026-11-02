# Changelog

## 0.1.1 - 2026-11-02

Blender add-on:

- Simpler interface laid out like Skybrush Studio: three sidebar tabs -
  *Murmura* (drones and show), *Murmura LEDs* (lights, painting) and
  *Murmura Export* (safety, validation, export). Rarely used settings moved
  to collapsed sub-panels; a status line under *Recalculate Show* says
  whether the show is safe; storyboard times are shown as minutes:seconds.
- *Formation* turns the selection into a formation: one or several objects,
  vertices in Edit Mode, or the collection active in the Outliner. It
  reports the number of points and drones.
- The shape generator moved to a collapsed *Shape Generator* panel; its
  button is now *Create Shape Mesh*.
- The language selector moved to the add-on preferences.

## 0.1.0 - 2026-10-30

First public release.

- `.skyc` reader and writer: Bézier trajectories, LED bytecode, yaw, pyro,
  cues, cameras, geolocation and audio.
- Trajectory compression of sampled motion with C¹-continuous cubic segments
  and a guaranteed error bound.
- Formations: grid, line, circle, polygon, star, heart, spiral, disc,
  rectangle, sphere, cube, torus, helix, text (Latin + Cyrillic), SVG, image.
- Planning: squared-distance assignment, smooth transitions, staggered,
  lane-based and via-spread conflict resolution verified by simulation,
  layered takeoff, staged return and sequenced landing, smart RTH.
- LED effects: solid, formation colours, gradient, rainbow, pulse, wave,
  sparkle, fade; formation motions: rotate, breathe, wave.
- Safety validation with a PDF report.
- Show scripts (YAML / JSON), Python API and command line tool.
- Blender add-on (Blender 4.2+): drones, formations, storyboard, one-click show
  building baked as exact Bézier keyframes, validation, `.skyc` / CSV export,
  `.skyc` import and viewer preview; ships with a bundled copy of the engine.
- SciPy is optional: exact NumPy fallbacks for assignment and neighbour search.
- Russian localisation: Blender add-on (with its own language selector),
  command line, validation and planner messages, PDF reports, documentation.
- HTTP planning server compatible with the Skybrush Studio for Blender add-on.
- Live preview in a running show viewer.
