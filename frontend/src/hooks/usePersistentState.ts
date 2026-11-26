// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useState } from "react";

const PREFIX = "falcon.ui.";

export function readPersistent<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    const value: unknown = JSON.parse(raw);
    return typeof value === typeof fallback ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writePersistent<T>(key: string, value: T): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* per-browser convenience only */
  }
}

/**
 * useState that is remembered in this browser, so a switch keeps its position across
 * pages, reloads and FALCON restarts. Only simple values of the same type are restored.
 */
export function usePersistentState<T extends string | number | boolean>(
  key: string,
  fallback: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => readPersistent(key, fallback));
  const update = useCallback(
    (next: T) => {
      setValue(next);
      writePersistent(key, next);
    },
    [key],
  );
  return [value, update];
}
