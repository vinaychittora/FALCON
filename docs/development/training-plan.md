# Local classifier and mini-PC plan

No training, dataset download or evidence-crop collection ran during implementation.
The working baseline uses MegaDetector proposals, BioCLIP 2 regional candidates and
independent BirdNET acoustic detections.

## What the backyard run actually shows

The saved run `1248ee26-e124-4c34-b8b8-67e52f384b07` used the 1,369-species
Rajasthan cache, including Sulphur-bellied Warbler. Adding a taxon creates a text
candidate; it does not train the classifier on that bird's appearance. Review edits
currently annotate records and do not update model weights.

| Example | Best candidate / closest alternative | Remaining problem |
| --- | --- | --- |
| Warbler, 16.5–17.5 s | Sulphur-bellied Warbler 0.767689 / Tickell's Leaf Warbler 0.761165 | Margin 0.006524, below 0.025. Earlier frames slightly favor Tickell's. |
| Magpie-robin, 21.5–23.5 s | Oriental Magpie-Robin 0.734654 / Indian Robin 0.719295 | Margin 0.015359, below 0.025. |
| Bee-like subject, 1.0 s | Xylocopa pubescens 0.698573 / X. fenestrata 0.686082 | Margin 0.012491, below 0.025; species identity needs review. |

These are cosine similarities, not probability percentages or verified labels.
All three have detector proposals. The audit found no duplicate IDs, scientific
names or text vectors, and no subspecies candidates causing these near-ties.
There are no Bombus candidates in the current cache; if review establishes a
bumblebee, its relevant regional species must be included explicitly. Detection
recall, especially for other insects, cannot be measured from proposals alone.
Neighboring records reuse temporal evidence and are not independent confirmations.

## Next experiment, in order

1. Annotate the existing backyard recording with confirmed species, timestamps and
   tight boxes, including visible animals the detector missed. Prioritize 0–1.5 s,
   12.5–17.5 s and 21.5–24 s. Compare classification on manual boxes against detector
   boxes to distinguish poor localization from poor species recognition. Keep this
   recording as a documented regression example, not an unbiased final test after
   tuning against it.
2. Curate independent encounters of the targets and their lookalikes, including
   different poses, distances, light, sexes/plumages where relevant, partial bodies
   and empty foliage. Preserve uncertain identifications as uncertain. Include
   seasonal visitors; regional observation counts are not reliable absence evidence.
3. First compare the existing text baseline against a small classifier trained on
   frozen BioCLIP image embeddings. The official [BioCLIP tutorial](https://imageomics.github.io/pybioclip/python-tutorial/#lightweight-classifiers)
   provides SVM, Ridge and SimpleShot examples for this experiment. Retain broad
   candidates and unknown rejection. This tests whether reviewed examples help;
   a small classification head still requires the large BioCLIP image encoder.
4. Measure box recall by subject size. If insects or small birds lack usable boxes,
   train a compact detector with local annotated boxes and foliage/background
   negatives. Compare targeted high-resolution regions against full-frame inference.
   The current tiling option adds compute; it is not evidence of sufficient recall.
   [MegaDetector's official documentation](https://github.com/microsoft/MegaDetector)
   describes its detector/classifier separation and fine-tuning support.
5. Evaluate held-out encounters: animal localization recall, species precision and
   recall, wrong confident names, unknown rejection, false alarms per hour and
   detection delay. Tune rejection thresholds on validation data, including unseen
   species. A single global margin is a baseline, not a calibrated probability.
6. If the local classifier improves held-out results, train and compare a compact
   image model for deployment. Run the same evaluation after ONNX export and any
   quantization, then benchmark sustained camera + audio workloads on the actual
   mini PC. Desktop GPU results cannot establish that deployment's performance.

Audio remains independent evidence of a bird heard nearby. A call cannot establish
that the visible bird is the caller. Keep visual and acoustic scores separate until
an explicitly evaluated association method exists.

## Dataset and training contract

The coverage goal is India-wide birds, butterflies, reptiles and mammals. Build and
maintain a broad species inventory, explicitly marking missing images and insufficient
validation; do not call a list of names a trained model. Prove the training workflow
with 20–40 priority local species and their lookalikes, including seasonal visitors,
then expand in measured batches. Include unknown/background, hard negatives,
confusing species, partial animals, empty scenes and different lighting/weather. Collect
only deliberately reviewed crops with provenance and an explicit retention policy.
`SAVE_REVIEWED_CROPS=false` is reserved for future collection; changing it currently
does not enable crop storage.

Optional iNaturalist examples must have photo-level CC0, CC BY or CC BY-SA permission.
Retain observation ID, photo ID, creator, source URL, taxon ID, scientific name, license
and attribution. Observation licenses do not establish image licenses. Use the official
API with rate limits and cached metadata, never image-search scraping. Downloads must
be explicitly invoked and respect a byte budget; no bulk downloader runs with app setup.

### Public data sources and availability, checked 17 October 2026

Use [iNaturalist Licensed Observation Images](https://registry.opendata.aws/inaturalist-open-data/)
as the main image source. It supplies actual image files and monthly metadata without
requiring an AWS account. iNaturalist's [official photo export guidance](https://help.inaturalist.org/en/support/solutions/articles/151000223300-how-i-download-inaturalist-photos-to-use-for-research-)
directs bulk research downloads there. Small API queries are suitable for availability
audits; use the bulk/export route for a large national collection, respecting the
[documented usage limits](https://www.inaturalist.org/pages/api+recommended+practices).

The aggregate API audit used India place 6681, research grade, wild observations,
photos, identification at species or below, and photo licenses CC0 / CC BY / CC BY-SA.
India and group taxon IDs were first resolved through the official autocomplete API.
Results are observations with matching photo metadata, not counts of ready-to-train
images or guaranteed independent encounters. Inactive/non-species results were excluded.

| Group | Active species represented | Qualifying observations | Species with at least 100 observations |
| --- | ---: | ---: | ---: |
| Birds (Aves) | 1,058 | 113,743 | 259 |
| Butterflies (Papilionoidea) | 746 | 57,082 | 138 |
| Reptiles (Reptilia) | 375 | 10,343 | 22 |
| Mammals (Mammalia) | 199 | 10,718 | 27 |

This is a filtered source inventory, not a complete Indian fauna checklist or a claim
that every represented species has sufficient data. Counts can change. Query URLs,
filters and the timestamp are saved in [the availability report](india-data-availability.json).
The full per-species audit is local at
`data/cache/india-data-availability-2026-10-17.json`; no photos were downloaded.

| Priority species | Qualifying India observations | Qualifying worldwide observations |
| --- | ---: | ---: |
| Sulphur-bellied Warbler | 14 | 34 |
| Oriental Magpie-Robin | 1,036 | 3,129 |
| Indian Garden Lizard | 1,532 | 2,721 |

Target species occurring in India, while allowing licensed images of the same species
from other countries to fill gaps. Preserve country/source provenance and account for
subspecies/plumage differences. Geographic frequency is a soft contextual signal;
migrants must not be excluded merely because regional photographs are scarce.

Other sources have different roles:

- [GBIF](https://techdocs.gbif.org/en/data-use/download-formats) can identify additional
  records and media URLs. Its downloads are occurrence metadata, not a bundled image
  library. Check [media-specific licenses](https://techdocs.gbif.org/en/openapi/images)
  and deduplicate iNaturalist records appearing in both sources.
- [Bird Count India / eBird](https://birdcount.in/using-ebird-data-for-research/) can help
  establish bird occurrence and seasonality. Its media catalog is not a blanket license
  to download training photos; see [Macaulay Library permissions](https://support.ebird.org/en/support/solutions/articles/48000960529).
- [Butterflies of India](https://ifoundbutterflies.org/data-privacy) is useful for
  identification and regional references. Contributors retain image copyright;
  obtain appropriate permission before treating it as a training image source.

### Concrete collection and training sequence

1. Reconcile an India species inventory with regional checklists and current taxonomy.
   Record photo availability, provenance and unresolved gaps per species, including
   species with no eligible public images. The audit above is the first input, not a
   completed national checklist.
2. Implement the optional downloader (currently a scaffold): select a balanced pilot
   of target species and lookalikes, at most 100 observations per species and one
   suitable photo per observation initially. Use a hard cumulative 2 GB dataset cap
   for the first pilot, with a resumable manifest, photo-specific attribution, download
   hashes and a failure report. This is a cap, not a forecast of actual size or enough
   data for every species. Larger collections require the size approval specified in
   the original project brief. A manifest preview must precede image collection.
3. Reject duplicates, broken files and images without the target animal. Research
   Grade helps with labels but is not perfect: observations may contain habitat images
   or only a genus-level identification. See [the official quality criteria](https://help.inaturalist.org/en/support/solutions/articles/151000169936).
   Review difficult labels and a sample of each class. Do not require the user to
   manually label the entire public collection.
4. Separate complete encounters/observations into train, validation and test. Keep
   reviewed local recordings as an additional domain test, with whole encounters held
   out. Train a local classifier and compare against the existing BioCLIP baseline.
   Public close-up photo performance cannot establish distant CCTV performance.
5. For missed insects/small birds, collect or review bounding boxes in representative
   scenes and train/evaluate the detector separately. Species labels on public images
   generally do not supply these boxes. Review proposed boxes rather than treating
   model-generated boxes as ground truth.
6. Expand the collection and trained classes after measured improvement. Deploy a
   validated compact model to the mini PC; the full training image collection can stay
   on the development machine. Preserve an unknown/genus fallback for unsupported
   species and test CPU performance with audio and camera decoding running together.

The download, training and ONNX export scripts below remain scaffolds. The availability
audit and this plan do not mean a new model has been trained or installed.

Each JSONL row needs `sample_id`, `path`, `scientific_name`, `encounter_id`, `source`
(`reviewed_local` or `inaturalist`). Local rows also require `reviewed: true`. iNaturalist
rows require the provenance fields above and a lowercase `license` of `cc0`, `cc-by`
or `cc-by-sa`. Assign every adjacent frame/crop from one recording encounter the same
encounter ID. For iNaturalist, use observation ID as encounter ID.

From the repository after `source scripts/env.sh`:

| Script | Current behavior |
| --- | --- |
| `python training/download_inat_dataset.py curated.jsonl` | Validates provenance and emits a plan; downloads nothing. |
| `python training/build_dataset.py reviewed.jsonl split.jsonl` | Writes deterministic 70/15/15 encounter-group splits; refuses to overwrite output. |
| `python training/train_local_classifier.py split.jsonl` | Checks split boundaries and emits a MobileNetV3-small or EfficientNet-B0 experiment plan; does not train. |
| `python training/evaluate.py split.jsonl predictions.jsonl` | Computes held-out sample accuracy, macro/per-class recall and confusion counts. Predictions need `sample_id` and `predicted_scientific_name`. |
| `python training/export_onnx.py` | Emits the deployment contract; actual export awaits a trained model. |

The split utility avoids encounter leakage but does not guarantee class balance. Audit
class and encounter coverage. Hold out whole days/sites for final evaluation, and never
mix neighboring video frames across training and test. Include encounter-level confidence
intervals, unknown rejection and false alarms per hour. Sample-level accuracy alone is
not enough. Compare the compact classifier and frozen BioCLIP 2 on the same untouched
test events. Tune thresholds only on validation.

Train transfer learning on the development RTX 3060 Ti after dataset review. Export ONNX
with a versioned class-to-taxon map, RGB preprocessing, input size and unknown threshold.
Check PyTorch/ONNX logit agreement before quantization. Test sustained performance on
the actual mini PC with camera decode, audio and sensor workloads present.

Keep the detector/classifier/audio interfaces replaceable. Live RTSP capture, bounded
queues, reconnection and BirdNET audio windows are implemented; see
[live validation](../validation/live-validation.md). Sensors remain disconnected placeholders.
Future sensor integration should poll independently and attach the latest prior
reading, timestamp and age to detections, with stale/unavailable states. Further
audio worker optimization and overlap handling must be evaluated for latency and
duplicate detections on the mini PC.
