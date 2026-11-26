// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import UploadStatus from "./UploadStatus";

it("announces the pending file without inventing upload progress", () => {
  const html = renderToStaticMarkup(<UploadStatus filename="sample.mp4" />);
  expect(html).toContain('role="status"');
  expect(html).toContain("sample.mp4");
  expect(html).toContain("Uploading and checking the source");
  expect(html).not.toContain("%");
});
