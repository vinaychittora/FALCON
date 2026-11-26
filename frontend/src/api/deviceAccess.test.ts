// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  canOpenAdminAccess,
  canEditAdminLogins,
  connectivityCheckLabel,
  parseAdminLogins,
  readDeviceAccess,
  sameAdmins,
  shareAddress,
  type RemoteAccessState,
} from "./deviceAccess";

const connected: RemoteAccessState = {
  installed: true,
  connected: true,
  enabled: false,
  url: null,
  hostname: "falcon",
  admin_logins: ["admin@example.org"],
  message: "Ready",
  internet: "unchecked",
  can_manage: true,
};
afterEach(() => vi.unstubAllGlobals());

describe("private device access", () => {
  it("requires access to be closed before the approved-admin list can change", () => {
    expect(canEditAdminLogins(connected)).toBe(true);
    expect(canEditAdminLogins({ ...connected, enabled: true })).toBe(false);
    expect(canEditAdminLogins({ ...connected, can_manage: false })).toBe(false);
  });

  it("describes endpoint-check results without claiming general internet availability", () => {
    expect(connectivityCheckLabel("offline")).toBe("Check failed");
    expect(connectivityCheckLabel("online")).toBe("Endpoint responded");
    expect(connectivityCheckLabel("unchecked")).toBe("Not checked");
  });
  it("normalizes explicit admin logins without adding anyone", () => {
    expect(
      parseAdminLogins(
        "Admin@example.org\n second@example.org;ADMIN@example.org,",
      ),
    ).toEqual(["admin@example.org", "second@example.org"]);
    expect(
      sameAdmins("SECOND@example.org\nadmin@example.org", [
        "admin@example.org",
        "second@example.org",
      ]),
    ).toBe(true);
    expect(sameAdmins("new@example.org", connected.admin_logins)).toBe(false);
  });

  it("opens only with a connected local session and a saved nonempty admin list", () => {
    expect(canOpenAdminAccess(connected, false)).toBe(true);
    expect(canOpenAdminAccess(connected, true)).toBe(false);
    for (const unavailable of [
      { can_manage: false },
      { connected: false },
      { installed: false },
      { admin_logins: [] },
      { enabled: true },
    ])
      expect(canOpenAdminAccess({ ...connected, ...unavailable }, false)).toBe(
        false,
      );
  });

  it("shares only an enabled HTTPS address without embedded credentials", () => {
    expect(
      shareAddress({
        ...connected,
        enabled: true,
        url: "https://falcon.example.test",
      }),
    ).toBe("https://falcon.example.test/");
    expect(
      shareAddress({ ...connected, url: "https://falcon.example.test" }),
    ).toBeNull();
    expect(
      shareAddress({
        ...connected,
        enabled: true,
        verified: false,
        url: "https://falcon.example.test",
      }),
    ).toBeNull();
    expect(
      shareAddress({
        ...connected,
        enabled: true,
        connected: false,
        url: "https://falcon.example.test",
      }),
    ).toBeNull();
    expect(
      shareAddress({
        ...connected,
        enabled: true,
        url: "https://user:secret@falcon.example.test",
      }),
    ).toBeNull();
    expect(
      shareAddress({ ...connected, enabled: true, url: "javascript:alert(1)" }),
    ).toBeNull();
  });

  it("keeps startup settings available when an older backend lacks remote access", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.endsWith("/remote")
            ? Response.json({ detail: "Not Found" }, { status: 404 })
            : Response.json({
                auto_observe: false,
                camera_saved: true,
                state: "disabled",
                message: "Ready",
              }),
        ),
      ),
    );
    const result = await readDeviceAccess();
    expect(result.remote.kind).toBe("unavailable");
    expect(result.appliance).toMatchObject({
      kind: "ready",
      value: { camera_saved: true },
    });
  });

  it("isolates a failed endpoint without hiding successful remote status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.endsWith("/remote")
            ? Response.json(connected)
            : Response.json(
                { detail: "Startup preference unavailable" },
                { status: 503 },
              ),
        ),
      ),
    );
    const result = await readDeviceAccess();
    expect(result.remote).toMatchObject({ kind: "ready", value: connected });
    expect(result.appliance).toEqual({
      kind: "error",
      message: "Startup preference unavailable",
    });
  });
});
