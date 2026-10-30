"""Packages the Blender add-on together with a copy of the Murmura engine.

    python blender/build_addon.py

creates ``dist/murmura-blender-<version>.zip``, installable in Blender 4.2+
via *Edit > Preferences > Get Extensions > Install from Disk*.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "blender" / "murmura_blender"
ENGINE = ROOT / "src" / "murmura"
SKIP_DIRS = {"__pycache__", "server"}


def _files(base: Path):
    for path in sorted(base.rglob("*")):
        if path.is_dir() or any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        yield path


def build(out_dir: Path | None = None) -> Path:
    manifest = (ADDON / "blender_manifest.toml").read_text(encoding="utf-8")
    version = re.search(r'^version\s*=\s*"([^"]+)"', manifest, re.M).group(1)
    out_dir = out_dir or ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"murmura-blender-{version}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _files(ADDON):
            rel = path.relative_to(ADDON)
            if rel.parts[0] == "murmura":
                continue  # stale bundled engine from a previous build
            zf.write(path, rel.as_posix())
        for path in _files(ENGINE):
            zf.write(path, ("murmura" / path.relative_to(ENGINE)).as_posix())
    return target


if __name__ == "__main__":
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")
