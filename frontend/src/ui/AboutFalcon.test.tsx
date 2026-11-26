// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AboutFalcon from "./AboutFalcon";
import { LICENCE_TEXT, SOURCE_URL, TERMS_TEXT } from "./aboutTexts";
import { CREDIT_LINE, FALCON_VERSION } from "../version";

describe("About FALCON (release 2.0)", () => {
  const html = renderToStaticMarkup(<AboutFalcon onClose={() => {}} />);

  it("names the release, the developer, the copyright and the licence", () => {
    expect(html).toContain(`FALCON ${FALCON_VERSION}`);
    expect(html).toContain("Field Acoustic, Lens &amp; Climate Observation Node");
    expect(html).toContain("Developer: Vinay Chittora");
    expect(html).toContain("Copyright (C) 2026 Vinay Chittora");
    expect(html).toContain("WITHOUT ANY WARRANTY");
    expect(html).toContain(
      "Licence: GNU Affero General Public License, version 3, with additional terms on author credit and naming",
    );
    expect(html).toContain("Read the licence");
    expect(html).toContain("Read the additional terms");
  });

  it("links the source code in a new tab", () => {
    expect(SOURCE_URL).toBe("https://github.com/vinaychittora/FALCON");
    expect(html).toContain(`href="${SOURCE_URL}"`);
    expect(html).toContain('target="_blank"');
    expect(html).toContain("github.com/vinaychittora/FALCON");
  });

  it("bundles the repository's own licence files", () => {
    expect(LICENCE_TEXT).toContain("GNU AFFERO GENERAL PUBLIC LICENSE");
    expect(LICENCE_TEXT).toContain("Version 3, 19 November 2007");
    expect(TERMS_TEXT).toContain("# Additional terms for FALCON");
  });

  it("keeps the credit line the terms ask for, with this release's number", () => {
    expect(CREDIT_LINE).toBe("FALCON 2.0 · Vinay Chittora");
  });
});
