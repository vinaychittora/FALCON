import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PictureControl } from "../api/nodes";
import PictureControls, { controlLabel, menuLabel } from "./PictureControls";

const exposure: PictureControl = {
  name: "auto_exposure",
  type: "menu",
  min: 0,
  max: 3,
  step: 1,
  default: 3,
  value: 3,
  inactive: false,
  menu: [
    [1, "Manual Mode"],
    [3, "Aperture Priority Mode"],
  ],
};

describe("webcam picture controls", () => {
  it("names controls the way people know them", () => {
    expect(controlLabel(exposure)).toBe("Exposure");
    expect(menuLabel(exposure, 1, "Manual Mode")).toBe("Manual");
    expect(menuLabel(exposure, 3, "Aperture Priority Mode")).toBe("Automatic");
    expect(controlLabel({ ...exposure, name: "zoom_absolute" })).toBe(
      "zoom absolute",
    );
    expect(controlLabel({ ...exposure, name: "sharpness" })).toBe("Sharpening");
  });

  it("shows a loading state before the node answers", () => {
    expect(renderToStaticMarkup(<PictureControls nodeId="node-1" />)).toContain(
      "Reading the camera",
    );
  });
});
