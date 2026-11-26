// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
// The repository's own licence files, bundled at build time (never fetched, never edited).
import LICENCE_RAW from "../../../LICENSE?raw";
import TERMS_RAW from "../../../ADDITIONAL-TERMS.md?raw";

export const LICENCE_TEXT: string = LICENCE_RAW;
export const TERMS_TEXT: string = TERMS_RAW;

export const SOURCE_URL = "https://github.com/vinaychittora/FALCON";

/** The About sheet's lines: the credit and copyright from NOTICE, and the warranty sentence
 * of the AGPL's own notice. */
export const ABOUT = {
  longName: "Field Acoustic, Lens & Climate Observation Node",
  developer: "Developer: Vinay Chittora",
  copyright: "Copyright (C) 2026 Vinay Chittora",
  warranty:
    "This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.",
  licence:
    "Licence: GNU Affero General Public License, version 3, with additional terms on author credit and naming",
} as const;
