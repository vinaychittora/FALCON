// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-22" → "22 Nov", from its parts (no time zone conversion). */
function evening(day: string): string {
  const [, month, date] = day.split("-").map(Number);
  return month && date ? `${date} ${MONTHS[month - 1]}` : day;
}

/** System line for rats and mice at night: the two most recent nights with a count,
 * dated by the evening the night began. `recent` is "2026-11-22:220,2026-11-21:124". */
export function rodentNights(recent: unknown): string {
  const nights = String(recent ?? "")
    .split(",")
    .map((part) => part.split(":"))
    .filter(([day, count]) => day && Number(count) > 0)
    .slice(0, 2);
  if (!nights.length) return "Not kept · none so far";
  const [first, second] = nights;
  const text = `${first[1]} on the night of ${evening(first[0])}`;
  return second ? `Not kept · ${text}, ${second[1]} on ${evening(second[0])}` : `Not kept · ${text}`;
}
