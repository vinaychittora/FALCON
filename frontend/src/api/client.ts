// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { beginRequest, NetworkError } from "./activity";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // Every request reports to the activity sign (api/activity.ts).
  const end = beginRequest();
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (reason) {
    if (init?.signal?.aborted || (reason instanceof DOMException && reason.name === "AbortError")) {
      end("aborted");
      throw reason;
    }
    // The network failed (FALCON not reachable): the status line says so; pages get a
    // plain sentence instead of the browser's raw "Failed to fetch".
    end("network");
    throw new NetworkError();
  }
  end(response.ok ? "ok" : "answered");
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof error.detail === "string"
        ? error.detail
        : error.detail
          ? JSON.stringify(error.detail)
          : response.statusText,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}
