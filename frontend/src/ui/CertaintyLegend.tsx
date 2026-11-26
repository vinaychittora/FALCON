// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
/** The colour code used on boxes and cards. */
export default function CertaintyLegend() {
  return (
    <p className="certainty-legend" aria-label="Colour code">
      <span className="certainty-likely">
        <i aria-hidden="true" /> Likely
      </span>
      <span className="certainty-probable">
        <i aria-hidden="true" /> Probable · look-alikes, often one genus
      </span>
      <span className="certainty-possible">
        <i aria-hidden="true" /> Possible · faint guess
      </span>
      <span className="certainty-unknown">
        <i aria-hidden="true" /> Unknown
      </span>
    </p>
  );
}
