// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
/** Retry only unsuccessful initial reads; successful editable data stays local. */
export function initialResourceLoader(tasks: Array<() => Promise<boolean>>) {
  const pending = new Set(tasks);
  let running = false;
  return async () => {
    if (running || !pending.size) return;
    running = true;
    try {
      await Promise.all(
        [...pending].map(async (task) => {
          try {
            if (await task()) pending.delete(task);
          } catch {
            // A failed read remains pending until the next retry.
          }
        }),
      );
    } finally {
      running = false;
    }
  };
}
