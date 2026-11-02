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

**Takeoff and landing in turns.** When drones stand closer than the minimum
distance on the pad, *In turns* (on by default) splits them into waves whose
drones are at least the minimum distance apart - a checkerboard on a square
grid. The first wave climbs highest; the next one starts as soon as the
drones above it are far enough away and stops one layer lower (the layer gap
is just what keeps neighbours at the minimum distance). Landing plays the
same plan backwards: the lowest layer lands first, neighbours touch down
*Spin-down* seconds apart. A pad that already respects the minimum distance
takes off all at once.

**Sakura petals (default return).** The figure falls apart drone by drone,
like after a finger snap: each drone leaves on its turn (at random, from
the top, bottom, edges or front), flies straight to its point above a free
landing spot and lands at once, while the others are still leaving. The
figure first breathes out to sqrt(2) times the minimum distance, drones
not in the figure land first, and every departure time is chosen so that
the drone keeps the minimum distance to everybody during its whole flight
and neighbours touch down *Spin-down* seconds apart. Planned drones never
change, so a finished plan is safe; if no plan is found the swarm re-forms
into its homes instead.

**Re-form into homes.** The whole swarm re-forms in the
air into its home grid - a point above every landing spot - with every drone
moving at once along a straight line, then lands row by row. Drones get the
home points that minimise the sum of squared distances; with such an
assignment synchronised straight moves never bring two drones closer than
the start and end spacing divided by sqrt(2) (the CAPT result), so the home
grid uses sqrt(2) times the minimum distance (4 rows on a 1.5 m pad) and a
denser formation first breathes out, scaled up about its base. No paths
cross, nobody waits for a turn, and planning takes a fraction of a second.

**Rows.** Landing goes row by row: a row starts descending only when the
previous one has touched down (plus *Spin-down*). *Rows* under *More
Options* asks for at least 2 (checkerboard) or 4 rows.

**Return to the own spot.** With *Land on: Own spot* (the default) every
drone flies back to the very point where it hovered after takeoff and lands
where it took off. The return is the flight from the takeoff points into the
last formation played backwards, so drones retrace their way in the order
they left. If several formations mixed the drones up so much that the own
spots cannot be reached safely, they land on the nearest free spots and the
report says so.

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
