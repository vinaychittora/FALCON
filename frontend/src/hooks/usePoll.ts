import { useCallback, useEffect, useRef, useState } from "react";

/** Load a resource now and every `interval` ms; keeps the last good value on errors. */
export function usePoll<T>(
  load: () => Promise<T>,
  interval: number,
  key = "",
): {
  data: T | null;
  error: string;
  refresh: () => void;
  setData: (value: T) => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const loader = useRef(load);
  const running = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    loader.current = load;
  });
  const refresh = useCallback(() => {
    if (running.current) return;
    running.current = true;
    const current = generation.current;
    loader
      .current()
      .then((value) => {
        if (current !== generation.current) return;
        setData(value);
        setError("");
      })
      .catch((reason: unknown) => {
        if (current !== generation.current) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        running.current = false;
      });
  }, []);
  useEffect(() => {
    generation.current += 1;
    running.current = false;
    refresh();
    if (interval <= 0) return;
    const timer = setInterval(refresh, interval);
    return () => clearInterval(timer);
  }, [interval, key, refresh]);
  return { data, error, refresh, setData };
}
