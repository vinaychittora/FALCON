# FALCON: plan for the next rig (9 Nov 2026)

## 1. What we are building

A plug-in wildlife observer for **backyards, gardens and small water bodies**, that a friend can set up without a PC, wires inside their house, SSH or technical steps. It watches one spot (usually water), day and night, and keeps a small, trustworthy record: *what came, when, how sure, with a clip*. Privacy-safe by default for residential areas.

Not in scope for now: forests and remote sites, insect identification at night, counting or tracking individuals.

## 2. What the current rig taught us (7-9 Nov, measured)

| Area | Finding | Consequence |
|---|---|---|
| Picture | Fixed-focus USB webcam (focus ring glued), 1080p MJPEG with no quality control, weak IR | Small animals are blurry; similarity rarely above 0.55; insects at night unrecognisable |
| Heat | Pi 4 reached 75 °C streaming 1080p in a closed box | Outdoor unit should not encode video or think |
| Models | BioCLIP 2.5 about 45 ms per crop on an RTX 3060 Ti; seconds on CPU | The computer needs a GPU or AI accelerator |
| False alarms | Bowl, dead leaf, hood edge, remount, IR insects | Solved in software by motion, scenery memory, counted tiers, SIZE hold, night-insect rule |
| Real animals | Rusty-spotted Cat (night), Oriental Magpie-Robins (day), small mammal at 23:42 | Night animals score 0.54-0.75 at the detector: the floor must allow 0.5 |
| Configuration | About 40 settings; mistakes made the picture black and flooded alerts | Fix most values internally; few, safe choices per site |
| Privacy | 20 s raw sound clips kept around bird calls; people not blurred | Defaults must change before other homes |

## 3. Architecture: two devices

**Outdoor sensor head (weatherproof, cool, no computing)**
- PoE IP camera: starlight-class sensor, built-in IR (30 m), RTSP H.264, 1080p or better, motorised or settable focus, IP66/67, built-in or external mic. One cable for power and data up to 100 m; an outdoor Wi-Fi bridge where a cable is impossible.
- Optional small weather sensor (temperature, humidity, light). The Pi 4 can keep this job plus the microphone if the camera has none.
- Solar only at sites without mains: a 12 V battery with a PoE injector, sized later.

**Indoor compute box (shade or indoors, pre-installed)**
- Runs today's FALCON unchanged: detection, BioCLIP, BirdNET, visits, clips, web page.
- Candidates to benchmark (do not buy several before the test):
  1. NVIDIA Jetson Orin NX 16 GB or Orin Nano Super (low power, CUDA, fanless options)
  2. Mini PC with a low-profile NVIDIA card (most compatible with today's code)
  3. Intel Core Ultra mini PC (NPU/iGPU, would need an OpenVINO path)
- Target: 2 frames/s, at least 10 crops/s, under 60 °C indoors, about 30 W or less, silent.

## 4. The appliance (for friends)

- **First start:** the box opens a setup page over its own Wi-Fi; the owner picks home Wi-Fi, sets the place on a map (sun times and the local species list) and gives the device a name. The camera is found on the network automatically.
- **Runs by itself:** observation starts at power-up and after power cuts. Nothing to click.
- **Use:** web page on phone or laptop on the same Wi-Fi with an access code. Live, Review, Summary.
- **No SSH, ever.** Updates are signed packages: "Update available, install?" on the page, or automatic at night.
- **Remote help only with consent:** a "Let Vinay help" switch on the owner's page that opens a private link (Tailscale), off by default and visible while on.
- **Data stays on the device.** Export (CSV or Camtrap DP with clips) only when the owner presses Export.

## 5. Fixed configuration (what the owner sees)

Per site, only:
1. Place (map pin)
2. Camera aim and focus (guided by a live picture with a grid)
3. What to watch: animals day and night (default); insects by day only (fixed)
4. Privacy level: standard (people blurred, no raw sound) or research (owner's own garden: sound clips allowed)

Everything else becomes fixed internally, with values measured on our nights: detector floor 0.5, 2 frames/s, BioCLIP 2.5, every crop classified, scenery after 3 minutes, Likely at 0.45/0.02/3 frames over 2 s, SIZE hold, night-insect rule, flicker guard, clips 5 s before and after.

Kept as engineering settings behind a "Service" page: the same values, editable only during remote help.

## 6. Clips and alerts (Vinay's rule)

- One alert per animal visit, when it becomes Likely.
- One 10 s clip at arrival (5 s before, 5 s after); while the animal stays, another 10 s clip every 10 s (0 s, 10 s, 20 s ...).
- Each animal has its own clips, even when two overlap.
- Hidden records (glimpses, scenery, insects at night) keep a short clip for 48 h; real visits keep clips for 30 days or until exported; a disk cap protects the box.

## 7. Privacy defaults (residential)

- People blurred in every clip and preview (on).
- Sound: BirdNET listens continuously, but by default no raw sound is stored; only the call's name, time and confidence. Optional: store bird-call clips with speech removed.
- No upload, no cloud. Nothing is seen by anyone else unless the owner exports or turns on remote help.

## 8. Calibration at a new site (10 minutes, guided)

1. Place the camera 1.5-3 m from the water, slightly above, without sky or a road in view.
2. Day picture check (focus, sharpness score), then night picture check (IR reach, no glare).
3. Let FALCON learn the scenery (3 minutes still).
4. Sound check (noise level, quiet hours).
5. A one-page site card: photo, place, date, scores, to compare later.

## 9. Steps

| Step | What | Done when |
|---|---|---|
| 1 | This document and the fixed configuration agreed | Vinay approves |
| 2 | One IP camera and one compute candidate bought; benchmark on saved nights (replay tool, clips) and three nights side by side with today's rig | Numbers: detections, false alarms, crops/s, temperature |
| 3 | Appliance build: image, setup page, updates, privacy defaults, clip rule, fewer settings | A non-technical person sets it up from the box in 15 minutes |
| 4 | Pilot at 2-3 sites, about a week each (backyard, a friend's garden, a small pond) | Short report per site: what came, what was missed, false alarms, heat |
| 5 | Decide solar and outdoor variants, and a second production batch | Based on step 4 |

## 10. Meanwhile, on today's rig

Settings set on 9 Nov 20:51 IST for the most detections with confidence: detector 0.5, 12 boxes per frame, 2 frames/s, BioCLIP 2.5, fixed camera off, people blurred, one sound visit per bout (120 s gap, 15 min cap). Picture controls back to the 8 Nov values. Logging keeps collecting for the step 2 comparison.
