// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
// A wet rain plate means rain or dew on the plate, not a rainfall amount.
export const wetness = (value: boolean | null | undefined) =>
  value === true ? "Wet" : value === false ? "Dry" : "—";
