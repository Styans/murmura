"""Message translation (English and Russian).

Messages are written in English in the code and translated with :func:`t`.
The language is chosen with :func:`set_language`; :func:`detect_language`
picks it from the ``MURMURA_LANG`` environment variable or the operating
system's language.
"""

from __future__ import annotations

import locale
import os
import re
import sys

__all__ = ("LANGUAGES", "detect_language", "get_language", "is_warning", "set_language", "t")

LANGUAGES = ("en", "ru")
_language = "en"

RU: dict[str, str] = {
    # validation summary
    "Show: {title} - {drones} drones, {duration}": "Шоу: {title} - дронов: {drones}, длительность {duration}",
    "Max altitude": "Макс. высота",
    "Max horizontal speed": "Макс. гориз. скорость",
    "Max climb speed": "Макс. скорость набора",
    "Max descent speed": "Макс. скорость снижения",
    "Max horizontal accel.": "Макс. гориз. ускорение",
    "Max vertical accel.": "Макс. верт. ускорение",
    "Min distance (airborne)": "Мин. дистанция в воздухе",
    "Min altitude during show": "Мин. высота во время шоу",
    "Max yaw rate": "Макс. скорость рысканья",
    "limit": "лимит",
    "{count} violation(s)": "нарушений: {count}",
    " at t={time:.2f}s ({a} / {b})": " в t={time:.2f} с ({a} / {b})",
    "RESULT: PASSED": "ИТОГ: ПРОЙДЕНО",
    "RESULT: FAILED": "ИТОГ: НЕ ПРОЙДЕНО",
    "PASSED": "ПРОЙДЕНО",
    "FAILED": "НЕ ПРОЙДЕНО",
    "FAIL": "ОШИБ",
    " OK ": " OK ",
    "m": "м",
    "m/s": "м/с",
    "m/s2": "м/с²",
    "deg/s": "°/с",
    "{check}: {value:.2f} (limit {limit:.2f}) at t={time:.2f}s, {who}": "{check}: {value:.2f} (лимит {limit:.2f}) в t={time:.2f} с, {who}",
    "altitude": "высота",
    "velocity_xy": "гориз. скорость",
    "velocity_z_up": "скорость набора",
    "velocity_z_down": "скорость снижения",
    "acceleration_xy": "гориз. ускорение",
    "acceleration_z": "верт. ускорение",
    "distance": "дистанция",
    "nav_altitude": "мин. высота",
    "yaw_rate": "скорость рысканья",
    # planner notes
    "warning": "внимание",
    "takeoff": "взлёт",
    "return": "возврат",
    "approach": "заход на посадку",
    "transition": "переход",
    "takeoff in {count} waves, layers {gap:.1f} m apart": "взлёт в {count} волны (по очереди), слои через {gap:.1f} м",
    "{name}: drones arrive {late:.1f} s after the binding starts": "{name}: дроны долетают на {late:.1f} с позже начала привязки",
    "{name}: the model moves faster than the drones may fly ({speed:.1f} m/s); slow its animation down": "{name}: модель движется быстрее, чем могут лететь дроны ({speed:.1f} м/с) - замедлите её анимацию",
    "landing in {count} waves": "посадка в {count} волны (по очереди)",
    "return: the swarm re-forms into its home grid in the air ({count} rows) and keeps {clearance:.2f} m": "возврат: рой перестраивается в воздухе в «дома» (рядов: {count}) и держит {clearance:.2f} м",
    "return: crumbling is not possible here, the swarm re-forms into its homes": "возврат: рассыпание здесь невозможно - рой перестраивается в «дома»",
    "return like falling petals: drones leave one by one over {seconds:.0f} s and land at once": "возврат «лепестками»: дроны по одному отрываются от фигуры за {seconds:.0f} с и сразу садятся",
    "return: drones land on the nearest free spots, their own were not safe": "возврат: дроны сядут на ближайшие свободные места - на свои вернуться безопасно не получилось",
    "{label}: requested {requested:.2f}s is too short, using {used:.2f}s": "{label}: запрошенные {requested:.2f} с - слишком мало, используется {used:.2f} с",
    "{label}: {plan} transition keeps {separation:.2f} m separation": "{label}: {plan} переход сохраняет дистанцию {separation:.2f} м",
    "{label}: could only keep {separation:.2f} m between drones (minimum {minimum:g} m)": "{label}: удалось сохранить только {separation:.2f} м между дронами (минимум {minimum:g} м)",
    "{kind} motion slowed down to respect the speed limit": "движение «{kind}» замедлено, чтобы не превысить скорость",
    "{kind} motion softened to respect the acceleration limit": "движение «{kind}» смягчено, чтобы не превысить ускорение",
    "rotate": "вращение",
    "breathe": "дыхание",
    "wave": "волна",
    "synchronised": "синхронный",
    "vertical first": "сначала по вертикали",
    "horizontal first": "сначала по горизонтали",
    "staggered": "со сдвигом старта",
    "{count} lanes": "по дорожкам ({count})",
    "via {factor}x spread": "через растяжку ×{factor}",
    "{name}: scaled up to keep {spacing:.2f} m spacing": "{name}: фигура увеличена для шага {spacing:.2f} м",
    "{name}: formation spacing is {spacing:.2f} m, below the {minimum:g} m minimum (set auto_scale: true to fix)": "{name}: шаг фигуры {spacing:.2f} м меньше минимума {minimum:g} м (включите auto_scale: true)",
    "{name}: lifted by {height:.1f} m to stay above the minimum altitude": "{name}: поднята на {height:.1f} м, чтобы не опускаться ниже минимальной высоты",
    # script errors
    "'drones' (number of drones) is required": "нужно указать 'drones' (число дронов)",
    "scene {name!r} has no formation": "у сцены {name!r} нет фигуры (formation)",
    "scene #{index} must be a mapping": "сцена №{index} должна быть словарём",
    "unknown limit(s): {names}": "неизвестные ограничения: {names}",
    "home layout has {count} positions but the show has {drones} drones": "в стартовой сетке {count} точек, а дронов {drones}",
    "a show script must be a mapping at the top level": "сценарий шоу должен быть словарём на верхнем уровне",
    "scene {name!r}: {error}": "сцена {name!r}: {error}",
    # command line
    "note": "заметка",
    "error": "ошибка",
    "Wrote {path} ({size:.1f} KiB, {drones} drones, {duration:.1f} s)": "Записан {path} ({size:.1f} КБ, дронов: {drones}, {duration:.1f} с)",
    "Wrote {path}": "Записан {path}",
    "Built in {seconds:.1f} s": "Собрано за {seconds:.1f} с",
    "Validation report written to {path}": "Отчёт о проверке записан в {path}",
    "Sent to the viewer at {url}": "Шоу отправлено в просмотрщик: {url}",
    "Preview failed: {error}": "Не удалось открыть предпросмотр: {error}",
    "no show viewer found on this machine; is it running?": "просмотрщик шоу на этом компьютере не найден - он запущен?",
    "could not reach the viewer at {url}: {reason}": "не удалось связаться с просмотрщиком {url}: {reason}",
    "viewer rejected the show: {result}": "просмотрщик отклонил шоу: {result}",
    "Title:": "Название:",
    "Drones:": "Дронов:",
    "Duration:": "Длительность:",
    "Segment:": "Участок:",
    "Cues:": "Метки:",
    "Audio:": "Звук:",
    "Location:": "Место:",
    "Extras:": "Дополнительно:",
    "Trajectory segments: {segments}, light keyframes: {keyframes}": "Сегментов траекторий: {segments}, ключей света: {keyframes}",
    "heading {heading:.1f} deg": "курс {heading:.1f}°",
    "The server needs extra packages: pip install murmura[server]": "Серверу нужны дополнительные пакеты: pip install murmura[server]",
    "Murmura planning server {version} on http://{host}:{port}  (API docs: /docs)": "Сервер планирования Murmura {version}: http://{host}:{port}  (документация API: /docs)",
    "Output must end with .skyc, .zip (CSV), .pdf (report) or .json": "Выходной файл должен оканчиваться на .skyc, .zip (CSV), .pdf (отчёт) или .json",
    "Wrote {count} points to {path}": "Записано точек: {count} в {path}",
    "Drone show choreography engine": "Движок хореографии дрон-шоу",
    "interface language: auto, en or ru": "язык интерфейса: auto, en или ru",
    "compile a YAML/JSON show script into .skyc": "собрать шоу из сценария YAML/JSON в .skyc",
    "build the built-in 100-drone demo show": "собрать встроенное демо-шоу на 100 дронов",
    "run the planning server for design plugins": "запустить сервер планирования для дополнений",
    "print a summary of a show file": "показать сводку по файлу шоу",
    "check a show against its safety limits": "проверить шоу на соответствие ограничениям безопасности",
    "convert between .skyc, CSV .zip, .json and PDF report": "конвертировать между .skyc, CSV .zip, .json и PDF-отчётом",
    "send a .skyc file to a running show viewer": "отправить .skyc в запущенный просмотрщик",
    "export a formation as a static CSV (Name,x,y,z,R,G,B)": "выгрузить фигуру в статический CSV (Name,x,y,z,R,G,B)",
    "output .skyc file": "выходной файл .skyc",
    "also write a CSV archive (.zip)": "также записать CSV-архив (.zip)",
    "CSV sampling rate (default: 4)": "частота строк CSV (по умолчанию 4)",
    "write a PDF validation report": "записать PDF-отчёт о проверке",
    "write the validation result as JSON": "записать результат проверки в JSON",
    "open the result in a running show viewer": "открыть результат в запущенном просмотрщике",
    "exit with status 1 if validation fails": "завершиться с кодом 1, если проверка не пройдена",
    "API level reported to clients": "уровень API, сообщаемый клиентам",
    "sampling interval in seconds": "шаг выборки в секундах",
    "write a PDF report": "записать PDF-отчёт",
    "write a JSON report": "записать JSON-отчёт",
    "circle, heart, star, sphere, text, svg, image, ...": "circle, heart, star, sphere, text, svg, image, ...",
    "number of points": "число точек",
    "shape parameter, e.g. radius=15 or center=[0,0,30]": "параметр фигуры, например radius=15 или center=[0,0,30]",
    # PDF report
    "Validation report - {title}": "Отчёт о проверке - {title}",
    "First violations:": "Первые нарушения:",
    "Max altitude [m]": "Макс. высота [м]",
    "Max horizontal speed [m/s]": "Макс. гориз. скорость [м/с]",
    "Max vertical speed [m/s]": "Макс. верт. скорость [м/с]",
    "Max acceleration [m/s²]": "Макс. ускорение [м/с²]",
    "Min distance (airborne) [m]": "Мин. дистанция в воздухе [м]",
    "Time [s]": "Время [с]",
    "Safety envelope over time": "Ограничения безопасности во времени",
    "Top view (X / Y)": "Вид сверху (X / Y)",
    "Front view (X / Z)": "Вид спереди (X / Z)",
    # default cue names
    "Takeoff": "Взлёт",
    "s": "с",
    "show": "шоу",
    "landing": "посадка",
    "yaw": "рысканье (yaw)",
    "pyro": "пиротехника",
    "Landing": "Посадка",
}


def set_language(language: str | None) -> str:
    """Selects the message language (``en`` or ``ru``; ``auto`` or ``None``
    detects it) and returns the language now in use."""
    global _language
    lang = (language or "auto").lower()
    if lang == "auto":
        lang = detect_language()
    _language = "ru" if lang.startswith("ru") else "en"
    return _language


def get_language() -> str:
    return _language


def _system_language() -> str:
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if lang_id & 0x3FF == 0x19:  # LANG_RUSSIAN
                return "ru"
        except (AttributeError, OSError):
            pass
    for value in (os.environ.get("LC_ALL"), os.environ.get("LC_MESSAGES"), os.environ.get("LANG")):
        if value:
            return value
    try:
        return locale.getlocale()[0] or ""
    except ValueError:
        return ""


def detect_language() -> str:
    """``MURMURA_LANG`` if set, otherwise the language of the system."""
    value = os.environ.get("MURMURA_LANG") or _system_language()
    return "ru" if value.lower().startswith(("ru", "russian")) else "en"


def t(message: str, **kwargs) -> str:
    """Translates ``message`` and formats it with ``kwargs``."""
    text = RU.get(message, message) if _language == "ru" else message
    return text.format(**kwargs) if kwargs else text


def is_warning(note: str) -> bool:
    return note.startswith(("warning:", "внимание:"))


_PLAN = re.compile(
    r"^(?:(\d+) lanes|via ([\d.]+)x spread|(synchronised|vertical first|horizontal first)"
    r"|(staggered))( \+ staggered)?$"
)


def plan_label(label: str) -> str:
    """Translates the label of a transition plan."""
    m = _PLAN.match(label)
    if not m:
        return label
    if m.group(1):
        text = t("{count} lanes", count=m.group(1))
    elif m.group(2):
        text = t("via {factor}x spread", factor=m.group(2))
    else:
        text = t(m.group(3) or m.group(4))
    if m.group(5):
        text += " + " + t("staggered")
    return text
