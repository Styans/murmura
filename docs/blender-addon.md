# Murmura for Blender

A Blender add-on (Blender 4.2 or newer, tested with 5.2) that turns Blender
into a drone show editor: create drones and formations, arrange them on a
storyboard, let Murmura plan takeoff, collision-aware transitions, lights and
landing, then validate and export a `.skyc` show. It needs no server and no
extra Python packages - the Murmura engine is bundled inside the add-on.

## Install

1. Build the package (or download it from the releases page):

   ```bash
   python blender/build_addon.py
   ```

   This writes `dist/murmura-blender-<version>.zip`.
2. In Blender open *Edit → Preferences → Get Extensions*, open the drop-down
   menu in the top right corner and choose *Install from Disk…*, then pick
   the zip file.
3. Three tabs appear in the 3D viewport sidebar (press `N`), laid out like
   Skybrush Studio. The language follows Blender / the system and can be
   changed in the add-on preferences.

## Tabs

| Tab | Contents | Skybrush equivalent |
| --- | --- | --- |
| **Murmura** | drones and the show: storyboard and *Recalculate Show* | Formations |
| **Murmura LEDs** | lights of the selected formation, painting drones | LEDs |
| **Murmura Export** | safety limits, validation, `.skyc` export | Safety & Export |

Rarely used settings live in collapsed *More Options* / *All Limits*
sub-panels.

## Workflow

1. **Drones** - number of drones, pad spacing and drone size, then *Create
   Drones* (skip this if the scene already has drones in a `Drones`
   collection). Drone groups are in a collapsed sub-panel; any formation can
   be flown by one group only.
2. **Formation** - select the object with the target points (for example the
   points made by Pointille or DroneGen), several objects, vertices in Edit
   Mode, or click a collection in the Outliner with nothing selected, then
   press **Formation** in the *Show* panel. Repeat for every formation.
   *Takeoff* and *Landing* entries are added automatically when missing.
3. **Recalculate Show** - the only button that computes: assignment, safe
   transitions (synchronised, staggered, lanes, vertical-first, via spread),
   lights, return and landing are baked into the drone animation. A status
   line below the button says whether the show is safe.
4. **Export .skyc** on the *Murmura Export* tab.

The collapsed *Shape Generator* panel only creates a helper mesh (circle,
heart, text, SVG...) that you then add with *Formation* like any object.
On *Murmura LEDs*, *Object colours* use the points' `drone_color` attribute
(Pointille / DroneGen), vertex colours, or the texture / material of the
object under each point; *Paint Selected* stores a colour for the selected
drones that survives recalculation.

## Tips

* Scene units: Murmura works in metres; the scene's *Unit Scale* is respected.
* The first frame of the scene is time 0 of the show; drones' positions on
  that frame are their takeoff spots.
* Large shows: importing a 1000-drone, 17-minute show takes a few seconds;
  exporting it samples the animation frame by frame and takes about two
  minutes at 4 samples per second.

## Development

```bash
# end-to-end test inside Blender (from the repository, or a built zip)
blender --background --factory-startup --python blender/tests/run_blender_tests.py
blender --background --factory-startup --python blender/tests/run_blender_tests.py -- dist/murmura-blender-0.1.1.zip
# validate the package
blender --command extension validate dist/murmura-blender-0.1.1.zip
```
