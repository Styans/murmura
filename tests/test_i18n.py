import ast
import re
from pathlib import Path

import pytest

from murmura import i18n
from murmura.cli import DEMO_SCRIPT
from murmura.script import build_from_script
from murmura.validation import validate_show

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "murmura"
ADDON = ROOT / "blender" / "murmura_blender"


@pytest.fixture
def russian():
    i18n.set_language("ru")
    yield
    i18n.set_language("en")


def _dict_from_source(path: Path, name: str) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def _calls(path: Path, func: str) -> set[str]:
    """String literals passed as the first argument to ``func(...)``."""
    found = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == func
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found


def test_every_engine_message_has_a_russian_translation():
    missing = set()
    for path in ENGINE.rglob("*.py"):
        for alias in ("t", "tr"):
            missing |= {m for m in _calls(path, alias) if m not in i18n.RU}
    assert not missing, sorted(missing)


def test_every_addon_string_has_a_russian_translation():
    ru = _dict_from_source(ADDON / "i18n.py", "RU")
    wanted: set[str] = set()
    for path in ADDON.glob("*.py"):
        if path.name == "i18n.py":
            continue
        text = path.read_text(encoding="utf-8")
        wanted |= _calls(path, "tr")
        wanted |= set(re.findall(r'\bname="([^"]+)"', text))
        wanted |= set(re.findall(r'\bdescription=\s*"([^"]+)"', text))
        wanted |= set(re.findall(r'\bbl_label = "([^"]+)"', text))
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.startswith("MURMURA_OT_"):
                doc = ast.get_docstring(node)
                if doc:
                    wanted.add(doc.strip())
    props = ADDON / "props.py"
    for list_name in ("SHAPES", "PLANES", "EFFECTS", "AXES", "MOTIONS"):
        for _, label, description in _dict_from_source(props, list_name):
            wanted |= {label, description} - {""}
    untranslatable = {"X", "Y", "Z", "SVG", "Language / Язык", "Murmura"}
    missing = sorted(w for w in wanted if w not in ru and w not in untranslatable)
    assert not missing, missing


def test_validation_summary_in_russian(russian):
    show, notes = build_from_script(DEMO_SCRIPT)
    summary = validate_show(show).summary()
    assert "Мин. дистанция в воздухе" in summary
    assert "ИТОГ: ПРОЙДЕНО" in summary
    assert any("переход сохраняет дистанцию" in note for note in notes)
    assert [c.name for c in show.cues][0] == "Взлёт"


def test_plan_labels_and_warnings(russian):
    assert i18n.plan_label("2 lanes + staggered") == "по дорожкам (2) + со сдвигом старта"
    assert i18n.plan_label("via 1.6x spread") == "через растяжку ×1.6"
    assert i18n.is_warning(i18n.t("warning") + ": x")


def test_language_selection(monkeypatch):
    monkeypatch.setenv("MURMURA_LANG", "ru")
    assert i18n.set_language("auto") == "ru"
    monkeypatch.setenv("MURMURA_LANG", "en")
    assert i18n.set_language("auto") == "en"
    assert i18n.set_language("ru_RU") == "ru"
    i18n.set_language("en")
    assert i18n.t("Max altitude") == "Max altitude"
