# Сценарии шоу

Сценарий шоу - это документ YAML (или JSON). Он собирается командой
`murmura build сценарий.yaml -o show.skyc`. Относительные пути к файлам
отсчитываются от папки сценария.

```yaml
title: Моё шоу             # название, показывается в просмотрщиках
drones: 64                 # обязательно: число дронов

limits:                    # ограничения для планирования и проверки
  max_velocity_xy: 6       # м/с, горизонтальная скорость
  max_velocity_z: 2.5      # м/с, снижение (и набор, если не задан max_velocity_z_up)
  max_velocity_z_up: 2.0   # м/с, набор высоты (необязательно)
  max_acceleration: 3      # м/с², задаёт оба параметра ниже
  max_acceleration_xy: 3
  max_acceleration_z: 3
  min_distance: 2          # м, между дронами в воздухе
  max_altitude: 120        # м
  min_nav_altitude: 2.5    # м над точкой взлёта во время шоу
  max_yaw_rate: 30         # °/с

home:                      # точки взлёта и посадки (один из вариантов)
  grid: {spacing: 3, columns: 8, center: [0, 0, 0], yaw: 0}
  # points: [[x, y, z], ...]
  # file: home.csv         # строки, оканчивающиеся на x,y,z

settings:
  light_fps: 10            # частота выборки анимированных световых эффектов
  motion_fps: 8            # частота выборки анимированных фигур
  fit_tolerance: 0.02      # м, допустимая ошибка при сжатии траекторий
  profile: smooth          # smooth | linear | ease_in | ease_out
  stagger: true            # разрешать конфликты задержками и дорожками

auto_scale: false          # увеличивать фигуры плотнее min_distance (+15 % запаса)

takeoff:                   # или false, чтобы начать шоу в воздухе
  altitude: 6
  layered: true            # дроны ближе min_distance взлетают по очереди (шахматкой)
  color: "#303030"

scenes:
  - name: Кольцо
    formation: {shape: circle, radius: 18, center: [0, 0, 30], plane: xz}
    hold: 8                # секунд в фигуре после прилёта
    start: 20.0            # необязательно: время начала перехода (под музыку)
    auto_scale: true       # переопределение для этой сцены
    lights: {effect: rainbow, period: 4, axis: x}
    motion: {kind: rotate, rpm: 2}
    transition:
      duration: 10         # минимальная длительность; увеличивается, если нужно
      profile: smooth
      stagger: true
      matching: optimal    # optimal | fixed
      lights: {effect: fade, start: black, end: white, duration: 10}
  - wait: 3                # пауза на месте
  - name: Логотип
    formation: {shape: svg, file: logo.svg, size: 40, center: [0, 0, 35]}
    lights: formation      # цвета рисунка

landing:                   # или false
  velocity: 1.2            # м/с, пиковая скорость снижения
  spindown: 3              # с между посадками соседних дронов
  target: home             # home (своя точка взлёта, обратно тем же путём) | nearest (ближайшая)
  staging_spread: null     # необязательная растяжка сетки перед посадкой, например 2.0
  rows: 0                  # минимум рядов посадки (0 - сколько нужно, 2, 4)
  style: dissolve          # dissolve (лепестки: по одному) | morph (в «дома») | direct
  order: random            # random | top | bottom | outside | front
  interval: 0.15           # с между отрывом дронов от фигуры
  color: "#303030"

audio: {file: music.mp3, start: 0.0}
location: {lat: 55.7539, lon: 37.6208, amsl: 150, orientation: 0}
```

## Фигуры

Все фигуры принимают `center: [x, y, z]`. Плоские фигуры также принимают
`plane: xz | xy | yz` (по умолчанию `xz` - вертикальная плоскость, обращённая к
зрителям со стороны -Y), `rotation` (поворот в плоскости, градусы) и `yaw`
(поворот вокруг вертикали, градусы).

| shape | параметры |
| --- | --- |
| `grid` | `spacing`, `columns` |
| `line` | `length` |
| `circle` | `radius`, `start_angle` |
| `polygon` | `radius`, `sides` |
| `star` | `radius`, `inner_ratio`, `spikes` |
| `heart` | `size` |
| `spiral` | `radius`, `turns` |
| `disc` | `radius` (заполненный) |
| `rectangle` | `width`, `height`, `filled` |
| `sphere` | `radius` |
| `cube` | `size` |
| `torus` | `radius`, `tube` |
| `helix` | `radius`, `height`, `turns` |
| `text` | `text` (латиница, кириллица, цифры, `!?.,-+:'"/=#*♥`, `\n`), `height` |
| `svg` | `file` или `source`, `size`, `angle` (порог углов) - даёт цвета |
| `image` | `file`, `size`, `threshold`, `invert` - даёт цвета (нужен Pillow) |
| `points` | `points: [[x, y, z], ...]` (ровно по одной точке на дрона) |

## Световые эффекты

`lights` принимает цвет (`"#ff0080"`, `red`, `rgb(255, 0, 128)`) или эффект.
Любой эффект принимает `brightness` (0-1).

| effect | параметры |
| --- | --- |
| `solid` | `color` |
| `formation` | `fallback` - цвета из SVG / картинки |
| `gradient` | `colors: [...]`, `axis: x | y | z | radial` |
| `rainbow` | `period`, `axis`, `spread`, `saturation` |
| `pulse` | `color`, `period`, `min`, `use_formation_colors` |
| `wave` | `colors: [...]`, `speed`, `wavelength`, `axis` |
| `sparkle` | `color`, `background`, `rate`, `flash`, `seed` |
| `fade` | `start`, `end`, `duration` |

## Движение

| kind | параметры |
| --- | --- |
| `rotate` | `rpm`, `center`, `ramp` |
| `breathe` | `amplitude` (относительная), `period`, `ramp` |
| `wave` | `amplitude` (м), `wavelength`, `period`, `along: x | y | z`, `ramp` |

Движения плавно начинаются и заканчиваются. Если движение превышает
ограничения скорости или ускорения, сначала удлиняются разгон и торможение,
затем уменьшается скорость. Сборка выводит об этом заметку.

## Язык сообщений

Команды `murmura` выводят сообщения на русском, если Windows или переменная
окружения `MURMURA_LANG=ru` на русском. Язык можно задать явно:

```bash
murmura --lang ru build сценарий.yaml -o show.skyc --report отчёт.pdf
```
