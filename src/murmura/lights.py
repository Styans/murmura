"""LED light programs: keyframes, simplification and the compact bytecode
used inside ``.skyc`` files.

Bytecode summary (all durations are unsigned LEB128 varints counted in
frames of 1/50 s):

======  =======================  ==========================
opcode  command                  arguments
======  =======================  ==========================
0x00    END
0x01    NOP
0x02    SLEEP                    duration
0x03    WAIT_UNTIL               absolute frame
0x04    SET_COLOR                r, g, b, duration
0x05    SET_GRAY                 value, duration
0x06    SET_BLACK                duration
0x07    SET_WHITE                duration
0x08    FADE_TO_COLOR            r, g, b, duration
0x09    FADE_TO_GRAY             value, duration
0x0A    FADE_TO_BLACK            duration
0x0B    FADE_TO_WHITE            duration
0x0C    LOOP_BEGIN               iterations (1 byte, 0 = forever)
0x0D    LOOP_END
0x0E    RESET_CLOCK
0x10    SET_COLOR_FROM_CHANNELS  3 channel indices, duration
0x11    FADE_COLOR_FROM_CHANNELS 3 channel indices, duration
0x12    JUMP                     address
======  =======================  ==========================

``SET_*`` commands switch the colour immediately and then hold it for the
given duration; ``FADE_*`` commands fade linearly from the current colour to
the target over the given duration.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from .colors import RGB, parse_color

__all__ = (
    "FPS",
    "LightKeyframe",
    "LightProgram",
    "Opcode",
    "decode_bytecode",
    "encode_bytecode",
)

FPS = 50
"""Number of bytecode frames per second."""


class Opcode(IntEnum):
    END = 0x00
    NOP = 0x01
    SLEEP = 0x02
    WAIT_UNTIL = 0x03
    SET_COLOR = 0x04
    SET_GRAY = 0x05
    SET_BLACK = 0x06
    SET_WHITE = 0x07
    FADE_TO_COLOR = 0x08
    FADE_TO_GRAY = 0x09
    FADE_TO_BLACK = 0x0A
    FADE_TO_WHITE = 0x0B
    LOOP_BEGIN = 0x0C
    LOOP_END = 0x0D
    RESET_CLOCK = 0x0E
    SET_COLOR_FROM_CHANNELS = 0x10
    FADE_TO_COLOR_FROM_CHANNELS = 0x11
    JUMP = 0x12


@dataclass(frozen=True)
class LightKeyframe:
    """Colour of the LED at time ``t``.

    If ``fade`` is true, the LED fades linearly from the previous keyframe's
    colour to this one; otherwise it keeps the previous colour until ``t`` and
    switches abruptly.
    """

    t: float
    color: RGB
    fade: bool = True


class LightProgram:
    """A sequence of colour keyframes with absolute (show-relative) times."""

    def __init__(self, keyframes: Iterable[LightKeyframe | Sequence] | None = None):
        items: list[LightKeyframe] = []
        for kf in keyframes or []:
            if isinstance(kf, LightKeyframe):
                items.append(kf)
            else:
                t, color, *rest = kf
                items.append(
                    LightKeyframe(float(t), parse_color(color), bool(rest[0]) if rest else True)
                )
        # Stable sort keeps the order of keyframes sharing the same timestamp
        self.keyframes: list[LightKeyframe] = sorted(items, key=lambda k: k.t)

    def __len__(self) -> int:
        return len(self.keyframes)

    def __bool__(self) -> bool:
        return bool(self.keyframes)

    def add(self, t: float, color, fade: bool = True) -> LightProgram:
        kf = LightKeyframe(float(t), parse_color(color), fade)
        if self.keyframes and kf.t < self.keyframes[-1].t:
            raise ValueError("light keyframes must be added in chronological order")
        self.keyframes.append(kf)
        return self

    def extend(self, other: Iterable[LightKeyframe]) -> LightProgram:
        for kf in other:
            self.add(kf.t, kf.color, kf.fade)
        return self

    @property
    def end_time(self) -> float:
        return self.keyframes[-1].t if self.keyframes else 0.0

    def color_at(self, t) -> np.ndarray:
        """Evaluates the colour at time(s) ``t``; returns an ``(k, 3)`` float array."""
        ts = np.atleast_1d(np.asarray(t, dtype=float))
        if not self.keyframes:
            return np.zeros((len(ts), 3))
        kt = np.array([k.t for k in self.keyframes])
        kc = np.array([k.color for k in self.keyframes], dtype=float)
        kf = np.array([k.fade for k in self.keyframes], dtype=bool)
        idx = np.searchsorted(kt, ts, side="right") - 1
        out = np.empty((len(ts), 3))
        before = idx < 0
        out[before] = kc[0]
        last = idx >= len(kt) - 1
        out[last & ~before] = kc[-1]
        mid = ~before & ~last
        if np.any(mid):
            i = idx[mid]
            span = kt[i + 1] - kt[i]
            ratio = np.where(span > 0, (ts[mid] - kt[i]) / np.where(span > 0, span, 1.0), 1.0)
            ratio = np.where(kf[i + 1], ratio, 0.0)
            out[mid] = kc[i] + (kc[i + 1] - kc[i]) * ratio[:, None]
        return out

    def simplified(self, tolerance: float = 2.0) -> LightProgram:
        """Returns an equivalent program with redundant keyframes removed.

        Keyframes are dropped if linear interpolation between their neighbours
        reproduces them within ``tolerance`` (in 0-255 units on any channel).
        """
        kfs = self.keyframes
        if len(kfs) <= 2:
            return LightProgram(kfs)

        # 1) collapse runs of identical colours, keeping both ends of the run
        collapsed: list[LightKeyframe] = [kfs[0]]
        for i in range(1, len(kfs)):
            kf = kfs[i]
            nxt = kfs[i + 1] if i + 1 < len(kfs) else None
            if kf.color == collapsed[-1].color and nxt is not None and nxt.color == kf.color:
                continue
            collapsed.append(kf)

        # 2) Douglas-Peucker on chains of consecutive fades
        result: list[LightKeyframe] = [collapsed[0]]
        i = 0
        n = len(collapsed)
        while i < n - 1:
            j = i + 1
            while j < n and collapsed[j].fade:
                j += 1
            # collapsed[i .. j-1] is a fade chain (collapsed[i] is its anchor)
            chain = collapsed[i:j]
            if len(chain) > 2:
                result.extend(_douglas_peucker(chain, tolerance)[1:])
            else:
                result.extend(chain[1:])
            if j < n:
                result.append(collapsed[j])  # step keyframe
            i = j
        return LightProgram(result)

    def shifted(self, dt: float) -> LightProgram:
        return LightProgram(LightKeyframe(k.t + dt, k.color, k.fade) for k in self.keyframes)

    # ------------------------------------------------------------------
    # Bytecode
    # ------------------------------------------------------------------

    def to_bytecode(self, end_time: float | None = None) -> bytes:
        return encode_bytecode(self.keyframes, end_time=end_time)

    @classmethod
    def from_bytecode(cls, data: bytes, *, max_time: float = 24 * 3600) -> LightProgram:
        return cls(_execute(decode_bytecode(data), max_time=max_time))


def _douglas_peucker(chain: list[LightKeyframe], tolerance: float) -> list[LightKeyframe]:
    times = np.array([k.t for k in chain])
    colors = np.array([k.color for k in chain], dtype=float)
    keep = np.zeros(len(chain), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(chain) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        span = times[b] - times[a]
        r = (times[a + 1 : b] - times[a]) / span if span > 0 else np.full(b - a - 1, 0.5)
        line = colors[a] + r[:, None] * (colors[b] - colors[a])
        err = np.max(np.abs(line - colors[a + 1 : b]), axis=1)
        k = int(np.argmax(err))
        if err[k] > tolerance:
            worst = a + 1 + k
            keep[worst] = True
            stack.append((a, worst))
            stack.append((worst, b))
    return [kf for kf, k in zip(chain, keep) if k]


# ----------------------------------------------------------------------
# Encoding
# ----------------------------------------------------------------------


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varints must be non-negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _frames(t: float) -> int:
    return int(round(t * FPS))


def _set_cmd(color: RGB, duration: int) -> bytes:
    r, g, b = color
    if r == g == b == 0:
        return bytes([Opcode.SET_BLACK]) + _varint(duration)
    if r == g == b == 255:
        return bytes([Opcode.SET_WHITE]) + _varint(duration)
    if r == g == b:
        return bytes([Opcode.SET_GRAY, r]) + _varint(duration)
    return bytes([Opcode.SET_COLOR, r, g, b]) + _varint(duration)


def _fade_cmd(color: RGB, duration: int) -> bytes:
    r, g, b = color
    if r == g == b == 0:
        return bytes([Opcode.FADE_TO_BLACK]) + _varint(duration)
    if r == g == b == 255:
        return bytes([Opcode.FADE_TO_WHITE]) + _varint(duration)
    if r == g == b:
        return bytes([Opcode.FADE_TO_GRAY, r]) + _varint(duration)
    return bytes([Opcode.FADE_TO_COLOR, r, g, b]) + _varint(duration)


def encode_bytecode(keyframes: Sequence[LightKeyframe], *, end_time: float | None = None) -> bytes:
    """Compiles light keyframes into bytecode.

    The colour before the first keyframe is the colour of the first keyframe.
    If ``end_time`` is later than the last keyframe, the last colour is held
    until then.
    """
    # Each entry: ["set"|"fade"|"sleep", color, frames]
    ops: list[list] = []
    if not keyframes:
        if end_time and end_time > 0:
            ops.append(["set", (0, 0, 0), _frames(end_time)])
    else:
        first = keyframes[0]
        ops.append(["set", first.color, max(0, _frames(first.t))])
        current_frame = max(0, _frames(first.t))
        current_color = first.color
        for kf in keyframes[1:]:
            frame = max(current_frame, _frames(kf.t))
            duration = frame - current_frame
            if kf.color == current_color:
                if duration:
                    ops.append(["sleep", None, duration])
            elif kf.fade and duration > 0:
                ops.append(["fade", kf.color, duration])
            else:
                if duration:
                    ops.append(["sleep", None, duration])
                ops.append(["set", kf.color, 0])
            current_frame = frame
            current_color = kf.color
        if end_time is not None and _frames(end_time) > current_frame:
            ops.append(["sleep", None, _frames(end_time) - current_frame])

    # Peephole: merge sleeps into the preceding command / each other
    merged: list[list] = []
    for op in ops:
        if op[0] == "sleep" and merged and merged[-1][0] in ("set", "sleep"):
            merged[-1][2] += op[2]
        else:
            merged.append(op)

    out = bytearray()
    for kind, color, duration in merged:
        if kind == "set":
            out += _set_cmd(color, duration)
        elif kind == "fade":
            out += _fade_cmd(color, duration)
        else:
            out += bytes([Opcode.SLEEP]) + _varint(duration)
    out.append(Opcode.END)
    return bytes(out)


# ----------------------------------------------------------------------
# Decoding
# ----------------------------------------------------------------------


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if i >= len(data):
            raise ValueError("truncated varint in light program")
        byte = data[i]
        i += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return result, i


def decode_bytecode(data: bytes) -> list[tuple]:
    """Decodes bytecode into a list of ``(address, opcode, *args)`` tuples."""
    commands: list[tuple] = []
    i = 0
    while i < len(data):
        addr = i
        op = data[i]
        i += 1
        if op in (Opcode.END, Opcode.NOP, Opcode.LOOP_END, Opcode.RESET_CLOCK):
            commands.append((addr, Opcode(op)))
            if op == Opcode.END:
                break
        elif op in (
            Opcode.SLEEP,
            Opcode.WAIT_UNTIL,
            Opcode.SET_BLACK,
            Opcode.SET_WHITE,
            Opcode.FADE_TO_BLACK,
            Opcode.FADE_TO_WHITE,
            Opcode.JUMP,
        ):
            value, i = _read_varint(data, i)
            commands.append((addr, Opcode(op), value))
        elif op in (Opcode.SET_GRAY, Opcode.FADE_TO_GRAY):
            gray = data[i]
            value, i = _read_varint(data, i + 1)
            commands.append((addr, Opcode(op), gray, value))
        elif op in (
            Opcode.SET_COLOR,
            Opcode.FADE_TO_COLOR,
            Opcode.SET_COLOR_FROM_CHANNELS,
            Opcode.FADE_TO_COLOR_FROM_CHANNELS,
        ):
            r, g, b = data[i], data[i + 1], data[i + 2]
            value, i = _read_varint(data, i + 3)
            commands.append((addr, Opcode(op), r, g, b, value))
        elif op == Opcode.LOOP_BEGIN:
            commands.append((addr, Opcode(op), data[i]))
            i += 1
        else:
            raise ValueError(f"unknown light program opcode 0x{op:02x} at offset {addr}")
    return commands


def _execute(commands: list[tuple], *, max_time: float) -> list[LightKeyframe]:
    """Runs decoded bytecode and records the resulting colour keyframes."""
    max_frame = _frames(max_time)
    by_addr = {c[0]: k for k, c in enumerate(commands)}
    frame = 0
    clock_origin = 0
    color: RGB = (0, 0, 0)
    out: list[LightKeyframe] = []
    loops: list[list[int]] = []  # [start_index, remaining]
    pc = 0
    steps = 0

    def emit(t_frame: int, c: RGB, fade: bool) -> None:
        out.append(LightKeyframe(t_frame / FPS, c, fade))

    while pc < len(commands) and frame <= max_frame and steps < 5_000_000:
        steps += 1
        cmd = commands[pc]
        op = cmd[1]
        pc += 1
        if op == Opcode.END:
            break
        if op == Opcode.SLEEP:
            frame += cmd[2]
        elif op == Opcode.WAIT_UNTIL:
            frame = max(frame, clock_origin + cmd[2])
        elif op in (
            Opcode.SET_COLOR,
            Opcode.SET_GRAY,
            Opcode.SET_BLACK,
            Opcode.SET_WHITE,
            Opcode.SET_COLOR_FROM_CHANNELS,
        ):
            color = _command_color(cmd)
            emit(frame, color, False)
            frame += cmd[-1]
        elif op in (
            Opcode.FADE_TO_COLOR,
            Opcode.FADE_TO_GRAY,
            Opcode.FADE_TO_BLACK,
            Opcode.FADE_TO_WHITE,
            Opcode.FADE_TO_COLOR_FROM_CHANNELS,
        ):
            if not out or _frames(out[-1].t) < frame:
                # the fade starts now: pin the colour held until this moment
                emit(frame, color, bool(out))
            frame += cmd[-1]
            color = _command_color(cmd)
            emit(frame, color, True)
        elif op == Opcode.LOOP_BEGIN:
            loops.append([pc, cmd[2] if cmd[2] > 0 else -1])
        elif op == Opcode.LOOP_END:
            if loops:
                start, remaining = loops[-1]
                if remaining == -1 or remaining > 1:
                    if remaining > 1:
                        loops[-1][1] -= 1
                    pc = start
                else:
                    loops.pop()
        elif op == Opcode.RESET_CLOCK:
            clock_origin = frame
        elif op == Opcode.JUMP:
            pc = by_addr.get(cmd[2], len(commands))
    if out and frame > _frames(out[-1].t):
        emit(frame, color, False)
    return out


def _command_color(cmd: tuple) -> RGB:
    op = cmd[1]
    if op in (Opcode.SET_BLACK, Opcode.FADE_TO_BLACK):
        return (0, 0, 0)
    if op in (Opcode.SET_WHITE, Opcode.FADE_TO_WHITE):
        return (255, 255, 255)
    if op in (Opcode.SET_GRAY, Opcode.FADE_TO_GRAY):
        return (cmd[2], cmd[2], cmd[2])
    if op in (Opcode.SET_COLOR_FROM_CHANNELS, Opcode.FADE_TO_COLOR_FROM_CHANNELS):
        # Channel values are unknown offline; render as white
        return (255, 255, 255)
    return (cmd[2], cmd[3], cmd[4])
