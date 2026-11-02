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
3. The add-on appears in the 3D viewport sidebar (press `N`) as the
   **Murmura** tab.

## Workflow

1. **Swarm** - number of drones, pad spacing, columns and drone size, then
   *Create Drones*. Select drones and press **+** under *Drone groups* to make
   a group; any formation can be flown by one group only.
2. **Formations** - select the object with the target points (for example the
   points made by Pointille or DroneGen), several objects, vertices in Edit
   Mode, or click a collection in the Outliner with nothing selected, then
   press **Add Selected as Formation**. The drones will fly to those points.
   The collapsed *Generate Shape Mesh* sub-panel only creates a helper mesh
   (circle, heart, text, SVG...) that you can then add the same way.
3. **Storyboard** - formations appear here; add *Takeoff* and *Landing*
   entries, reorder, duplicate or delete them. A missing takeoff or landing
   is added automatically.
4. **Recalculate Show** - the only button that computes: assignment, safe
   transitions (synchronised, staggered, lanes, vertical-first, via spread),
   lights, return and landing are baked into the drone animation.
5. **Lights** - *Object colours* use the points' `drone_color` attribute
   (Pointille / dronegen), vertex colours, or the texture / material of the
   object under each point; or pick an effect. *Paint Selected* stores a
   colour for selected drones in the current scene and survives recalculation.
6. **Safety** - limits, transition tempo, landing speed, spin-down; validate.
7. **Export** - `.skyc`, CSV, import, viewer preview.

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
