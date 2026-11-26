// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState } from "react";
import { api } from "../api/client";

interface Retention {
  used_bytes: number;
  per_day_bytes: number;
  kept_for_good: number;
  keep_days: number;
  first_thinning: string | null;
}

const gb = (bytes: number) => `${(bytes / 1e9).toFixed(bytes < 10e9 ? 1 : 0)} GB`;

/** One line under System: what recordings use and how they are kept. */
export function recordingsLine(r: Retention): string {
  return (
    `Recordings use ${gb(r.used_bytes)}, about ${gb(r.per_day_bytes)} a day · ` +
    `${r.kept_for_good} kept for good (confirmed or corrected) · ` +
    `discarded ones go within the hour, hidden ones you do not review are cleared after 7 days, ` +
    `the rest after ${r.keep_days} days` +
    (r.first_thinning ? ` (first ${r.keep_days}-day thinning ${r.first_thinning})` : "")
  );
}

export default function RecordingsLine() {
  const [value, setValue] = useState<Retention | null>(null);
  useEffect(() => {
    api<Retention>("/evidence/retention")
      .then(setValue)
      .catch(() => setValue(null));
  }, []);
  if (!value) return null;
  return <p className="live-system-caption">{recordingsLine(value)}</p>;
}
