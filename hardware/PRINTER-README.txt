FALCON node enclosure - files for 3D printing
=============================================

Print the ten STL files in stl/. All parts print WITHOUT supports in the
orientation listed below. Sheet 1 of FALCON-enclosure-drawings.pdf repeats this.

  01_shell                  1x  back wall on the bed, open side up
  02_front_cover            1x  outer face on the bed      (print after the mic check, see below)
  03_electronics_tray       1x  flat plate on the bed, bosses up
  04_roof_hood              1x  upside down (top face on the bed)
  05_rain_plate_cradle      1x  flat base on the bed
  06_shield_cap             1x  flat underside on the bed
  07_shield_plate_x4        4x  flat underside on the bed, posts up
  08_shield_sensor_carrier  1x  ring on the bed
  09_shield_arm             1x  on its side (L shape flat on the bed)
  10_pole_mount_plate       1x  plate on the bed, strap tunnels up

Material:  PETG minimum, ASA preferred (outdoors, strong sun). NOT PLA.
Colour:    white or light grey.
Settings:  0.4 mm nozzle, 0.2 mm layers, 4 walls, 5 top / 5 bottom layers,
           30-40 % gyroid infill, brim on the shell and cover if corners lift.
Inserts:   holes are sized for brass heat-set inserts: M3 = 4.2 mm, M2.5 = 3.6 mm.

The STEP files in step/ are the same parts for any CAD program; the file
00_assembly_with_reference_boards.step shows everything in place.

Microphone check before printing the cover: the two grille positions come from the
audio board maker's 3D model. Drawing sheet 4 describes a two-minute check once the
electronics are on the printed tray. Everything else can be printed first.
