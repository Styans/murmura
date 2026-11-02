# Show scripts

A show script is a YAML (or JSON) document compiled with
`murmura build script.yaml -o show.skyc`. Relative file paths are resolved
against the folder of the script.

```yaml
title: My show              # shown in viewers
drones: 64                  # required

limits:                     # flight envelope used for planning and validation
  max_velocity_xy: 6        # m/s
  max_velocity_z: 2.5       # m/s, descending (and climbing unless max_velocity_z_up is set)
  max_velocity_z_up: 2.0    # m/s, optional
  max_acceleration: 3       # m/s², sets both of the following
  max_acceleration_xy: 3
  max_acceleration_z: 3
  min_distance: 2           # m, between airborne drones
  max_altitude: 120         # m
  min_nav_altitude: 2.5     # m above home, during the show segment
  max_yaw_rate: 30          # deg/s

home:                       # takeoff / landing positions (pick one)
  grid: {spacing: 3, columns: 8, center: [0, 0, 0], yaw: 0}
  # points: [[x, y, z], ...]
  # file: home.csv          # rows ending with x,y,z

settings:
  light_fps: 10             # sampling rate of animated light effects
  motion_fps: 8             # sampling rate of animated formations
  fit_tolerance: 0.02       # m, max error when compressing animated motion
  profile: smooth           # smooth | linear | ease_in | ease_out
  stagger: true             # resolve conflicts with delays / lanes

auto_scale: false           # enlarge formations that are denser than min_distance (+15% margin)

takeoff:                    # or `false` to start in the air
  altitude: 6
  layered: true             # drones closer than min_distance take off in waves (checkerboard)
  color: "#303030"

scenes:
  - name: Ring
    formation: {shape: circle, radius: 18, center: [0, 0, 30], plane: xz}
    hold: 8                 # seconds in formation after arriving
    start: 20.0             # optional: absolute time to start the transition (music sync)
    auto_scale: true        # per-scene override
    lights: {effect: rainbow, period: 4, axis: x}
    motion: {kind: rotate, rpm: 2}
    transition:
      duration: 10          # minimum duration; extended if the limits need more time
      profile: smooth
      stagger: true
      matching: optimal     # optimal | fixed
      lights: {effect: fade, start: black, end: white, duration: 10}
  - wait: 3                 # pause in place
  - name: Logo
    formation: {shape: svg, file: logo.svg, size: 40, center: [0, 0, 35]}
    lights: formation       # use the colours of the drawing

landing:                    # or `false`
  velocity: 1.2             # m/s peak descent speed
  spindown: 3               # s between touchdowns of neighbouring drones
  target: home              # home (own takeoff point, back the way it came) | nearest
  staging_spread: null      # optional enlarged staging grid before the final approach, e.g. 2.0
  rows: 0                   # at least this many landing rows (0 = as needed, 2, 4)
  style: morph              # morph (re-form above the pad, all at once) | direct | petals
  petal_order: top          # top | bottom | outside | front | random
  petal_interval: 0.15      # s between drones leaving the formation
  sway: 1.5                 # m of sideways sway
  color: "#303030"

audio: {file: music.mp3, start: 0.0}
location: {lat: 47.4979, lon: 19.0402, amsl: 110, orientation: 0}
```

## Formations

Every formation takes `center: [x, y, z]`; 2D shapes also take
`plane: xz | xy | yz` (default `xz`, a vertical plane facing the audience on the
-Y side), `rotation` (degrees within the plane) and `yaw` (degrees around Z).

| shape | parameters |
| --- | --- |
| `grid` | `spacing`, `columns` |
| `line` | `length` |
| `circle` | `radius`, `start_angle` |
| `polygon` | `radius`, `sides` |
| `star` | `radius`, `inner_ratio`, `spikes` |
| `heart` | `size` |
| `spiral` | `radius`, `turns` |
| `disc` | `radius` (filled) |
| `rectangle` | `width`, `height`, `filled` |
| `sphere` | `radius` |
| `cube` | `size` |
| `torus` | `radius`, `tube` |
| `helix` | `radius`, `height`, `turns` |
| `text` | `text` (Latin, Cyrillic, digits, `!?.,-+:'"/=#*♥`, `\n`), `height` |
| `svg` | `file` or `source`, `size`, `angle` (corner threshold) - provides colours |
| `image` | `file`, `size`, `threshold`, `invert` - provides colours (needs Pillow) |
| `points` | `points: [[x, y, z], ...]` (exactly one per drone) |

## Light effects

`lights` accepts a colour (`"#ff0080"`, `red`, `rgb(255, 0, 128)`) or an effect.
Every effect accepts `brightness` (0-1).

| effect | parameters |
| --- | --- |
| `solid` | `color` |
| `formation` | `fallback` - colours defined by SVG / image formations |
| `gradient` | `colors: [...]`, `axis: x | y | z | radial` |
| `rainbow` | `period`, `axis`, `spread`, `saturation` |
| `pulse` | `color`, `period`, `min`, `use_formation_colors` |
| `wave` | `colors: [...]`, `speed`, `wavelength`, `axis` |
| `sparkle` | `color`, `background`, `rate`, `flash`, `seed` |
| `fade` | `start`, `end`, `duration` |

## Motion

| kind | parameters |
| --- | --- |
| `rotate` | `rpm`, `center`, `ramp` |
| `breathe` | `amplitude` (relative), `period`, `ramp` |
| `wave` | `amplitude` (m), `wavelength`, `period`, `along: x | y | z`, `ramp` |

Motions start and stop smoothly; if a motion would exceed the speed or
acceleration limits, its ramps are lengthened and then its rate is reduced
(the build prints a note).
