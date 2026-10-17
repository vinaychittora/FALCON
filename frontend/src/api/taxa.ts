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
