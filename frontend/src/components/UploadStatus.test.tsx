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
