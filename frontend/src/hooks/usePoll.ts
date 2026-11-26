// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useEffect, useRef, useState } from "react";
import { inBackground, NetworkError } from "../api/activity";

/**
 * Load a resource now and every `interval` ms; keeps the last good value on errors.
 * A new `key` cancels the request still running for the old one (its signal aborts) and
 * a late answer for an old key is never kept. `fresh` says the data belongs to the
 * current key, so a page can show stale data as stale (Review, 25 Nov).
 */
export function usePoll<T>(
  load: (signal: AbortSignal) => Promise<T>,
  interval: number,
  key = "",
): {
  data: T | null;
  error: string;
  refresh: () => void;
  setData: (value: T) => void;
  fresh: boolean;
} {
  const [state, setState] = useState<{ data: T | null; key: string | null }>({
    data: null,
    key: null,
  });
  const [error, setError] = useState("");
  const loader = useRef(load);
  const currentKey = useRef(key);
  const running = useRef(false);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  // The first load for a key is what the user waits for (it shows as loading); the repeats
  // run in the background and only count as heartbeats.
  const firstOfKey = useRef(true);
  useEffect(() => {
    loader.current = load;
    currentKey.current = key;
  });
  const refresh = useCallback(() => {
    if (running.current) return;
    running.current = true;
    const current = generation.current;
    const asked = currentKey.current;
    const control = new AbortController();
    controller.current = control;
    const foreground = firstOfKey.current;
    firstOfKey.current = false;
    const start = () => loader.current(control.signal);
    (foreground ? start() : inBackground(start))
      .then((value) => {
        if (current !== generation.current) return;
        setState({ data: value, key: asked });
        setError("");
      })
      .catch((reason: unknown) => {
        if (current !== generation.current || control.signal.aborted) return;
        // A lost connection is the status line's to report; the page keeps its data.
        if (reason instanceof NetworkError) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (current === generation.current) running.current = false;
      });
  }, []);
  useEffect(() => {
    generation.current += 1;
    running.current = false;
    firstOfKey.current = true;
    refresh();
    const timer = interval > 0 ? setInterval(refresh, interval) : undefined;
    return () => {
      clearInterval(timer);
      // The key changed or the page closed: the old request is no longer wanted.
      controller.current?.abort();
    };
  }, [interval, key, refresh]);
  const setData = useCallback(
    (value: T) => setState({ data: value, key: currentKey.current }),
    [],
  );
  return { data: state.data, error, refresh, setData, fresh: state.key === key };
}
