"""Format conversions shared by the command line and the HTTP server."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from .csvio import read_csv_zip, write_csv_zip
from .model import Show
from .skyc import parse_show_spec, read_skyc, show_to_spec, write_skyc

__all__ = (
    "INPUT_FORMATS",
    "OUTPUT_FORMATS",
    "UnsupportedFormatError",
    "load_show",
    "render_output",
    "show_from_render_input",
)

INPUT_FORMATS = ("json", "skyc", "csv", "null")
OUTPUT_FORMATS = ("skyc", "csv", "plot", "json", "null")


class UnsupportedFormatError(ValueError):
    pass


def _decode_data(data: Any) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        return base64.b64decode(data)
    raise ValueError("binary input data must be a base64-encoded string")


def show_from_render_input(inp: dict[str, Any], *, tolerance: float = 0.03) -> Show:
    """Decodes the ``input`` part of a render request."""
    fmt = str(inp.get("format", "json")).lower()
    params = inp.get("parameters") or {}
    simplify = bool(params.get("simplify", True))
    data = inp.get("data")
    if fmt == "json":
        if isinstance(data, str):
            data = json.loads(data)
        return parse_show_spec(data, simplify=simplify, tolerance=tolerance)
    if fmt == "skyc":
        return read_skyc(_decode_data(data))
    if fmt == "csv":
        return read_csv_zip(_decode_data(data), simplify=simplify, tolerance=tolerance)
    if fmt == "null":
        return Show()
    raise UnsupportedFormatError(
        f"input format {fmt!r} is not supported (supported: {', '.join(INPUT_FORMATS)})"
    )


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "show"


def render_output(show: Show, out: dict[str, Any] | None = None) -> tuple[bytes, str, str]:
    """Renders a show into the requested output format.

    Returns the payload, its media type and a suggested file name.
    """
    out = out or {"format": "skyc"}
    fmt = str(out.get("format", "skyc")).lower()
    params = out.get("parameters") or {}
    name = _slug(show.title)
    if fmt == "skyc":
        return (
            write_skyc(show, ndigits=int(params.get("ndigits", 3))),
            "application/octet-stream",
            f"{name}.skyc",
        )  # type: ignore[return-value]
    if fmt == "csv":
        fps = float(params.get("fps", 4))
        return write_csv_zip(show, fps=fps), "application/zip", f"{name}.zip"
    if fmt == "plot":
        from .report import render_report_pdf

        fps = float(params.get("fps", 4) or 4)
        return render_report_pdf(show, dt=1.0 / fps), "application/octet-stream", f"{name}.pdf"
    if fmt == "json":
        return json.dumps(show_to_spec(show)).encode("utf-8"), "application/json", f"{name}.json"
    if fmt == "null":
        return b"", "application/octet-stream", name
    raise UnsupportedFormatError(
        f"output format {fmt!r} is not supported (supported: {', '.join(OUTPUT_FORMATS)})"
    )


def load_show(path: str | Path) -> Show:
    """Loads a show from ``.skyc``, a CSV ``.zip``, a JSON specification or a
    YAML / JSON show script."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".skyc":
        return read_skyc(p)
    if suffix == ".zip" or p.is_dir():
        return read_csv_zip(p, title=p.stem)
    if suffix in (".yaml", ".yml"):
        from .script import build_from_script

        return build_from_script(p)[0]
    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if "swarm" in data:
            return parse_show_spec(data)
        if "input" in data:
            return show_from_render_input(data["input"])
        from .script import build_from_script

        return build_from_script(data, base_dir=p.parent)[0]
    raise UnsupportedFormatError(f"don't know how to read {p.name!r}")
