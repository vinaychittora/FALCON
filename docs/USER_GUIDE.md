# Using FALCON

Open **http://127.0.0.1:8000** on the inference computer (or the private address from
System → Device access). The menu on the left has nine pages.
Every page has a **Help** button next to its title that opens the matching guide. The bar along the top
always shows whether FALCON is observing, how many sensor nodes are online and how many
animal visits are waiting for review. Click any of them to jump there.

## Live

Watch the sensor and check detections while they happen.

1. Choose a source at the top right: a FALCON sensor node, or the saved IP camera.
2. Press **Start observing**. The picture appears with boxes around detected animals.
3. Detections appear on the right as **cards, one per animal visit**, newest on top.
   A visit is one tracked animal (its frames are grouped, even when the bird flutters
   or the detector misses it for a moment), or one bird call. Each card shows a crop of
   the animal, or a spectrogram for sound, the suggested species, the time, and the
   model score. When the species is unclear the card still leads with the most probable
   name and says what else it could be: **Spotted Owlet**, *or Jungle Owlet*; **Indian
   Pitta**, *or Mangrove Pitta · same genus Pitta*; or just **Unknown bird**. Boxes and
   cards share one colour code: **green** likely, **orange** probable (look-alikes score
   almost the same), **red** a faint best guess (shown with a question mark), **gray**
   unknown. The box shows only the name; the scores are in the card and the side panel.
   Detections that say nothing yet (no species, no group) are kept in the archive but
   not shown on Live; find them on Review with **Show hidden**. The heading counts the
   visits and species of this session.
4. Check each card with one click:

   | Button | Key | Meaning |
   | --- | --- | --- |
   | Confirm | C | The suggested species is right |
   | Correct | R | Choose the right species (type a common or scientific name) |
   | Unsure | U | An animal, but the species is not clear |
   | Discard | D | No animal, or not useful: a duplicate, blurred or empty recording. Hidden and never exported |
   | Details | Enter | Open the review dialog: evidence and facts on the left, decision on the right |

   Click a card first (or Tab to it) to use the keys. A decision applies to every frame of
   that visit.

   The review dialog keeps everything on one screen: the clip or source frame, a facts
   grid (detector, similarity, gap to the runner-up, genus, box size, track, frames, device,
   weather), the model's top five suggestions as bars, and on the right the decision
   buttons (same keys as the cards, plus **R** for unreviewed), species search, notes and
   Save. **Ctrl+Enter** saves. On a narrow screen the two columns stack.

Below the picture: stream facts (frame rate, resolution, analysis rate and delay, model,
sound format, saved clips, clock), the node's sensor switches, quick camera settings
(focus, brightness, white balance, HDR, flip) and the latest weather at the sensor.
**Stop** ends the observation. FALCON analyzes one source at a time. Every start and
stop is recorded as a **session**; see Summary.

**People are never recorded as observations.** A person in the picture is masked with
a gray box in the live picture, in the review images and in the saved clips, and seconds
with human voices are silenced in saved sound clips. Nothing extra has to be switched on.
To see people as filmed (for example while setting up the camera), turn off **Mask people
in video** in Settings. People are still never recorded as observations.

**Status line.** One line under the top bar (inside the bar on a wide screen) always says
what is going on: **Connected**, **Loading…** with a thin moving bar while something you
asked for is on its way, **FALCON is slow to answer…** after 5 seconds, **Can't reach
FALCON since** a time when two checks in a row fail, or **This device has no network.**
Short confirmations such as "2 reviews saved" appear there for 3 seconds, and an open
record or the posting panel on a phone shows the same states in its own top bar.

**Recordings.** Each stay at the bowl is one continuous video with sound, from 5 s
before the animal is first seen until 15 s pass without it (files of at most 10 minutes
follow each other without a gap); a calling bird gets one sound recording for the whole
calling stretch. How long they are kept: visits you **Confirm** or **Correct** keep their
recordings for good; **Discard** loses its recording one to two hours after your choice
(an hourly pass removes what was decided more than an hour ago; until then Undo brings it
back); everything else after 60 days. The record, its picture
(for sound, the spectrogram) and all details stay, with one exception: a record FALCON hid
by itself (Review → Status → Hidden) that you have not reviewed 7 days after capture is
cleared completely, record and recording. Hidden (N) and Show hidden (N) show how many are
waiting. System shows the space used.

*Technical note: sound and picture.* The sensor node sends the camera and the microphone
as two separate streams, so a camera hiccup never interrupts the sound. FALCON lines them
up on the time they arrive, corrected by a small constant for the capture path (sound
about 23 ms from the encoder and sound card, picture about 15 ms from USB and decoding):
estimated once per rig, about 8 ms, no user step. Live warns on its Sound indicator when
the microphone delivers more than 1 % off its rate.

**Friends (view only).** Under System → Device access, invite a friend by name and email;
they get a 10-letter code (shown once) for the view-only page, which shows the live
picture once a second, recognised animals and their video clips: no sound, settings or
anything hidden. The friends' picture pauses while a person is in view, whatever Mask
people is set to. **Withdraw** stops an invitation at once; *Who viewed what* lists
sign-ins and clips played. The page runs on this computer (port 8081) and is not on the
internet until a Cloudflare or Tailscale front door is set up.

## Review

Go through everything recorded, in a chosen time window.

- **Filters:** time (last 24 hours, 7 days, 30 days, all, or custom from/to), status
  (To review, Hidden, Confirmed, Unsure, Discarded, or All), video or
  sound, and species name. **More** adds field-or-test recordings, a single session, a
  minimum model score and **Show hidden (N)**: detections with no species and no group,
  one-frame glimpses, and Probable sound records (best BirdNET confidence under 0.60, or
  the cleaned sound disagrees), hidden by default; N says how many. Hiding deletes nothing, but what FALCON hid and
  you have not reviewed is cleared 7 days after capture (see **Recordings** under Live); once you
  review a sound record it is always listed. **Unidentified only** lists just the
  unreviewed picture visits the model gave no species, hidden ones included, so you can
  name them by hand; turn on Show hidden as well to add one-frame glimpses. Night insects
  and the rats and mice removed at night stay out. Status **Hidden** lists only what FALCON
  hid by itself and you have not reviewed (exactly what Show hidden adds to To review);
  the two switches do nothing while it is chosen.
- **One visit at a time:** use the same buttons and keys as on Live. **J** and **K** move
  to the next and previous card.
- **One card per stay:** when several animals are at the water in the same recording,
  Review shows them as one card: a head with the time span, and one row per animal. Each
  animal keeps its own decision. Animals FALCON hid in that stay sit behind the line
  *N more that FALCON hid in this stay*. Every number still counts visits, not cards. In
  the recording every box carries its name, and the chips under the player
  (*Name 09:37*) choose the animal: the recording jumps to it, its box turns bold, and the
  line above the buttons says which animal they act on.
- **Unidentified sound:** a sound gets a bird's name only if that bird is recorded in
  Rajasthan. Any other sound is kept as *Unidentified sound*, with BirdNET's guess, under
  Hidden for you to review; **Correct** offers the guess first. It rings no bell, cannot
  be posted until you correct it, and is cleared after 7 days if you do not review it.
- **Post to iNaturalist:** a visit you confirmed or corrected to a species can be posted to
  iNaturalist with your own account. Pasting a key from inaturalist.org/users/api_token
  always works; the key lasts 24 hours and FALCON keeps it in memory only, until it
  restarts. **Sign in to iNaturalist** (on this computer, http://localhost:8000) needs an
  iNaturalist application of your own, registered at inaturalist.org/oauth/applications as
  a non-confidential application with the redirect address http://localhost:8000/oauth/cb;
  enter its Application ID once under **Set up sign-in** on the posting page. Open the visit with
  **Post to iNaturalist**, choose 1 to 3 pictures (suggested frames, or frames picked from
  the recording, with an optional crop) and/or include the trimmed sound, check the
  description, and press **Post**: one press sends one observation. The page shows how
  many were posted today out of 20 a day. A posted visit leaves the list, says it is
  already on iNaturalist, and cannot be posted twice. The location is the node's camera
  spot, shown publicly only as an obscured area.
- **Many at once:** tick cards (or press **Space**), or *Select all on this page*, then use
  the bar that appears: Confirm, Correct, Unsure, Discard, or Reset to "to review". When the list has more pages, *Select all N in this list* takes every page;
  the bar then counts the records as they are saved, and **Undo** takes back the whole
  action.
- Every decision is stored with the time and the previous decision (an audit trail); the
  original model output is never overwritten. Discarded visits stay in the audit trail but
  are hidden unless you choose the Discarded filter, and are never exported.

## Summary

Counts for a report or a field notebook, and the list of observation sessions.

- **Time, Count and Session** at the top choose the period (last 24 hours, 7 days,
  30 days, all time, or custom), what to count (*Verified + unreviewed*, *Verified only*,
  or *Everything except discarded*) and one session or all.
- **Tiles** give the number of animal visits, species, video and sound visits, reviewed
  visits, and visits whose species is still unclear (with their groups: birds, mammals…).
- **Visits per species:** one row per species with visits, how many were reviewed, video
  and sound, and when it was first and last seen.
- **Observation sessions:** one row each time a sensor or camera was started and
  stopped, with start, stop, duration, visits, species, saved clips and three actions:
  **Review** (that session on the Review page), **Camtrap DP** (the Export page with that
  session selected) and **Archive** (every record of that session with its review history).
  **Complete archive** downloads everything since the setup started.

A visit is one tracked animal or one bird call. The same bird can make several visits,
so visits are not a count of individuals. Unreviewed visits are the model's suggestions.

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

The **Detections** panel beside the player shows what is in the frame at the current
position: the leading name in its certainty colour, the look-alikes under it, one line of
scores (detector, similarity, gap) and the top three suggestions as bars. Under it,
**Recently seen** keeps the last 20 seconds of visits that have left the frame; click one
to jump back to it, or its arrow to review it. The full table of observations is below.

## Species

The local species list that the visual model chooses from, built from iNaturalist
research-grade observations for your region (`make taxa ARGS='--place "Kerala, India"'`).
**Refresh taxa** rebuilds it.

## System

- **Live status:** camera and sound input, inference delay, saved clips, weather freshness,
  and this computer's CPU, GPU, memory and storage.
- **Configuration:** Mask people, Forget scenery, sound analysis on or off, and the site
  location, used for day and night and by BirdNET (it narrows only the birds of the local
  list that are outside North India; every North India bird is listened for all year). The analysis tuning (BioCLIP 2.5, detector 0.50, 3 % picture
  edges ignored, 3 frames a second, thresholds, one recording per stay) is fixed for this rig
  and listed on the page. Saving restarts a running observation so changes apply now.
- **Model status:** which models are loaded and on which device.
- **Device access:** private remote access through Tailscale, phone on home Wi-Fi,
  Friends (view only) and the startup service.

## Help

Everything about FALCON in one place: these guides, the sensor node guide, the parts list,
data export, troubleshooting, how the system works, security and licenses. **Search all
guides** finds any word across them; **On this page** jumps to a section. Under
*Handbooks*, the node build handbook opens as a web page, and both handbooks can be
downloaded as PDF for printing.

**Display** (bottom left) opens a small panel above the button with dark or light theme,
text size and higher contrast.

## Reading the numbers

- *Visual similarity* compares the animal crop with species names. It ranks candidates
  but is **not a probability**.
- *BirdNET confidence* is the sound model's own score for a call.
- Times are the inference computer's clock (UTC in exports). A warning appears if its
  clock was not synchronized.
- A visit is not a count of individuals: the same animal can make several visits.
- *Detector confidence* (for example 0.86) only says how sure the detector is that the box
  holds an animal. It plays no part in naming the species.
- The colour of a box or card is its certainty. **Likely** (green): one species is clearly
  ahead. **Probable** (orange): two or three look-alikes score within the top-two margin of
  each other; the card leads with the best one and lists the others ("Spotted Owlet, or
  Jungle Owlet"), with the genus when they share it. **Possible** (red): the best match is
  below the species threshold, shown as a faint guess with a question mark ("Indian
  Pitta?"). **Unknown** (gray): a living thing, but nothing more is clear.
- *Unknown bird* (or mammal, reptile…) means the strongest candidates agree on the group
  even though the species is unclear. *Unknown organism* means not even that is clear.
- The detector was trained on camera-trap photographs of mammals and birds. Insects and
  other very small animals are often not detected at all, and at night insects are never
  named.
- Rats and mice at night are not kept: between sunset and sunrise, a visit whose card shows
  a rat or mouse name (any rat, mouse or bandicoot-rat, or "Mouse or rat (species
  uncertain)") leaves no record, recording or bell; while it is still going on it is
  hidden as "Rat or mouse at night". A visit whose card shows another name is kept, and so
  is one you confirmed, corrected, marked unsure or posted. Gerbils and jirds are kept.
  System → Rats and mice at night shows how many were not kept on the last two nights. By
  day nothing changes.
- In full darkness (not dawn or dusk), a picture visit where the camera model gave no
  species score on any frame is not kept either, unless you judged or posted it; System →
  Pictures with no score at night counts them.
