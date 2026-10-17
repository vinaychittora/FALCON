import type { Video } from "../types";
import { ApiError } from "./client";

function uploadFailure(response: Response) {
  if (response.status === 413)
    return "Upload rejected (HTTP 413). Check the server or reverse proxy upload limit.";
  if (response.status === 507)
    return "Upload failed: the server has insufficient storage (HTTP 507).";
  return `Upload failed (HTTP ${response.status}${response.statusText ? " " + response.statusText : ""}). Check the source library before retrying.`;
}

/** Stream the browser's file through FormData; do not read it into JS memory. */
export async function uploadMedia(file: File): Promise<Video> {
  const body = new FormData();
  body.append("file", file);
  let response: Response;
  try {
    response = await fetch("/api/videos/upload", { method: "POST", body });
  } catch {
    throw new Error(
      "The upload connection failed. Check that FALCON is reachable and refresh the source library before retrying.",
    );
  }
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      result && typeof result.detail === "string" ? result.detail.trim() : "";
    throw new ApiError(detail || uploadFailure(response), response.status);
  }
  if (!result || typeof result.source_id !== "string" || !result.source_id)
    throw new Error(
      "FALCON did not confirm the saved source. Refresh the source library before retrying the upload.",
    );
  return result as Video;
}
