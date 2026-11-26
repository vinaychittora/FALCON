// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { api, ApiError } from "./client";

export interface TestSession {
  session_id: string;
  status: "active" | "ending" | "ended";
  created_at: string;
  expires_at: string;
  message: string;
}
export const TEST_SESSION_KEY = "falcon.test-session";
export function testSessionHeaders(id: string | null | undefined) {
  return id ? { "X-Falcon-Test-Session": id } : undefined;
}
export function storedTestSession(): string | null {
  try {
    return sessionStorage.getItem(TEST_SESSION_KEY);
  } catch {
    return null;
  }
}
export function rememberTestSession(id: string | null) {
  try {
    if (id) sessionStorage.setItem(TEST_SESSION_KEY, id);
    else sessionStorage.removeItem(TEST_SESSION_KEY);
  } catch {
    /* The server lease still expires if browser storage is unavailable. */
  }
}
export function heartbeatTestSession(id: string) {
  return api<TestSession>(
    `/test-sessions/${encodeURIComponent(id)}/heartbeat`,
    { method: "POST" },
  );
}
export function readTestSession(id: string) {
  return api<TestSession>(`/test-sessions/${encodeURIComponent(id)}`);
}
export function endTestSession(id: string) {
  return api<TestSession>(`/test-sessions/${encodeURIComponent(id)}/end`, {
    method: "POST",
  });
}
export async function openTestSession(id: string | null): Promise<TestSession> {
  if (id) {
    try {
      const current = await heartbeatTestSession(id);
      if (current.status === "active") return current;
      if (current.status === "ending")
        throw new Error(
          "The previous test session is still closing. Wait for cleanup before starting another test.",
        );
    } catch (error) {
      if (!(error instanceof ApiError) || ![404, 410].includes(error.status))
        throw error;
    }
  }
  return api<TestSession>("/test-sessions", { method: "POST" });
}
