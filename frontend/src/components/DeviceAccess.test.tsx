import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { ResourceNotice, StartupControls } from "./DeviceAccess";

it("shows a restart compatibility message for an older backend", () => {
  const html = renderToStaticMarkup(
    <ResourceNotice resource={{ kind: "unavailable" }} />,
  );
  expect(html).toContain("Available after engine restart");
  expect(html).not.toContain('role="alert"');
});

it("requires a saved camera before automatic startup observation can be enabled", () => {
  const html = renderToStaticMarkup(
    <StartupControls
      appliance={{
        auto_observe: false,
        camera_saved: false,
        state: "disabled",
        message: "",
      }}
      pending={false}
      onChange={() => {}}
    />,
  );
  expect(html).toMatch(/<input[^>]*disabled=""/);
  expect(html).toContain("Save a camera");
  expect(html).toContain("next engine startup");
});

it("lets an approved remote admin change startup preference independently of local access management", () => {
  const html = renderToStaticMarkup(
    <StartupControls
      appliance={{
        auto_observe: true,
        camera_saved: true,
        state: "ready",
        message: "",
      }}
      pending={false}
      onChange={() => {}}
    />,
  );
  expect(html).toMatch(/<input[^>]*checked=""/);
  expect(html).not.toMatch(/<input[^>]*disabled=""/);
});

it("allows an existing automatic-observation preference to be turned off after its camera was removed", () => {
  const html = renderToStaticMarkup(
    <StartupControls
      appliance={{
        auto_observe: true,
        camera_saved: false,
        state: "failed",
        message: "Saved camera unavailable",
      }}
      pending={false}
      onChange={() => {}}
    />,
  );
  expect(html).toMatch(/<input[^>]*checked=""/);
  expect(html).not.toMatch(/<input[^>]*disabled=""/);
});
