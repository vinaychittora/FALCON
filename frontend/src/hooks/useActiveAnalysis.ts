// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Job } from "../types";

/** Engine ownership must not disappear when another source/run is selected. */
export function useActiveAnalysis() {
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let stopped = false;
    let loading = false;
    async function load() {
      if (loading || stopped) return;
      loading = true;
      try {
        const active = await api<Job | null>("/jobs/active");
        if (!stopped) {
          setJob(active);
          setError("");
          setLoading(false);
        }
      } catch (error) {
        if (!stopped) {
          // Older running backends do not expose global engine state yet.
          if (error instanceof ApiError && error.status === 404) {
            setJob(null);
            setError("");
          } else {
            setError(error instanceof Error ? error.message : String(error));
          }
          setLoading(false);
        }
      } finally {
        loading = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 1500);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [revision]);
  return { job, loading, error, refresh };
}
