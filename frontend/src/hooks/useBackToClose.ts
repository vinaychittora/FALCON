// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef } from "react";

let nextLayer = 1;

/**
 * The Android Back gesture closes the top layer instead of leaving the page. The history
 * entry survives React's development double-mount; it is removed shortly after the layer
 * really closes, and only while it is still the newest entry.
 */
export function useBackToClose(onClose: () => void) {
  const close = useRef(onClose);
  const entry = useRef({ layer: 0, hash: "", timer: 0, closedByBack: false });
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const state = entry.current;
    window.clearTimeout(state.timer);
    if (!state.layer) {
      state.layer = nextLayer++;
      state.hash = window.location.hash;
      state.closedByBack = false;
      window.history.pushState(
        { ...(window.history.state ?? {}), falconLayer: state.layer },
        "",
      );
    }
    const onPop = () => {
      const current = (window.history.state as { falconLayer?: number } | null)
        ?.falconLayer;
      if ((current ?? 0) < state.layer) {
        state.closedByBack = true;
        close.current();
      }
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      state.timer = window.setTimeout(() => {
        const top =
          (window.history.state as { falconLayer?: number } | null)
            ?.falconLayer === state.layer;
        if (!state.closedByBack && top && window.location.hash === state.hash)
          window.history.back();
        state.layer = 0;
      }, 0);
    };
  }, []);
}
