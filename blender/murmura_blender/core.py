"""Access to the Murmura engine.

Release builds ship a copy of the engine inside the add-on (``./murmura``).
During development the engine is imported from the Python environment or
from the repository's ``src`` folder.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

try:
    from . import murmura as engine  # bundled copy
except ImportError:
    try:
        import murmura as engine  # installed into Blender's Python
    except ImportError:
        _src = Path(__file__).resolve().parents[2] / "src"
        if (_src / "murmura").is_dir() and str(_src) not in sys.path:
            sys.path.insert(0, str(_src))
        import murmura as engine

# make the submodules used by the add-on available as attributes
for _name in (
    "_compat",
    "bezier",
    "utils",
    "model",
    "csvio",
    "skyc",
    "formations",
    "effects",
    "choreo",
    "validation",
    "viewer",
    "planning",
):
    importlib.import_module(f"{engine.__name__}.{_name}")

__all__ = ("engine",)
