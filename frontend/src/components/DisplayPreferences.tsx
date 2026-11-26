// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef, useState } from "react";
import {
  applyDisplayPreferences,
  DISPLAY_STORAGE_KEY,
  parseDisplayPreferences,
  readDisplayPreferences,
  saveDisplayPreferences,
  type DisplayPreferences as Preferences,
} from "../api/displayPreferences";
import Icon from "./Icon";
import "./display-preferences.css";

export default function DisplayPreferences() {
  const [preferences, setPreferences] = useState(readDisplayPreferences);
  const [canPersist, setCanPersist] = useState(true);
  const disclosure = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    applyDisplayPreferences(preferences);
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onSystemTheme = () => applyDisplayPreferences(preferences);
    query?.addEventListener("change", onSystemTheme);
    return () => query?.removeEventListener("change", onSystemTheme);
  }, [preferences]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === DISPLAY_STORAGE_KEY || event.key === null) {
        setPreferences(parseDisplayPreferences(event.newValue));
      }
    };
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !disclosure.current?.contains(event.target)
      ) {
        disclosure.current?.removeAttribute("open");
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && disclosure.current?.open) {
        disclosure.current.open = false;
        disclosure.current.querySelector("summary")?.focus();
      }
    };
    window.addEventListener("storage", onStorage);
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("storage", onStorage);
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  function update(next: Preferences) {
    setPreferences(next);
    setCanPersist(saveDisplayPreferences(next));
  }

  return (
    <details className="display-preferences" ref={disclosure}>
      <summary aria-label="Display and accessibility options">
        <Icon name="display" size={19} />
        <span>Display</span>
      </summary>
      <div className="display-popover">
        <strong>Display &amp; accessibility</strong>
        <label>
          Theme
          <select
            aria-label="Theme"
            value={preferences.theme}
            onChange={(event) =>
              update({
                ...preferences,
                theme: event.target.value as Preferences["theme"],
              })
            }
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">Follow device</option>
          </select>
        </label>
        <label>
          Text size
          <select
            aria-label="Text size"
            value={preferences.textSize}
            onChange={(event) =>
              update({
                ...preferences,
                textSize: event.target.value as Preferences["textSize"],
              })
            }
          >
            <option value="standard">Standard</option>
            <option value="large">Larger</option>
            <option value="extra-large">Largest</option>
          </select>
        </label>
        <label>
          Navigation
          <select
            aria-label="Navigation"
            value={preferences.navigation}
            onChange={(event) =>
              update({
                ...preferences,
                navigation: event.target.value as Preferences["navigation"],
              })
            }
          >
            <option value="side">Side column</option>
            <option value="top">Top bar (more room)</option>
          </select>
        </label>
        <label className="contrast-option">
          <input
            type="checkbox"
            checked={preferences.contrast === "high"}
            onChange={(event) =>
              update({
                ...preferences,
                contrast: event.target.checked ? "high" : "standard",
              })
            }
          />
          Higher contrast
        </label>
        <small>
          {canPersist
            ? "Saved in this browser."
            : "Applied for this tab. Browser storage is unavailable."}
        </small>
      </div>
    </details>
  );
}
