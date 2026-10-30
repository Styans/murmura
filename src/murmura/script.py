"""Declarative show scripts (YAML or JSON) compiled with :class:`ShowBuilder`.

See ``docs/show-script.md`` for the full reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .choreo import ShowBuilder, effect_or_default, make_motion
from .effects import make_effect
from .formations import grid, make_formation, min_spacing, scale_to_spacing
from .i18n import t
from .model import Audio, SafetyLimits, Show, ShowLocation

__all__ = ("ScriptError", "build_from_script", "load_script")


class ScriptError(ValueError):
    """Raised for invalid show scripts."""


def load_script(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        import json

        data = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as ex:  # pragma: no cover - depends on the environment
            raise ScriptError("YAML show scripts need PyYAML: pip install pyyaml") from ex
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ScriptError(t("a show script must be a mapping at the top level"))
    return data


def _limits(spec: dict[str, Any] | None) -> SafetyLimits:
    spec = dict(spec or {})
    acc = spec.pop("max_acceleration", None)
    if acc is not None:
        spec.setdefault("max_acceleration_xy", acc)
        spec.setdefault("max_acceleration_z", acc)
    known = SafetyLimits.__dataclass_fields__
    unknown = set(spec) - set(known)
    if unknown:
        raise ScriptError(t("unknown limit(s): {names}", names=", ".join(sorted(unknown))))
    return SafetyLimits(**{k: float(v) if v is not None else None for k, v in spec.items()})


def _home(spec: dict[str, Any] | None, n: int, limits: SafetyLimits, base: Path) -> np.ndarray:
    spec = spec or {}
    if "points" in spec:
        pts = np.asarray(spec["points"], dtype=float).reshape(-1, 3)
    elif "file" in spec:
        rows = [
            line.split(",")
            for line in (base / spec["file"]).read_text(encoding="utf-8").splitlines()
        ]
        pts = np.array(
            [[float(v) for v in r[-3:]] for r in rows if r and _numeric(r[-1])], dtype=float
        )
    else:
        g = dict(spec.get("grid", {}))
        g.setdefault("spacing", max(limits.min_distance, 1.5))
        pts = grid(n, **g)
    if len(pts) != n:
        raise ScriptError(
            t(
                "home layout has {count} positions but the show has {drones} drones",
                count=len(pts),
                drones=n,
            )
        )
    return pts


def _numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def build_from_script(
    script: dict[str, Any] | str | Path,
    *,
    base_dir: str | Path | None = None,
) -> tuple[Show, list[str]]:
    """Compiles a show script into a :class:`Show`.

    Returns the show and a list of planner notes and warnings.
    """
    if isinstance(script, (str, Path)):
        base = Path(base_dir) if base_dir else Path(script).resolve().parent
        script = load_script(script)
    else:
        base = Path(base_dir or ".")

    try:
        n = int(script["drones"])
    except (KeyError, TypeError, ValueError):
        raise ScriptError(t("'drones' (number of drones) is required")) from None

    limits = _limits(script.get("limits"))
    settings = dict(script.get("settings") or {})
    home = _home(script.get("home"), n, limits, base)
    builder = ShowBuilder(
        n,
        title=str(script.get("title", "Murmura show")),
        limits=limits,
        home=home,
        light_fps=float(settings.get("light_fps", 10)),
        motion_fps=float(settings.get("motion_fps", 8)),
        fit_tolerance=float(settings.get("fit_tolerance", 0.02)),
        profile=str(settings.get("profile", "smooth")),
        stagger=bool(settings.get("stagger", True)),
    )
    notes = builder.log

    takeoff = script.get("takeoff", {})
    if takeoff is not False:
        builder.takeoff(**dict(takeoff or {}))

    for index, item in enumerate(script.get("scenes") or []):
        if not isinstance(item, dict):
            raise ScriptError(t("scene #{index} must be a mapping", index=index + 1))
        if "wait" in item and "formation" not in item:
            builder.wait(
                float(item["wait"]),
                effect=make_effect(item["lights"]) if "lights" in item else None,
            )
            continue
        name = str(item.get("name", f"Scene {index + 1}"))
        if "formation" not in item:
            raise ScriptError(t("scene {name!r} has no formation", name=name))
        try:
            points, colors = make_formation(item["formation"], n, base_dir=base)
        except (TypeError, ValueError, OSError) as ex:
            raise ScriptError(t("scene {name!r}: {error}", name=name, error=ex)) from ex
        spacing = min_spacing(points)
        if spacing < limits.min_distance - 1e-6:
            if item.get("auto_scale", script.get("auto_scale", False)):
                # leave a 15% margin so that transitions have room to manoeuvre
                points = scale_to_spacing(points, limits.min_distance * 1.15)
                notes.append(
                    t(
                        "{name}: scaled up to keep {spacing:.2f} m spacing",
                        name=name,
                        spacing=limits.min_distance * 1.15,
                    )
                )
            else:
                notes.append(
                    t("warning")
                    + ": "
                    + t(
                        "{name}: formation spacing is {spacing:.2f} m, below the {minimum:g} m "
                        "minimum (set auto_scale: true to fix)",
                        name=name,
                        spacing=spacing,
                        minimum=limits.min_distance,
                    )
                )
        floor = float(np.min(home[:, 2])) + limits.min_nav_altitude + 1.0
        lowest = float(np.min(points[:, 2]))
        if lowest < floor:
            points = points + np.array([0.0, 0.0, floor - lowest])
            notes.append(
                t(
                    "{name}: lifted by {height:.1f} m to stay above the minimum altitude",
                    name=name,
                    height=floor - lowest,
                )
            )
        transition = dict(item.get("transition") or {})
        builder.scene(
            name,
            points,
            hold=float(item.get("hold", 5.0)),
            colors=colors,
            effect=effect_or_default(item.get("lights"), colors),
            motion=make_motion(item.get("motion")),
            transition_duration=transition.get("duration"),
            transition_effect=make_effect(transition["lights"]) if "lights" in transition else None,
            profile=transition.get("profile"),
            stagger=transition.get("stagger"),
            matching=str(transition.get("matching", "optimal")),
            start=item.get("start"),
        )

    landing = script.get("landing", {})
    if landing is not False:
        builder.land(**dict(landing or {}))

    audio = script.get("audio")
    if audio:
        path = base / audio["file"]
        builder.audio = Audio(
            data=path.read_bytes(),
            start_time=float(audio.get("start", 0.0)),
            filename=path.name,
            media_type="audio/mpeg"
            if path.suffix.lower() == ".mp3"
            else "audio/" + path.suffix.lower().lstrip("."),
        )
    location = script.get("location")
    if location:
        builder.location = ShowLocation(
            latitude=float(location["lat"]),
            longitude=float(location["lon"]),
            amsl=float(location["amsl"]) if location.get("amsl") is not None else None,
            orientation=float(location.get("orientation", 0.0)),
        )
    return builder.build(), notes
