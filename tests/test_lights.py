import base64

import numpy as np
import pytest

from murmura.lights import (
    FPS,
    LightKeyframe,
    LightProgram,
    Opcode,
    decode_bytecode,
    encode_bytecode,
)


def test_encodes_fades_with_specialised_opcodes():
    program = LightProgram(
        [
            [0, [255, 0, 0]],
            [2, [0, 255, 0]],
            [4, [0, 0, 255]],
            [6, [255, 255, 255]],
            [7, [0, 0, 0]],
            [8, [128, 128, 128]],
            [9.5, [10, 20, 30]],
            [40, [10, 20, 30]],
        ]
    )
    code = program.to_bytecode()
    assert base64.b64encode(code).decode() == "BP8AAAAIAP8AZAgAAP9kC2QKMgmAMggKFB5LAvULAA=="
    ops = [c[1] for c in decode_bytecode(code)]
    assert ops == [
        Opcode.SET_COLOR,
        Opcode.FADE_TO_COLOR,
        Opcode.FADE_TO_COLOR,
        Opcode.FADE_TO_WHITE,
        Opcode.FADE_TO_BLACK,
        Opcode.FADE_TO_GRAY,
        Opcode.FADE_TO_COLOR,
        Opcode.SLEEP,
        Opcode.END,
    ]


def test_hold_is_extended_until_end_time():
    code = LightProgram([[0, [255, 0, 0]]]).to_bytecode(end_time=9.0)
    assert code == bytes([Opcode.SET_COLOR, 255, 0, 0]) + bytes([0xC2, 0x03, Opcode.END])


def test_empty_program_is_black_until_end():
    assert encode_bytecode([], end_time=1.0) == bytes([Opcode.SET_BLACK, 50, Opcode.END])


def test_step_keyframe_keeps_previous_colour_until_switch():
    program = LightProgram(
        [LightKeyframe(0, (255, 0, 0)), LightKeyframe(2, (0, 0, 255), fade=False)]
    )
    colors = program.color_at([0.0, 1.0, 1.99, 2.0, 3.0])
    assert colors[1].tolist() == [255, 0, 0]
    assert colors[2].tolist() == [255, 0, 0]
    assert colors[3].tolist() == [0, 0, 255]
    decoded = LightProgram.from_bytecode(program.to_bytecode())
    assert decoded.color_at([1.0])[0].tolist() == [255, 0, 0]
    assert decoded.color_at([2.5])[0].tolist() == [0, 0, 255]


def test_fade_after_a_hold_starts_when_the_hold_ends():
    # red until 4 s (SET + SLEEP), then fade to blue between 4 s and 6 s
    program = LightProgram([[0, "red"], [4, "red"], [6, "blue"]])
    decoded = LightProgram.from_bytecode(program.to_bytecode())
    t = np.array([1.0, 3.9, 4.0, 5.0, 6.0])
    assert np.allclose(decoded.color_at(t), program.color_at(t))
    assert decoded.color_at([3.9])[0].tolist() == [255, 0, 0]


@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 16383, 16384, 2**21 + 5])
def test_long_durations_survive_roundtrip(value):
    t = value / FPS
    program = LightProgram([[0, [1, 2, 3]], [t, [9, 8, 7]]])
    decoded = LightProgram.from_bytecode(program.to_bytecode())
    assert decoded.keyframes[-1].t == pytest.approx(t)


def test_roundtrip_preserves_colours():
    rng = np.random.default_rng(3)
    times = np.cumsum(rng.uniform(0.1, 2.0, 60))
    keyframes = [
        LightKeyframe(
            float(t), tuple(int(v) for v in rng.integers(0, 256, 3)), bool(rng.random() < 0.7)
        )
        for t in times
    ]
    program = LightProgram(keyframes)
    decoded = LightProgram.from_bytecode(program.to_bytecode())
    sample = np.linspace(0, times[-1], 500)
    assert np.max(np.abs(program.color_at(sample) - decoded.color_at(sample))) <= 6.0


def test_simplify_drops_redundant_keyframes():
    t = np.linspace(0, 10, 101)
    program = LightProgram([LightKeyframe(float(x), (int(25 * x), 0, 0)) for x in t])
    simple = program.simplified(tolerance=2)
    assert len(simple) == 2
    assert np.max(np.abs(program.color_at(t) - simple.color_at(t))) <= 2.0


def test_unknown_opcode_is_rejected():
    with pytest.raises(ValueError):
        decode_bytecode(bytes([0x7F]))
