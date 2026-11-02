"""Murmura - open drone show choreography engine.

Design formations, plan collision-aware transitions, compose LED programs
and export compiled ``.skyc`` show files.
"""

__version__ = "0.1.1"

from .choreo import Motion, ShowBuilder
from .effects import make_effect
from .lights import LightKeyframe, LightProgram
from .model import Drone, SafetyLimits, Show
from .script import build_from_script
from .skyc import read_skyc, write_skyc
from .trajectory import Trajectory
from .validation import validate_show

__all__ = (
    "Drone",
    "LightKeyframe",
    "LightProgram",
    "Motion",
    "SafetyLimits",
    "Show",
    "ShowBuilder",
    "Trajectory",
    "__version__",
    "build_from_script",
    "make_effect",
    "read_skyc",
    "validate_show",
    "write_skyc",
)
