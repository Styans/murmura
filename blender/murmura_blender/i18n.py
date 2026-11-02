"""Interface language of the add-on (English / Russian).

The add-on chooses its language independently of Blender's interface
language: *Auto* uses Russian when Blender or the operating system is in
Russian. Property names, descriptions, enum items and operator labels are
translated when the classes are registered; switching the language
re-registers them.
"""

import bpy

from .core import engine

LANGUAGES = [
    (
        "AUTO",
        "Auto / Авто",
        "Russian if Blender or the system is in Russian / Русский, если Blender или система на русском",
    ),
    ("RU", "Русский", "Russian interface"),
    ("EN", "English", "English interface"),
]

_override: str | None = None
_current = "en"

RU: dict[str, str] = {
    # panels and labels
    "Drones": "Дроны",
    "Formations": "Фигуры",
    "Storyboard": "Сценарий",
    "Safety & Export": "Безопасность и экспорт",
    "Report": "Отчёт",
    "Language": "Язык",
    "{count} drones in the scene": "Дронов в сцене: {count}",
    "No drones yet": "Дронов пока нет",
    "Clear Animation": "Очистить анимацию",
    "Height": "Высота",
    "CSV": "CSV",
    "Scene {index}": "Сцена {index}",
    # shapes
    "Circle": "Круг",
    "Ring of drones": "Кольцо из дронов",
    "Heart": "Сердце",
    "Heart outline": "Контур сердца",
    "Star": "Звезда",
    "Five-pointed star outline": "Контур пятиконечной звезды",
    "Polygon": "Многоугольник",
    "Regular polygon outline": "Контур правильного многоугольника",
    "Spiral": "Спираль",
    "Flat spiral": "Плоская спираль",
    "Line": "Линия",
    "Straight line": "Прямая линия",
    "Rectangle": "Прямоугольник",
    "Rectangle outline": "Контур прямоугольника",
    "Disc": "Диск",
    "Filled disc": "Заполненный круг",
    "Grid": "Сетка",
    "Horizontal grid": "Горизонтальная сетка",
    "Sphere": "Сфера",
    "Points on a sphere": "Точки на сфере",
    "Cube": "Куб",
    "Points on a cube": "Точки на поверхности куба",
    "Torus": "Тор",
    "Points on a torus": "Точки на торе",
    "Helix": "Винтовая линия",
    "3D helix": "Объёмная спираль",
    "Text": "Текст",
    "Text with the built-in font (Latin and Cyrillic)": "Текст встроенным шрифтом (латиница и кириллица)",
    "SVG": "SVG",
    "Outline of an SVG drawing, with its colours": "Контур рисунка SVG с его цветами",
    "Image": "Картинка",
    "Bright pixels of an image, with their colours": "Яркие пиксели изображения с их цветами",
    # planes
    "Front (XZ)": "Спереди (XZ)",
    "Vertical plane facing the -Y side": "Вертикальная плоскость, обращённая к стороне -Y",
    "Side (YZ)": "Сбоку (YZ)",
    "Vertical plane facing the +X side": "Вертикальная плоскость, обращённая к стороне +X",
    "Ground (XY)": "Горизонтально (XY)",
    "Horizontal plane": "Горизонтальная плоскость",
    # effects
    "Solid": "Цвет",
    "One colour": "Один цвет",
    "Formation colours": "Цвета фигуры",
    "Colours stored in the formation (SVG / image)": "Цвета, сохранённые в фигуре (SVG / картинка)",
    "Gradient": "Градиент",
    "Gradient between two colours along an axis": "Градиент между двумя цветами вдоль оси",
    "Rainbow": "Радуга",
    "Moving rainbow": "Бегущая радуга",
    "Pulse": "Пульсация",
    "Breathing brightness": "Дышащая яркость",
    "Wave": "Волна",
    "Colour wave travelling along an axis": "Цветовая волна вдоль оси",
    "Sparkle": "Мерцание",
    "Random twinkles": "Случайные вспышки",
    "Fade": "Переход цвета",
    "Fade from the first to the second colour": "Плавный переход от первого цвета ко второму",
    "Radial": "Радиально",
    # motions
    "None": "Нет",
    "Static formation": "Неподвижная фигура",
    "Rotate": "Вращение",
    "Spin around the vertical axis (rate = rpm)": "Вращение вокруг вертикальной оси (скорость = об/мин)",
    "Breathe": "Дыхание",
    "Scale in and out (rate = relative amplitude)": "Сжатие и расширение (скорость = относительная амплитуда)",
    "Vertical wave (rate = amplitude in metres)": "Вертикальная волна (скорость = амплитуда в метрах)",
    # landing
    "Nearest spot": "Ближайшая точка",
    "Drones land on the nearest free spots (shorter return)": "Дроны садятся на ближайшие свободные места (возврат короче)",
    "Own spot": "Своя точка",
    "Every drone flies back the way it came to the point it took off from and lands there": "Каждый дрон летит обратно тем же путём к точке, откуда взлетел, и садится на своё место",
    # storyboard entry
    "Name": "Название",
    "Formation": "Фигура",
    "Hold": "Время в фигуре",
    "Time spent in the formation": "Время в фигуре",
    "Fixed start": "Фикс. старт",
    "Start the transition at a fixed time": "Начать переход в заданное время",
    "Start": "Старт",
    "Min. transition": "Мин. переход",
    "Minimum transition duration (0 = as fast as the limits allow)": "Минимальная длительность перехода (0 - так быстро, как позволяют ограничения)",
    "Lights": "Свет",
    "Colour": "Цвет",
    "Colour 2": "Цвет 2",
    "Period": "Период",
    "Period / speed of animated effects": "Период / скорость анимированных эффектов",
    "Axis": "Ось",
    "Motion": "Движение",
    "Rate": "Скорость",
    # settings
    "Spacing": "Шаг",
    "Columns": "Столбцов",
    "0 = square grid": "0 - квадратная сетка",
    "Shape": "Фигура",
    "Size": "Размер",
    "Radius or overall size": "Радиус или общий размер",
    "Plane": "Плоскость",
    "Centre": "Центр",
    "File": "Файл",
    "Keep spacing": "Соблюдать шаг",
    "Enlarge the formation if its points are closer than the minimum distance": "Увеличить фигуру, если её точки ближе минимальной дистанции",
    "Takeoff altitude": "Высота взлёта",
    "Landing speed": "Скорость посадки",
    "Spin-down": "Остановка моторов",
    "Time between touchdowns of neighbours": "Время между посадками соседних дронов",
    "Land on": "Посадка на",
    "Max speed XY": "Макс. скорость XY",
    "Max speed Z": "Макс. скорость Z",
    "Max climb": "Макс. набор высоты",
    "Max acceleration": "Макс. ускорение",
    "Min distance": "Мин. дистанция",
    "Max altitude": "Макс. высота",
    "Min show altitude": "Мин. высота шоу",
    "Title": "Название",
    "Sampling rate": "Частота выборки",
    "Samples per second taken from the animation (0 = every frame)": "Отсчётов в секунду из анимации (0 - каждый кадр)",
    "Light rate": "Частота света",
    "Light samples per second (0 = same as the sampling rate)": "Отсчётов света в секунду (0 - как частота выборки)",
    "Accuracy": "Точность",
    "Max trajectory error": "Макс. ошибка траектории",
    # operators
    "Create Drones": "Создать дронов",
    "Create drones on a takeoff grid in the 'Drones' collection": "Создать дронов на стартовой сетке в коллекции 'Drones'",
    "Select Drones": "Выбрать дронов",
    "Select all drones": "Выделить всех дронов",
    "Add Formation": "Добавить фигуру",
    "Create a formation with one point per drone": "Создать фигуру с одной точкой на каждого дрона",
    "Add Storyboard Entry": "Добавить сцену",
    "Add a storyboard entry using the active mesh object as formation": "Добавить сцену с активным мешем в качестве фигуры",
    "Remove Storyboard Entry": "Удалить сцену",
    "Remove the selected storyboard entry": "Удалить выбранную сцену",
    "Move Storyboard Entry": "Переместить сцену",
    "Move the selected storyboard entry": "Переместить выбранную сцену",
    "Up": "Вверх",
    "Down": "Вниз",
    "Build Show": "Собрать шоу",
    "Plan takeoff, transitions, lights and landing for the storyboard and bake them onto the drones": "Рассчитать взлёт, переходы, свет и посадку по сценарию и записать их в анимацию дронов",
    "Validate Show": "Проверить шоу",
    "Sample the drone animation and check it against the safety limits": "Снять анимацию дронов и проверить её на соответствие ограничениям безопасности",
    "Go to First Problem": "К первой проблеме",
    "Jump to the first safety violation and select the drones involved": "Перейти к первому нарушению и выделить связанных дронов",
    "Export .skyc": "Экспорт .skyc",
    "Export the drone animation as a compiled .skyc show": "Экспортировать анимацию дронов в файл шоу .skyc",
    "Validate": "Проверить",
    "Open in viewer": "Открыть в просмотрщике",
    "Send the show to a running show viewer": "Отправить шоу в запущенный просмотрщик",
    "Export CSV": "Экспорт CSV",
    "Export the drone animation as CSV files (one per drone, zipped)": "Экспортировать анимацию в CSV (по файлу на дрона, в zip)",
    "Rows per second": "Строк в секунду",
    "Import .skyc": "Импорт .skyc",
    "Import a .skyc show: drones, trajectories, lights and cues": "Импортировать шоу .skyc: дроны, траектории, свет и метки",
    "Open in Viewer": "Открыть в просмотрщике",
    "Export to a temporary file and open it in a running show viewer": "Экспортировать во временный файл и открыть в запущенном просмотрщике",
    "Clear Drone Animation": "Очистить анимацию дронов",
    "Remove the baked animation from all drones": "Удалить записанную анимацию у всех дронов",
    "Drone show (.skyc)": "Дрон-шоу (.skyc)",
    # reports
    "Create drones first (Murmura > Drones)": "Сначала создайте дронов (Murmura > Дроны)",
    "Created {count} drones": "Создано дронов: {count}",
    "Selected {count} drones": "Выделено дронов: {count}",
    "Choose an SVG or image file first": "Сначала выберите файл SVG или картинку",
    "Formation enlarged to keep {spacing:.2f} m spacing": "Фигура увеличена для шага {spacing:.2f} м",
    "The storyboard is empty": "Сценарий пуст",
    "storyboard entry '{name}' has no formation": "у сцены «{name}» не выбрана фигура",
    "formation '{name}' has {count} points but there are {drones} drones": "в фигуре «{name}» точек: {count}, а дронов: {drones}",
    "Show built: {drones} drones, {duration:.1f} s, safety {status}": "Шоу собрано: дронов {drones}, {duration:.1f} с, безопасность: {status}",
    "OK": "OK",
    "FAILED": "НЕ ПРОЙДЕНА",
    "Built in {seconds:.1f} s": "Собрано за {seconds:.1f} с",
    "Validated in {seconds:.1f} s": "Проверено за {seconds:.1f} с",
    "Exported in {seconds:.1f} s": "Экспортировано за {seconds:.1f} с",
    "Safety check passed": "Проверка безопасности пройдена",
    "Safety check FAILED": "Проверка безопасности НЕ пройдена",
    "Exported {drones} drones, {duration:.1f} s to {file}": "Экспортировано дронов: {drones}, {duration:.1f} с в {file}",
    " - safety OK": " - безопасность OK",
    " - safety FAILED": " - безопасность НЕ ПРОЙДЕНА",
    "Exported CSV for {drones} drones": "CSV экспортирован, дронов: {drones}",
    "Could not read the show: {error}": "Не удалось прочитать шоу: {error}",
    "Imported {drones} drones, {duration:.1f} s": "Импортировано дронов: {drones}, {duration:.1f} с",
    "Show sent to the viewer at {url}": "Шоу отправлено в просмотрщик: {url}",
    "Preview failed: {error}": "Не удалось открыть предпросмотр: {error}",
    "there are no drones in the 'Drones' collection": "в коллекции 'Drones' нет дронов",
    "Blender show": "Шоу из Blender",
    # swarm, groups, storyboard v2
    "Swarm": "Рой",
    "Safety": "Безопасность",
    "Export": "Экспорт",
    "Drone size": "Размер дрона",
    "Diameter of the drone spheres": "Диаметр шариков-дронов",
    "Distance between drones on the pad": "Расстояние между дронами на площадке",
    "Drone groups": "Группы дронов",
    "Drone group": "Группа дронов",
    "Only this group flies (empty = all drones)": "Летит только эта группа (пусто - все дроны)",
    "Group": "Группа",
    "Add": "Добавить",
    "Remove": "Убрать",
    "Select": "Выбрать",
    "New Group from Selection": "Новая группа из выделенных",
    "Create a drone group from the selected drones": "Создать группу из выделенных дронов",
    "Delete Group": "Удалить группу",
    "Delete the selected drone group (the drones stay)": "Удалить выбранную группу (дроны остаются)",
    "Assign to Group": "Состав группы",
    "Add the selected drones to the group, or remove them from it": "Добавить выделенных дронов в группу или убрать из неё",
    "Select Group": "Выбрать группу",
    "Select the drones of the group": "Выделить дронов группы",
    "Group with {count} drones": "Группа из дронов: {count}",
    "drone group '{name}' not found": "группа дронов «{name}» не найдена",
    "drone group '{name}' is empty": "группа дронов «{name}» пуста",
    "Type": "Тип",
    "Takeoff": "Взлёт",
    "Landing": "Посадка",
    "Return and land": "Возврат и посадка",
    "Smooth vertical takeoff from the pad": "Плавный вертикальный взлёт с площадки",
    "Fly into a formation and hold it": "Перелёт в фигуру и удержание",
    "Return above the pad and land": "Возврат к площадке и посадка",
    "Points from": "Точки из",
    "Object": "Объект",
    "Collection": "Коллекция",
    "Vertex group": "Группа вершин",
    "All vertices of the object (other objects: their location)": "Все вершины объекта (для других объектов - их положение)",
    "Vertices of one vertex group of the object": "Вершины одной группы вершин объекта",
    "Vertices of every mesh in the collection, locations of other objects": "Вершины всех мешей коллекции и положения других объектов",
    "Object colours": "Цвета объекта",
    "Colours of the points, or the colour / texture of the object under them": "Цвета точек или цвет / текстура объекта под ними",
    "Keep colours": "Не менять свет",
    "Leave the lights as they are": "Оставить свет как есть",
    "Colour from": "Цвет из",
    "Object whose colours / texture light the drones (empty = the formation object or its parent)": "Объект, чьи цвета / текстура подсвечивают дронов (пусто - сама фигура или её родитель)",
    "Colour if none": "Цвет, если нет своего",
    "Min. brightness": "Мин. яркость",
    "Dark parts of the object still glow a little so that drones stay visible at night": "Тёмные места объекта всё равно слегка светятся, чтобы дроны были видны ночью",
    "Altitude": "Высота",
    "Climb speed": "Скорость набора",
    "Calm climbing saves the batteries: about 1-1.5 m/s is efficient for most drones": "Спокойный набор бережёт батареи: для большинства дронов экономично около 1-1.5 м/с",
    "In turns": "По очереди",
    "Rows": "Рядов",
    "Auto": "Авто",
    "As many rows as the minimum distance needs (2 on a dense square pad)": "Столько рядов, сколько нужно для минимальной дистанции (на плотной квадратной площадке - 2)",
    "2 (checkerboard)": "2 (шахматка)",
    "At least two rows: every other drone, like a checkerboard": "Не меньше двух рядов: через одного, как шахматная доска",
    "At least four rows: every other drone in both directions": "Не меньше четырёх рядов: через одного по обоим направлениям",
    "Drones take off and land row by row, each row after the previous one": "Дроны взлетают и садятся рядами, каждый ряд после предыдущего",
    "Return": "Возврат",
    "Re-form into homes": "Перестроение в «дома»",
    "The whole swarm smoothly re-forms in the air into its home grid above the pad, every drone at once and without crossing, then lands row by row": "Весь рой плавно перестраивается в воздухе в «дома» над площадкой - все дроны одновременно и без пересечений, - а потом садится рядами",
    "Sakura petals": "Лепестки сакуры",
    "The figure falls apart drone by drone: each drone leaves on its turn, flies straight to its spot and lands at once, while the others are still leaving": "Фигура рассыпается по одному дрону: каждый в свою очередь отрывается, летит прямо к своему месту и сразу садится, пока другие ещё отрываются",
    "Straight home": "Прямо домой",
    "Drones fly straight back the way they came": "Дроны летят обратно тем же путём, по прямой",
    "Petals fall": "Лепестки опадают",
    "From the top": "Сверху",
    "The highest drones leave first": "Первыми улетают самые верхние дроны",
    "From the bottom": "Снизу",
    "The lowest drones leave first": "Первыми улетают самые нижние дроны",
    "From the edges": "С краёв",
    "Drones furthest from the centre leave first": "Первыми улетают дроны дальше всего от центра",
    "From the front": "Спереди",
    "Drones nearest to home leave first": "Первыми улетают дроны ближе всего к дому",
    "Random": "Случайно",
    "Drones leave in random order": "Дроны улетают в случайном порядке",
    "Petal interval": "Интервал лепестков",
    "Time between drones leaving the formation": "Время между отрывом дронов от фигуры",
    "Drones standing closer than the minimum distance take off and land in turns (checkerboard): one wave climbs, then the next, each to its own height": "Дроны, стоящие ближе минимальной дистанции, взлетают и садятся по очереди (шахматкой): сначала одна волна, потом следующая, каждая на свою высоту",
    "Transition tempo": "Темп переходов",
    "Share of the speed limits used by transitions: lower is calmer and easier on the batteries": "Какую долю от лимитов скорости используют переходы: меньше - спокойнее и экономнее для батарей",
    "Paint colour": "Цвет покраски",
    "Paint": "Покраска",
    "Paint Selected": "Покрасить выделенных",
    "Add Takeoff": "Добавить взлёт",
    "Add a smooth, battery-friendly takeoff from the pad": "Добавить плавный, экономный для батарей взлёт с площадки",
    "Add Return and Landing": "Добавить возврат и посадку",
    "Add a return above the pad and a landing": "Добавить возврат к площадке и посадку",
    "Add Formation from Selection": "Добавить фигуру из выделения",
    "Add a formation from the selection: selected vertices (Edit Mode), one object, or several objects": "Добавить фигуру из выделения: выделенные вершины (режим редактирования), один объект или несколько объектов",
    "Duplicate Storyboard Entry": "Дублировать сцену",
    "Duplicate the selected storyboard entry": "Дублировать выбранную сцену",
    "Go to Entry": "Перейти к сцене",
    "Jump to the start of the selected entry": "Перейти к началу выбранной сцены",
    "Recalculate Show": "Пересчитать шоу",
    "Plan takeoff, formations, lights, return and landing from the storyboard and write the animation": "Рассчитать взлёт, фигуры, свет, возврат и посадку по сценарию и записать анимацию",
    "Paint Selected Drones": "Покрасить выделенных дронов",
    "Paint the selected drones in the formation shown on the current frame (or the selected entry)": "Покрасить выделенных дронов в фигуре на текущем кадре (или в выбранной сцене)",
    "Clear Painting": "Сбросить покраску",
    "Remove the painting of the selected storyboard entry": "Убрать покраску выбранной сцены",
    "Painted drone sets: {count}": "Покрашенных наборов дронов: {count}",
    "Select some vertices first": "Сначала выделите вершины",
    "Select some drones first": "Сначала выделите дронов",
    "Select a formation in the storyboard first": "Сначала выберите фигуру в сценарии",
    "Formation from {count} vertices": "Фигура из вершин: {count}",
    "Formation from {count} objects": "Фигура из объектов: {count}",
    "Formation '{name}': {points} points, {drones} drones": "Фигура «{name}»: точек {points}, дронов {drones}",
    "an even subset of points will be used": "будет взята равномерная выборка точек",
    "{count} drones will wait with lights off": "{count} дронов подождут с выключенным светом",
    "Creates a new mesh; then add it as a formation.": "Создаёт новый меш; потом добавьте его как фигуру.",
    "Create Shape Mesh": "Создать меш-фигуру",
    # sidebar tabs and panels
    "Murmura LEDs": "Murmura Свет",
    "Murmura Export": "Murmura Экспорт",
    "Show": "Шоу",
    "Drone Groups": "Группы дронов",
    "More Options": "Дополнительно",
    "Shape Generator": "Генератор фигур",
    "Paint Drones": "Покраска дронов",
    "All Limits": "Все ограничения",
    "Points": "Точки",
    "Select an object with points": "Выделите объект с точками",
    "and press Formation.": "и нажмите «Фигура».",
    "Select a formation in the storyboard.": "Выберите фигуру в списке на вкладке Murmura.",
    "Select drones, pick a colour, press Paint.": "Выделите дронов, выберите цвет, нажмите «Покрасить выделенных».",
    "Show is safe": "Шоу безопасно",
    "Problems found: see Murmura Export": "Есть проблемы - см. вкладку «Murmura Экспорт»",
    "Create a new mesh with one point per drone (then add it as a formation)": "Создать новый меш с точкой на каждого дрона (потом добавьте его как фигуру)",
    "{count} drones painted in '{name}' - press Recalculate": "Покрашено дронов: {count} в «{name}» - нажмите «Пересчитать шоу»",
    "'{name}': no points found": "«{name}»: точки не найдены",
    "'{name}': {count} points for {drones} drones - the others wait with lights off": "«{name}»: точек {count} на {drones} дронов - остальные ждут с выключенным светом",
    "Takeoff added automatically before '{name}'": "Взлёт добавлен автоматически перед «{name}»",
    "Landing added automatically at the end": "Посадка добавлена автоматически в конце",
    "vertex group '{group}' not found on '{name}'": "группа вершин «{group}» не найдена у «{name}»",
    # quick flight
    "Quick flight": "Быстрый полёт",
    "Each button continues the animation from the current frame.": "Каждая кнопка продолжает анимацию с текущего кадра.",
    "Select vertices in Edit Mode (Tab), then press Fly to Selection.": "Выделите вершины (Tab) и нажмите «Лететь к выделенному».",
    "Take Off": "Взлёт",
    "Lift all drones from the current frame to the takeoff altitude": "Поднять всех дронов с текущего кадра на высоту взлёта",
    "Fly to Selection": "Лететь к выделенному",
    "Fly the drones from where they are on the current frame to the selected vertices (Edit Mode) or to all vertices of the active mesh": "Перелёт дронов с их позиций на текущем кадре в выделенные вершины (режим редактирования) или во все вершины активного меша",
    "Return and Land": "Вернуться и сесть",
    "Fly the drones back above their takeoff spots and land them": "Вернуть дронов к точкам взлёта и посадить",
    "Hold after arrival": "Пауза после прилёта",
    "How long the drones stay in the formation before the next move": "Сколько секунд дроны держат фигуру до следующего перелёта",
    "Select a mesh with the target points first": "Сначала выберите меш с точками назначения",
    "{count} points selected but there are {drones} drones": "Выделено точек: {count}, а дронов: {drones}",
    "Some points are only {spacing:.2f} m apart (minimum {minimum:g} m)": "Некоторые точки стоят всего в {spacing:.2f} м друг от друга (минимум {minimum:g} м)",
    "Drones fly to '{name}': {seconds:.1f} s": "Дроны летят в «{name}»: {seconds:.1f} с",
    "Takeoff done: {seconds:.1f} s": "Взлёт: {seconds:.1f} с",
    "Landing done: {seconds:.1f} s": "Посадка: {seconds:.1f} с",
}


def set_override(language: str | None) -> None:
    """Forces a language (``"ru"`` / ``"en"``), e.g. when the add-on runs
    without its preferences being available."""
    global _override
    _override = language


def _preference() -> str:
    addon = bpy.context.preferences.addons.get(__package__) if __package__ else None
    if addon is not None and getattr(addon, "preferences", None) is not None:
        return getattr(addon.preferences, "language", "AUTO")
    return "AUTO"


def resolve_language() -> str:
    """The language the add-on should use right now: ``"ru"`` or ``"en"``."""
    if _override:
        return "ru" if _override.lower().startswith("ru") else "en"
    pref = _preference()
    if pref == "RU":
        return "ru"
    if pref == "EN":
        return "en"
    if bpy.app.translations.locale.startswith("ru"):
        return "ru"
    return engine.i18n.detect_language()


def apply_language() -> str:
    """Selects the language for the add-on and the engine messages."""
    global _current
    _current = resolve_language()
    engine.i18n.set_language(_current)
    return _current


def current() -> str:
    return _current


def tr(text: str, **kwargs) -> str:
    out = RU.get(text, text) if _current == "ru" else text
    return out.format(**kwargs) if kwargs else out


def localize(cls) -> None:
    """Translates the label, description and property definitions of a
    class right before it is registered."""
    original = cls.__dict__.get("_murmura_original")
    if original is None:
        original = {
            "bl_label": cls.__dict__.get("bl_label"),
            "bl_description": cls.__dict__.get("bl_description")
            or (cls.__doc__ or "").strip()
            or None,
            "bl_category": getattr(cls, "bl_category", None),
            "annotations": dict(cls.__dict__.get("__annotations__", {})),
        }
        cls._murmura_original = original
    if original["bl_label"]:
        cls.bl_label = tr(original["bl_label"])
    if original["bl_category"]:
        cls.bl_category = tr(original["bl_category"])
    if original["bl_description"] and issubclass(cls, bpy.types.Operator):
        cls.bl_description = tr(original["bl_description"])
    annotations = {}
    for key, prop in original["annotations"].items():
        function = getattr(prop, "function", None)
        keywords = getattr(prop, "keywords", None)
        if function is None or keywords is None:
            annotations[key] = prop
            continue
        keywords = dict(keywords)
        for field in ("name", "description"):
            if keywords.get(field):
                keywords[field] = tr(keywords[field])
        items = keywords.get("items")
        if isinstance(items, (list, tuple)):
            keywords["items"] = [(i[0], tr(i[1]), tr(i[2]), *i[3:]) for i in items]
        annotations[key] = function(**keywords)
    cls.__annotations__ = annotations
