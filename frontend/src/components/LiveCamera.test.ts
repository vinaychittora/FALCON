// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { canReuseCameraPassword, validateCameraUrl } from "./LiveCamera";

describe("camera address input", () => {
  it("accepts RTSP addresses with explicit paths and optional ports", () => {
    expect(validateCameraUrl("rtsp://192.0.2.10:554/stream1")).toBeNull();
    expect(validateCameraUrl("rtsps://camera.local/backyard")).toBeNull();
  });
  it("requires credentials to use their separate fields", () => {
    expect(
      validateCameraUrl("rtsp://camerauser:secret@camera.test/stream1"),
    ).toContain("separate fields");
    expect(
      validateCameraUrl("rtsp://camerauser@camera.test/stream1"),
    ).toContain("separate fields");
  });
  it("rejects web URLs and incomplete addresses", () => {
    expect(validateCameraUrl("https://example.com/video")).not.toBeNull();
    expect(validateCameraUrl("192.0.2.10")).not.toBeNull();
    expect(validateCameraUrl("")).not.toBeNull();
  });
});

describe("saved camera password reuse", () => {
  const profile = {
    saved: true,
    name: "Camera",
    url: "rtsp://camera.local/stream1",
    username: "observer",
    has_password: true,
    audio_enabled: true,
    updated_at: null,
  };
  it("reuses a saved password only for its matching camera and account", () => {
    expect(canReuseCameraPassword(profile, profile.url, "observer", "")).toBe(
      true,
    );
    expect(
      canReuseCameraPassword(
        profile,
        "rtsp://other.local/stream1",
        "observer",
        "",
      ),
    ).toBe(false);
    expect(canReuseCameraPassword(profile, profile.url, "different", "")).toBe(
      false,
    );
    expect(
      canReuseCameraPassword(profile, profile.url, "observer", "replacement"),
    ).toBe(false);
    expect(canReuseCameraPassword(null, profile.url, "observer", "")).toBe(
      false,
    );
  });
});
