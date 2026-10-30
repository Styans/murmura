# Planning server API

```bash
murmura serve --host 127.0.0.1 --port 8000
```

All routes are available both at the root and under `/api/v1`. Request bodies
are JSON and may be gzip-compressed (`Content-Encoding: gzip`). Errors are
returned with status 400 and a `{"detail": "..."}` body. Interactive
documentation is served at `/docs`.

`/queries/version` reports an *API level* (default `2.45.0`, change it with
`--compat-version`) because design plugins refuse backends below their
minimum supported level. The package version is available at `/murmura/info`.

## Queries

| Route | Response |
| --- | --- |
| `GET /ping` | `{"result": true}` |
| `GET /validate-api-key` | `{"result": true}` |
| `GET /queries/version` | `{"version": "2.45.0"}` |
| `GET /queries/limits` | `{"num_drones": null, "features": ["export:plot", "feat:pyro", "feat:yaw", "import:svg", "op:smart_rth"], "timeout": 600}` |
| `GET /murmura/info` | package name, version, API level and features |

## `POST /operations/render`

```json
{
  "input": {"format": "json", "data": { "...show specification..." }, "parameters": {"simplify": true}},
  "output": {"format": "skyc", "parameters": {}},
  "transformations": []
}
```

* input formats: `json` (show specification, see [skyc-format.md](skyc-format.md),
  inline or with sampled trajectories), `skyc` and `csv` (base64 data), `null`
* output formats: `skyc`, `csv` (ZIP of per-drone CSV, parameter `fps`),
  `plot` (PDF validation report, parameter `fps`), `json`, `null`

## `POST /operations/multi-render`

Same as `render` with `"outputs": [{"format": ...}, ...]`. Returns a ZIP with
one file per output under `<format>/`.

## `POST /operations/plan-transition`

```json
{"version": 1, "source": [[0,0,10], ...], "target": [[6,3,15], ...],
 "max_velocity_xy": 8, "max_velocity_z": 2, "max_velocity_z_up": 1.5, "max_acceleration": 4,
 "matching_method": "optimal", "radius": 0.5, "min_distance": 3, "velocity_profile": "smooth"}
```

Response: `{"version": 1, "start_times": [...], "durations": [...], "mapping": [...], "clearance": 1.121}`.
The i-th entries describe the drone flying to the i-th target; `mapping[i]` is
the index of its source point. `mapping` is omitted for `"matching_method": "fixed"`,
`clearance` only appears when `radius` is given. With `min_distance`, conflicting
drones get start delays. Profiles: `smooth`, `linear`, `ease_in`, `ease_out`.

## `POST /operations/match-points`

`{"version": 1, "source": [...], "target": [...], "radius": 0.5}` →
`{"version": 1, "mapping": [...], "clearance": 1.121}`

## `POST /operations/plan-takeoff`

`{"version": 1, "points": [...], "min_distance": 2, "downwash_radius": null}` →
`{"version": 1, "groups": [0, 2, 0, 1, ...]}` - drones in the same group are
horizontally at least `min_distance` (and `downwash_radius`) apart.

## `POST /operations/decompose`

`{"version": 1, "points": [...], "min_distance": 2, "method": "greedy" | "balanced"}` →
`{"version": 1, "groups": [...]}`

## `POST /operations/plan-landing`

`{"version": 1, "points": [...], "min_distance": 3, "velocity": 1.5, "target_altitude": 0, "spindown_time": 5}` →
`{"version": 1, "start_times": [...], "durations": [...]}`

## `POST /operations/plan-smart-rth`

```json
{"version": 1, "source": [...], "target": [...], "max_velocity_xy": 5, "max_velocity_z": 2,
 "max_acceleration": 3, "min_distance": 3, "rth_model": "straight_line_with_neck"}
```

Response: `start_times`, `durations` and `inner_points` (per drone, a list of
`[t, x, y, z]` relative to its own start). Models: `straight_line_with_neck`,
`straight_line_with_neck_to_layers`.

## `POST /operations/create-static-formation`

```json
{"version": 1, "method": "svg",
 "parameters": {"version": 1, "source": "<svg ...>", "n": 100, "size": 20, "angle": 30}}
```

Response: `{"version": 1, "points": [[v, -u, 0], ...], "colors": [[r, g, b], ...]}` -
the point order and axes follow the convention expected by the Blender add-on
(first coordinate up, second horizontal).

## `POST /operations/build`

Murmura extension: compiles a [show script](show-script.md) given as JSON and
returns the `.skyc` file. Planner notes are returned in the `X-Murmura-Notes` header.
