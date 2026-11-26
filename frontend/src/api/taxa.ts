// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
export const groupNames: Record<string, string> = {
  Aves: "Birds",
  Mammalia: "Mammals",
  Reptilia: "Reptiles",
  Amphibia: "Amphibians",
  Lepidoptera: "Butterflies & moths",
  Odonata: "Dragonflies & damselflies",
  Hymenoptera: "Bees, wasps & ants",
  Insecta: "Other insects",
  Arachnida: "Arachnids",
  organism: "Unidentified organism",
};

export function groupName(value: string) {
  return groupNames[value] ?? value;
}
