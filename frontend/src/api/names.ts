import type { Detection } from "../types";

interface TaxonName {
  taxon_id: number;
  scientific_name: string;
  common_name: string | null;
}
export interface TaxonNameIndex {
  byId: ReadonlyMap<number, TaxonName>;
  byScientificName: ReadonlyMap<string, TaxonName>;
}
const scientificKey = (name: string) => name.trim().toLocaleLowerCase("en");

export function indexTaxonNames(taxa: readonly TaxonName[]): TaxonNameIndex {
  return {
    byId: new Map(taxa.map((taxon) => [taxon.taxon_id, taxon])),
    byScientificName: new Map(
      taxa.map((taxon) => [scientificKey(taxon.scientific_name), taxon]),
    ),
  };
}

/** Resolve old reviews without rewriting their stored identification or model output. */
export function correctedNames(event: Detection, taxa?: TaxonNameIndex) {
  const review = event.review;
  const scientific = review.corrected_scientific_name?.trim() || null;
  const taxon =
    (review.corrected_taxon_id
      ? taxa?.byId.get(review.corrected_taxon_id)
      : undefined) ??
    (scientific
      ? taxa?.byScientificName.get(scientificKey(scientific))
      : undefined);
  const candidates =
    event.modality === "visual"
      ? [
          ...event.classification.top_k,
          ...(event.classification.model_evidence ?? []).flatMap(
            (model) => model.top_k,
          ),
        ]
      : [
          {
            taxon_id: 0,
            scientific_name: event.scientific_name,
            common_name: event.common_name,
          },
        ];
  const matchingPrediction = candidates.find(
    (candidate) =>
      (review.corrected_taxon_id != null &&
        candidate.taxon_id === review.corrected_taxon_id) ||
      (!!scientific &&
        !!candidate.scientific_name &&
        scientificKey(candidate.scientific_name) === scientificKey(scientific)),
  );
  return {
    common:
      review.corrected_common_name?.trim() ||
      taxon?.common_name?.trim() ||
      matchingPrediction?.common_name?.trim() ||
      null,
    scientific:
      scientific ||
      taxon?.scientific_name ||
      matchingPrediction?.scientific_name ||
      null,
  };
}
