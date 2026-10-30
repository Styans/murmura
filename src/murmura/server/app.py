"""HTTP planning server.

The REST API mirrors the operations a drone show design plugin needs:
rendering shows into ``.skyc`` / CSV / PDF, transition planning, point
matching, takeoff / landing planning, smart return-to-home and formations
from SVG drawings. Routes are served both at the root and under ``/api/v1``.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import time
import zipfile
from collections.abc import Callable
from importlib.util import find_spec
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..formations.svg import svg_points
from ..planning import (
    decompose_points,
    match_points,
    plan_landing,
    plan_smart_rth,
    plan_takeoff,
    plan_transition,
    synchronized_clearance,
)
from ..planning.matching import as_points
from ..render import UnsupportedFormatError, render_output, show_from_render_input
from ..script import ScriptError, build_from_script
from ..skyc import SkycError, write_skyc

__all__ = ("DEFAULT_COMPAT_VERSION", "create_app")

log = logging.getLogger("murmura.server")

DEFAULT_COMPAT_VERSION = "2.45.0"
"""API level reported by ``/queries/version``. Design plugins refuse backends
older than their minimum supported API level, so this is reported instead of
the package version (which is available at ``/murmura/info``)."""


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


async def _json_body(request: Request) -> Any:
    raw = await request.body()
    if request.headers.get("content-encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError as ex:
            raise ApiError(f"invalid gzip body: {ex}") from None
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError as ex:
        raise ApiError(f"invalid JSON body: {ex}") from None


def _require(body: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if k not in body]
    if missing:
        raise ApiError(f"missing field(s): {', '.join(missing)}")


def _features() -> list[str]:
    features = ["feat:pyro", "feat:yaw", "import:svg", "op:smart_rth"]
    if find_spec("matplotlib") is not None:
        features.append("export:plot")
    return sorted(features)


def create_app(*, compat_version: str = DEFAULT_COMPAT_VERSION, timeout: float = 600.0) -> FastAPI:
    app = FastAPI(
        title="Murmura planning server",
        version=__version__,
        description="Drone show planning and rendering API (.skyc, CSV, PDF reports).",
    )
    router = APIRouter()

    def operation(path: str, handler: Callable[[dict[str, Any]], Any]):
        async def endpoint(request: Request) -> Response:
            started = time.perf_counter()
            body = await _json_body(request)
            if not isinstance(body, dict):
                raise ApiError("request body must be a JSON object")
            result = await run_in_threadpool(handler, body)
            log.info("%s finished in %.2fs", path, time.perf_counter() - started)
            if isinstance(result, Response):
                return result
            return JSONResponse(result)

        endpoint.__name__ = "op_" + path.replace("-", "_").replace("/", "_")
        router.add_api_route(f"/operations/{path}", endpoint, methods=["POST"], summary=path)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @router.get("/ping", summary="Health check")
    async def ping():
        return {"result": True}

    @router.get("/validate-api-key", summary="Validate API key")
    async def validate_api_key():
        return {"result": True}

    @router.get("/queries/version", summary="API level")
    async def version():
        return {"version": compat_version}

    @router.get("/queries/limits", summary="Limits and features")
    async def limits():
        return {"num_drones": None, "features": _features(), "timeout": timeout}

    @router.get("/murmura/info", summary="Server information")
    async def info():
        return {
            "name": "murmura",
            "version": __version__,
            "api_level": compat_version,
            "features": _features(),
        }

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def render(body: dict[str, Any]) -> Response:
        _require(body, "input", "output")
        if body.get("transformations"):
            kinds = {t.get("type") for t in body["transformations"]} - {"null", None}
            if kinds:
                raise ApiError(f"transformations are not supported: {', '.join(sorted(kinds))}")
        show = show_from_render_input(body["input"])
        payload, media_type, filename = render_output(show, body["output"])
        return Response(
            payload,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def multi_render(body: dict[str, Any]) -> Response:
        _require(body, "input", "outputs")
        show = show_from_render_input(body["input"])
        buffer = io.BytesIO()
        stamp = time.strftime("%Y%m%d%H%M%S")
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for out in body["outputs"]:
                payload, _, filename = render_output(show, out)
                fmt = str(out.get("format", "skyc"))
                stem, _, ext = filename.rpartition(".")
                zf.writestr(f"{fmt}/{stem}-{stamp}.{ext}" if ext else f"{fmt}/{filename}", payload)
        return Response(buffer.getvalue(), media_type="application/zip")

    def transition(body: dict[str, Any]) -> dict[str, Any]:
        _require(body, "source", "target", "max_velocity_xy", "max_velocity_z", "max_acceleration")
        plan = plan_transition(
            body["source"],
            body["target"],
            max_velocity_xy=float(body["max_velocity_xy"]),
            max_velocity_z=float(body["max_velocity_z"]),
            max_acceleration=float(body["max_acceleration"]),
            max_velocity_z_up=body.get("max_velocity_z_up"),
            matching_method=str(body.get("matching_method", "optimal")),
            radius=body.get("radius"),
            min_distance=body.get("min_distance"),
            profile=str(body.get("velocity_profile", "smooth")),
        )
        return plan.to_json()

    def match(body: dict[str, Any]) -> dict[str, Any]:
        _require(body, "source", "target")
        source, target = as_points(body["source"]), as_points(body["target"])
        if str(body.get("method", "optimal")) == "fixed":
            mapping = [i if i < len(source) else None for i in range(len(target))]
        else:
            mapping = match_points(source, target)
        clearance = None
        radius = body.get("radius")
        if radius is not None:
            pairs = [(m, i) for i, m in enumerate(mapping) if m is not None]
            if len(pairs) >= 2:
                a = source[[m for m, _ in pairs]]
                b = target[[i for _, i in pairs]]
                value, _ = synchronized_clearance(a, b, radius)
                clearance = round(value, 3)
        return {"version": 1, "mapping": mapping, "clearance": clearance}

    def landing(body: dict[str, Any]) -> dict[str, Any]:
        _require(body, "points", "min_distance", "velocity")
        starts, durations = plan_landing(
            body["points"],
            min_distance=float(body["min_distance"]),
            velocity=float(body["velocity"]),
            target_altitude=float(body.get("target_altitude", 0.0)),
            spindown_time=float(body.get("spindown_time", 0.0)),
        )
        return {"version": 1, "start_times": starts, "durations": durations}

    def takeoff(body: dict[str, Any]) -> dict[str, Any]:
        _require(body, "points", "min_distance")
        groups = plan_takeoff(
            body["points"],
            min_distance=float(body["min_distance"]),
            downwash_radius=body.get("downwash_radius"),
        )
        return {"version": 1, "groups": groups}

    def decompose(body: dict[str, Any]) -> dict[str, Any]:
        _require(body, "points", "min_distance")
        groups = decompose_points(
            body["points"],
            min_distance=float(body["min_distance"]),
            method=str(body.get("method", "greedy")),
        )
        return {"version": 1, "groups": groups}

    def smart_rth(body: dict[str, Any]) -> dict[str, Any]:
        _require(
            body,
            "source",
            "target",
            "max_velocity_xy",
            "max_velocity_z",
            "max_acceleration",
            "min_distance",
        )
        plan = plan_smart_rth(
            body["source"],
            body["target"],
            max_velocity_xy=float(body["max_velocity_xy"]),
            max_velocity_z=float(body["max_velocity_z"]),
            max_acceleration=float(body["max_acceleration"]),
            min_distance=float(body["min_distance"]),
            rth_model=str(body.get("rth_model", "straight_line_with_neck")),
        )
        return plan.to_json()

    def static_formation(body: dict[str, Any]) -> dict[str, Any]:
        method = str(body.get("method", "svg"))
        if method != "svg":
            raise ApiError(f"unsupported formation method: {method!r}")
        params = body.get("parameters") or {}
        _require(params, "source", "n")
        uv, colors = svg_points(
            params["source"],
            int(params["n"]),
            size=float(params.get("size", 20.0)),
            angle=float(params.get("angle", 30.0)),
        )
        # Plugin convention: [vertical, horizontal (mirrored), 0]
        points = [[round(float(v), 4), round(float(-u), 4), 0] for u, v in uv]
        return {"version": 1, "points": points, "colors": [list(c) for c in colors]}

    def build(body: dict[str, Any]) -> Response:
        show, notes = build_from_script(body.get("script", body))
        return Response(
            write_skyc(show),  # type: ignore[arg-type]
            media_type="application/octet-stream",
            headers={"X-Murmura-Notes": json.dumps(notes)[:4000]},
        )

    operation("render", render)
    operation("multi-render", multi_render)
    operation("plan-transition", transition)
    operation("match-points", match)
    operation("plan-landing", landing)
    operation("plan-takeoff", takeoff)
    operation("decompose", decompose)
    operation("plan-smart-rth", smart_rth)
    operation("create-static-formation", static_formation)
    operation("build", build)

    app.include_router(router)
    app.include_router(router, prefix="/api/v1", include_in_schema=False)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    for error_type in (
        UnsupportedFormatError,
        SkycError,
        ScriptError,
        ValueError,
        KeyError,
        TypeError,
    ):

        async def _bad_request(request: Request, exc: Exception) -> JSONResponse:
            log.warning("bad request on %s: %s", request.url.path, exc)
            return JSONResponse({"detail": str(exc) or exc.__class__.__name__}, status_code=400)

        app.add_exception_handler(error_type, _bad_request)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        return _INDEX.format(
            version=__version__, api=compat_version, features=", ".join(_features())
        )

    return app


_INDEX = """<!doctype html><html><head><meta charset="utf-8"><title>Murmura server</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#1d2330}}
code{{background:#eef1f6;padding:1px 5px;border-radius:4px}}h1{{margin-bottom:4px}}</style></head>
<body><h1>Murmura planning server</h1><p>version {version} &middot; API level {api}</p>
<p>Features: {features}</p>
<p>Interactive API documentation: <a href="/docs">/docs</a></p>
<p>Point your drone show design plugin to <code>http://localhost:8000</code> to use this server
for transitions, takeoff / landing planning, return-to-home and <code>.skyc</code> export.</p>
</body></html>"""
