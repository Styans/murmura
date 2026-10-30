# The `.skyc` compiled show format

A `.skyc` file is a ZIP archive (deflate compression) containing JSON documents
that reference each other with `{"$ref": "./path"}` links. Murmura reads and
writes the layout below; all fields not listed are ignored on read.

```text
show.json                          root document
cues.json                          time markers
cameras.json                       optional camera list
assets/music.mp3                   optional soundtrack
drones/<name>/trajectory.json      flight path
drones/<name>/lights.json          LED program
drones/<name>/yaw_control.json     optional heading setpoints
drones/<name>/pyro.json            optional pyro events
```

Coordinates are metres in a right-handed show frame (X, Y horizontal, Z up),
times are seconds from the start of the show.

## `show.json`

```json
{
  "version": 1,
  "settings": {
    "cues": {"$ref": "./cues.json"},
    "validation": {
      "maxAccelerationXY": 4.0, "maxAccelerationZ": 4.0, "maxAltitude": 150.0,
      "maxVelocityXY": 8.0, "maxVelocityZ": 3.0, "maxVelocityZUp": 2.5,
      "maxYawRate": 30.0, "minDistance": 3.0, "minNavAltitude": 2.5
    }
  },
  "swarm": {
    "drones": [
      {
        "type": "generic",
        "settings": {
          "trajectory": {"$ref": "./drones/Drone 1/trajectory.json#"},
          "lights": {"$ref": "./drones/Drone 1/lights.json#"},
          "yawControl": {"$ref": "./drones/Drone 1/yaw_control.json#"},
          "pyro": {"$ref": "./drones/Drone 1/pyro.json#"},
          "home": [0.0, 0.0, 0.0],
          "landAt": [0.0, 0.0, 0.0],
          "name": "Drone 1"
        }
      }
    ]
  },
  "environment": {
    "type": "outdoor",
    "cameras": {"$ref": "./cameras.json"},
    "location": {"origin": [474980000, 190400000, 120000], "orientation": 12.5}
  },
  "meta": {
    "id": "7614b2a1d934ee9a5b0b8b72730f69bb",
    "title": "My show",
    "timestampOffset": 1700000000.0,
    "segments": {"takeoff": [0.0, 10.0], "show": [18.0, 38.0], "landing": [40.5, 74.5]}
  },
  "media": {
    "audio": {"data": {"$ref": "./assets/music.mp3"}, "mediaType": "audio/mpeg", "startTime": 1.5}
  }
}
```

* `maxVelocityZUp` is optional; when missing, `maxVelocityZ` applies to climbing too.
* `home` is the first point of the trajectory, `landAt` the last one.
* `location.origin` is `[latitude·10⁷, longitude·10⁷, AMSL altitude in mm]`
  (altitude optional); `orientation` is the heading of the +X axis in degrees,
  clockwise from North.
* `segments` mark the takeoff, show and landing phases (all optional).

## `cues.json`

```json
{"version": 1, "items": [{"time": 0.0, "name": "Takeoff"}, {"time": 18.0, "name": "Ring"}]}
```

## `cameras.json`

```json
[{"type": "perspective", "position": [0, -50, 10], "orientation": [1.0, 0.0, 0.0, 0.0], "name": "Front"}]
```

`orientation` is a `(w, x, y, z)` quaternion.

## `trajectory.json`

```json
{
  "version": 1,
  "points": [
    [0.0,  [-1.5, -0.75, 0.0], []],
    [4.0,  [-1.5, -0.75, 6.0], [[-1.5, -0.75, 0.0], [-1.5, -0.75, 6.0]]],
    [12.0, [17.26, 2.27, 16.44], [[4.02, 0.14, 9.07]]],
    [31.75, [17.26, 2.27, 16.44], []]
  ],
  "takeoffTime": 6.0,
  "landingTime": 37.75
}
```

* Each point is `[t, position, controls]`. `controls` are the inner control
  points of the segment that ends at this point: none (straight line at
  constant speed), one (quadratic) or two (cubic Bézier). The first point
  never has controls.
* Segments are parametrised by time: for a segment from `t0` to `t1`,
  `u = (t - t0) / (t1 - t0)` is the Bézier parameter.
* Point times are **relative to `takeoffTime`**: the absolute show time of a
  point is `takeoffTime + t`. `takeoffTime` is the moment the drone first leaves
  its starting position; the hover before it is not stored.
* `landingTime` is the absolute time of the last point.
* A drone that never moves gets `takeoffTime = 0` and a single hover segment.

Murmura also accepts two *input-only* sample representations (used by design
tools sending raw samples to the planning server); samples are compressed into
Bézier segments with a configurable error bound (3 cm by default):

* version 0: `"points": [[t, x, y, z], ...]`
* version 2: `"points": "<base64 of little-endian float32 t, x, y, z quadruples>"`

## `lights.json`

```json
{"version": 1, "data": "BP8AAAAIAP8AZAgAAP9kC2QKMgmAMggKFB5LAvULAA=="}
```

`data` is base64-encoded LED bytecode. Durations are unsigned LEB128 varints
counted in frames of **1/50 s**. The program starts at show time 0.

| opcode | command | arguments |
| --- | --- | --- |
| `0x00` | END | |
| `0x01` | NOP | |
| `0x02` | SLEEP | duration |
| `0x03` | WAIT_UNTIL | absolute frame |
| `0x04` | SET_COLOR | r, g, b, duration |
| `0x05` | SET_GRAY | value, duration |
| `0x06` | SET_BLACK | duration |
| `0x07` | SET_WHITE | duration |
| `0x08` | FADE_TO_COLOR | r, g, b, duration |
| `0x09` | FADE_TO_GRAY | value, duration |
| `0x0A` | FADE_TO_BLACK | duration |
| `0x0B` | FADE_TO_WHITE | duration |
| `0x0C` | LOOP_BEGIN | iterations (1 byte, 0 = forever) |
| `0x0D` | LOOP_END | |
| `0x0E` | RESET_CLOCK | |
| `0x10` | SET_COLOR_FROM_CHANNELS | 3 channel indices, duration |
| `0x11` | FADE_TO_COLOR_FROM_CHANNELS | 3 channel indices, duration |
| `0x12` | JUMP | address |

`SET_*` switches the colour immediately and holds it for the duration;
`FADE_*` fades linearly from the current colour to the target over the duration.

Example decoding of the program above:

```text
04 ff 00 00 00      SET_COLOR (255,0,0) for 0 frames
08 00 ff 00 64      FADE_TO_COLOR (0,255,0) over 100 frames (2 s)
08 00 00 ff 64      FADE_TO_COLOR (0,0,255) over 2 s
0b 64               FADE_TO_WHITE over 2 s
0a 32               FADE_TO_BLACK over 1 s
09 80 32            FADE_TO_GRAY 128 over 1 s
08 0a 14 1e 4b      FADE_TO_COLOR (10,20,30) over 1.5 s
02 f5 0b            SLEEP 1525 frames (30.5 s)
00                  END
```

Writers extend the last colour until the end of the show. Drones without
lights omit the `lights` entry.

On input (render API), lights can also be given as keyframes:
`{"version": 1, "data": [[t, [r, g, b], fade], ...]}` where `fade` is 1 to fade
from the previous keyframe and 0 to switch abruptly at `t`.

## `yaw_control.json`

```json
{"version": 1, "setpoints": [[0, 0], [10, 90], [30, -45]], "autoYaw": false, "autoYawOffset": 0}
```

Setpoints are `[absolute time, heading in degrees clockwise]`.

## `pyro.json`

```json
{
  "version": 1,
  "events": [[12.0, 0, "payload1"]],
  "payloads": {
    "payload1": {"name": "Gerb", "prefireTime": 0.5, "duration": 5, "yaw": 0, "pitch": -90}
  }
}
```

Events are `[absolute time, zero-based channel, payload key]`.
