import { afterEach, describe, expect, it, vi } from "vitest";
import {
  endTestSession,
  openTestSession,
  readTestSession,
  rememberTestSession,
  storedTestSession,
  TEST_SESSION_KEY,
} from "./testSessions";

const session = {
  session_id: "test-one",
  status: "active",
  created_at: "2026-10-17T08:00:00Z",
  expires_at: "2026-10-18T08:00:00Z",
  message: "",
};
afterEach(() => vi.unstubAllGlobals());

describe("temporary media sessions", () => {
  it("reuses the saved browser session after a reload", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(session));
    vi.stubGlobal("fetch", fetch);
    expect(await openTestSession("test-one")).toEqual(session);
    expect(fetch).toHaveBeenCalledExactlyOnceWith(
      "/api/test-sessions/test-one/heartbeat",
      expect.objectContaining({ method: "POST" }),
    );
  });
  it.each([404, 410])(
    "creates a fresh session when the previous lease returns %i",
    async (status) => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(Response.json({ detail: "Expired" }, { status }))
        .mockResolvedValueOnce(
          Response.json({ ...session, session_id: "new" }),
        );
      vi.stubGlobal("fetch", fetch);
      expect((await openTestSession("expired")).session_id).toBe("new");
      expect(fetch.mock.calls.map(([url]) => url)).toEqual([
        "/api/test-sessions/expired/heartbeat",
        "/api/test-sessions",
      ]);
    },
  );
  it("does not create another session after a connection or authorization failure", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json({ detail: "Forbidden" }, { status: 403 }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(openTestSession("test-one")).rejects.toThrow("Forbidden");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("waits for cleanup instead of creating new ownership while a session is ending", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(Response.json({ ...session, status: "ending" }));
    vi.stubGlobal("fetch", fetch);
    await expect(openTestSession("test-one")).rejects.toThrow("still closing");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("ends explicitly and polls status without renewing the cleanup lease", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ ...session, status: "ending" }, { status: 202 }),
      )
      .mockResolvedValueOnce(Response.json({ ...session, status: "ended" }));
    vi.stubGlobal("fetch", fetch);
    expect((await endTestSession("test-one")).status).toBe("ending");
    expect((await readTestSession("test-one")).status).toBe("ended");
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/test-sessions/test-one/end",
      "/api/test-sessions/test-one",
    ]);
  });
  it("stores only the session identifier in tab-local storage and clears it on completion", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    });
    rememberTestSession("test-one");
    expect(storedTestSession()).toBe("test-one");
    expect([...values.keys()]).toEqual([TEST_SESSION_KEY]);
    rememberTestSession(null);
    expect(storedTestSession()).toBeNull();
  });
  it("works when sessionStorage is unavailable", () => {
    vi.stubGlobal("sessionStorage", undefined);
    expect(storedTestSession()).toBeNull();
    expect(() => rememberTestSession("test-one")).not.toThrow();
  });
});
