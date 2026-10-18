# Using FALCON

Open **http://127.0.0.1:8000** on the inference computer (or the private address from
System → Device access). The menu on the left has eight pages.
Every page has a **Help** button next to its title that opens the matching guide. The bar along the top
always shows whether FALCON is observing, how many sensor nodes are online and how many
animal visits are waiting for review. Click any of them to jump there.

## Live

Watch the sensor and check detections while they happen.

1. Choose a source at the top right: a FALCON sensor node, or the saved IP camera.
2. Press **Start observing**. The picture appears with boxes around detected animals.
3. Detections appear on the right as **cards, one per animal visit**. A visit is one
   tracked animal (its frames are grouped), or one bird call. Each card shows a crop of
   the animal, or a spectrogram for sound, the suggested species, the time, and the
   model score.
4. Check each card with one click:

   | Button | Key | Meaning |
   | --- | --- | --- |
   | Confirm | C | The suggested species is right |
   | Correct | E | Choose the right species (type a common or scientific name) |
   | Unsure | U | An animal, but the species is not clear |
   | Not an animal | X | Wrong detection: leaves, shadow, a person, a vehicle |
   | Discard | D | Not useful: a duplicate, blurred or empty clip. Hidden and never exported |
   | Details | Enter | Play the saved clip, see all model suggestions, add notes |

   Click a card first (or Tab to it) to use the keys. A decision applies to every frame of
   that visit.

Below the picture: stream facts (frame rate, resolution, analysis rate and delay, model,
sound format, saved clips, clock), the node's sensor switches, quick camera settings
(focus, brightness, white balance, HDR, flip) and the latest weather at the sensor.
**Stop** ends the observation. FALCON analyzes one source at a time.

## Review

Go through everything recorded, in a chosen time window.

- **Filters:** time (last 24 hours, 7 days, 30 days, all, or custom from/to), status
  (To review, Confirmed, Corrected, Unsure, Not an animal, Discarded, or all), video or
  sound, and species name. **More** adds field-or-test recordings, a single session and a
  minimum model score.
- **One visit at a time:** use the same buttons and keys as on Live. **J** and **K** move
  to the next and previous card.
- **Many at once:** tick cards (or press **Space**), or *Select all on this page*, then use
  the bar that appears: Confirm, Set species…, Unsure, Not an animal, Discard, or reset to
  "to review".
- Every decision is stored with the time and the previous decision (an audit trail); the
  original model output is never overwritten. Discarded visits stay in the audit trail but
  are hidden unless you choose the Discarded filter, and are never exported.

## Sensors

Pair and control the devices that feed FALCON.

- **Add sensor node:** enter the node's address and pairing key (see
  [the sensor node guide](SENSOR_NODE.md)).
- For each node: stream on/off and restart, switches for camera, microphone, weather
  sensor and rain plate, **Observe live**, health (temperature, power, memory, storage,
  Wi-Fi, clock), stream details, weather readings, full **camera picture settings**,
  microphone choice, rescan hardware, restart or shut down the node, rename or forget it.
- **IP camera (RTSP):** save a network camera's address and account. The password is
  encrypted on this computer. Its picture settings stay in the camera's own app.
- **Start automatically:** after a power cut or restart, FALCON resumes observing the
  chosen node or camera by itself.
- **Environmental history:** every weather reading received, including times without
  animals.

## Export

Make a clean dataset for researchers. See [data export](DATA_EXPORT.md) for the format.

1. **Time window:** last 24 hours, 7 days, 30 days, everything, or custom.
2. **What to include:** *Verified only* (best for publication), *Verified + unreviewed*
   (adds machine identifications, marked as such), or *Everything except discarded*.
   Choose video and/or sound detections, clip files and weather readings, and optionally
   a minimum score for unreviewed records.
3. **Dataset details:** site latitude and longitude, contact name and dataset title are
   required by the standard. They are remembered in this browser.
4. The summary shows how many visits, species, sessions, clips and readings will be in
   the package. Press **Download Camtrap DP (.zip)**.

The *Complete FALCON archive* link downloads every field record with its full review
history, for backup.

## Media tests

Try FALCON on a photo, video or sound recording without mixing it into field data.
**Add media**, select it, and press **Analyze recording** (or **Analyze photo**). Results appear on the timeline and in the
list, and can be reviewed like field records. A test session is temporary: **End test
session** removes its uploads and results.

## Species

The local species list that the visual model chooses from, built from iNaturalist
research-grade observations for your region (`make taxa ARGS='--place "Kerala, India"'`).
**Refresh taxa** rebuilds it.

## System

- **Live status:** camera and sound input, inference delay, saved clips, weather freshness,
  and this computer's CPU, GPU, memory and storage.
- **Configuration:** analysis settings: species model, detector and species thresholds,
  frames analyzed per second, region of interest, small-animal mode, fixed camera mode
  (motion proposals), bird-call confidence and the site location used by BirdNET. Save, then start a
  new observation to use them.
- **Model status:** which models are loaded and on which device.
- **Device access:** private remote access through Tailscale and the startup service.

## Help

Everything about FALCON in one place: these guides, the sensor node guide, the parts list,
data export, troubleshooting, how the system works, security and licenses. **Search all
guides** finds any word across them; **On this page** jumps to a section. Under
*Handbooks*, the node build handbook opens as a web page, and both handbooks can be
downloaded as PDF for printing.

**Display** (bottom left) switches dark or light theme, text size and higher contrast.

## Reading the numbers

- *Visual similarity* compares the animal crop with species names. It ranks candidates
  but is **not a probability**.
- *BirdNET confidence* is the sound model's own score for a call.
- Times are the inference computer's clock (UTC in exports). A warning appears if its
  clock was not synchronized.
- A visit is not a count of individuals: the same animal can make several visits.
