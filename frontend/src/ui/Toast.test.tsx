// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Toast, { TOAST_MS } from "./Toast";

describe("Toast", () => {
  it("is a brief status message that can be tapped away", () => {
    const html = renderToStaticMarkup(
      <Toast message="Review saved." onClose={() => undefined} />,
    );
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="Review saved. Dismiss"');
    expect(html).toContain("<button");
    expect(TOAST_MS).toBeGreaterThanOrEqual(2000);
    expect(TOAST_MS).toBeLessThanOrEqual(3000);
  });
});
