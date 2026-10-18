// A wet rain plate means rain or dew on the plate, not a rainfall amount.
export const wetness = (value: boolean | null | undefined) =>
  value === true ? "Wet" : value === false ? "Dry" : "—";
