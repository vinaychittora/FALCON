// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useState } from "react";
import { ShellSheet } from "../components/Shell";
import { FALCON_VERSION } from "../version";
import { ABOUT, LICENCE_TEXT, SOURCE_URL, TERMS_TEXT } from "./aboutTexts";
import "./about.css";

type View = "about" | "licence" | "terms";

/** "About FALCON" (26 Nov, release 2.0): the credit, the copyright, the warranty notice, the
 * licence with its additional terms (the repository's own files, bundled at build time) and
 * the link to the source code. Opened from the credit line and from Help. */
export default function AboutFalcon({ onClose }: { onClose: () => void }) {
  const [view, setView] = useState<View>("about");
  return (
    <ShellSheet title="About FALCON" onClose={onClose}>
      {view === "about" ? (
        <div className="ab-body rv-gut">
          <p className="ab-name">
            <strong>FALCON {FALCON_VERSION}</strong>
            <span>{ABOUT.longName}</span>
          </p>
          <p>{ABOUT.developer}</p>
          <p>{ABOUT.copyright}</p>
          <p className="ab-muted">{ABOUT.warranty}</p>
          <p>{ABOUT.licence}</p>
          <div className="ab-actions">
            <button type="button" className="button" onClick={() => setView("licence")}>
              Read the licence
            </button>
            <button type="button" className="button" onClick={() => setView("terms")}>
              Read the additional terms
            </button>
          </div>
          <p>
            Source code:{" "}
            <a href={SOURCE_URL} target="_blank" rel="noopener noreferrer">
              github.com/vinaychittora/FALCON
            </a>
          </p>
        </div>
      ) : (
        <div className="ab-text rv-gut">
          <button type="button" className="text-button ab-back" onClick={() => setView("about")}>
            Back to About FALCON
          </button>
          <h3>{view === "licence" ? "GNU Affero General Public License, version 3" : "Additional terms"}</h3>
          <pre tabIndex={0} aria-label={view === "licence" ? "Licence text" : "Additional terms text"}>
            {view === "licence" ? LICENCE_TEXT : TERMS_TEXT}
          </pre>
        </div>
      )}
    </ShellSheet>
  );
}
