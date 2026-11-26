// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { api } from "./client";

/** iNaturalist posting: only the owner's Post press sends anything. */

export interface InatAccount {
  login: string;
  name: string | null;
  expires_at: string;
}

export interface PostableVisit {
  encounter_id: string;
  name: string | null;
  scientific_name: string | null;
  first_captured_at: string | null;
  duration_ms: number;
  records: number;
  review_status: string;
  thumbnail_event_id: string;
  node: string;
  /** "audio" for a sound visit (its tile is the spectrogram). */
  modality?: "visual" | "audio";
  /** The tile's own address, when it is not the detection thumbnail (the pinned link
   * visit shows its first suggested frame, as the panel does). */
  tile_url?: string;
}

export interface PostedVisit {
  encounter_id: string;
  observation_id: number;
  url: string;
  scientific_name: string | null;
  posted_at: string;
}

export interface VisitList {
  visits: PostableVisit[];
  posted: PostedVisit[];
  posted_today: number;
  daily_cap: number;
}

export interface PostPreview {
  encounter_id: string;
  node: string;
  species: { scientific_name: string | null; common_name: string | null };
  taxon: {
    id: number;
    name: string;
    common_name: string | null;
    rank: string;
  } | null;
  observed_at: string | null;
  duration_ms: number;
  frames: {
    event_id: string;
    captured_at: string | null;
    score: number | null;
    /** The box around the animal (where the crop tool starts); from FALCON 19 Nov on. */
    box?: number[];
  }[];
  /** Present when this FALCON posts whole frames and accepts crops (19 Nov on). */
  max_photos?: number;
  /** "sound": a visit only heard (calls), posted with its sound and no photos. */
  kind: "picture" | "sound";
  sound: VisitSound | null;
  description: string;
  location: "obscured" | null;
  tags: string;
  posted: PostedVisit | null;
  posted_today: number;
  daily_cap: number;
  problems: string[];
  warnings: string[];
}

export const keyStatus = () =>
  api<{ account: InatAccount | null }>("/inaturalist/key");
export const pasteKey = (key: string) =>
  api<{ account: InatAccount }>("/inaturalist/key", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
export const forgetKey = () =>
  api<{ account: null }>("/inaturalist/key", { method: "DELETE" });

/** Sign in on the PC: whether it can be used here, and whether it is set up. */
export interface SignInStatus {
  here: boolean;
  application_id: "set" | "not set" | null;
  notice: string | null;
}
export const AUTHORIZE = "https://www.inaturalist.org/oauth/authorize?";
export const signInStatus = () => api<SignInStatus>("/inaturalist/signin");
export const saveApplicationId = (applicationId: string) =>
  api<{ application_id: "set" }>("/inaturalist/signin/app", {
    method: "PUT",
    body: JSON.stringify({ application_id: applicationId }),
  });
/** Start a sign-in; the answer is iNaturalist's authorize address, or null. */
export async function startSignIn(): Promise<string | null> {
  const response = await fetch("/oauth/start", {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ return_to: "/#/posting" }),
  });
  if (!response.ok) return null;
  const body = (await response.json().catch(() => null)) as { location?: unknown } | null;
  return typeof body?.location === "string" ? body.location : null;
}

export const getNote = () => api<{ note: string }>("/inaturalist/note");
export const saveNote = (note: string) =>
  api<{ note: string }>("/inaturalist/note", {
    method: "PUT",
    body: JSON.stringify({ note }),
  });

export interface Spot {
  latitude: number | null;
  longitude: number | null;
}
export const getSpot = (nodeId: string) =>
  api<Spot>(`/inaturalist/spots/${encodeURIComponent(nodeId)}`);
export const saveSpot = (nodeId: string, text: string) =>
  api<Spot>(`/inaturalist/spots/${encodeURIComponent(nodeId)}`, {
    method: "PUT",
    body: JSON.stringify({ text }),
  });

export const postableVisits = () => api<VisitList>("/inaturalist/visits");
export const postPreview = (encounterId: string) =>
  api<PostPreview>(
    `/inaturalist/visits/${encodeURIComponent(encounterId)}/preview`,
  );
export type Crop = [number, number, number, number];
/** A chosen frame as it would be posted: the whole frame, or the owner's crop of it. */
export const photoUrl = (encounterId: string, eventId: string, crop?: Crop | null) =>
  `/api/inaturalist/visits/${encodeURIComponent(encounterId)}/photos/${encodeURIComponent(eventId)}.jpg${crop ? `?crop=${crop.map((v) => v.toFixed(4)).join(",")}` : ""}`;
/** The visit's sound: seconds in its recording (stay video or sound record). */
export interface VisitSound {
  kind: "video" | "audio";
  evidence_id: string;
  window: [number, number];
  heard: { start: number; end: number; confidence: number }[];
  trim: [number, number];
  include: boolean;
}
export const SOUND_MAX_S = 60;
export const soundUrl = (encounterId: string, start: number, end: number) =>
  `/api/inaturalist/visits/${encodeURIComponent(encounterId)}/sound.wav?start=${start.toFixed(2)}&end=${end.toFixed(2)}`;
export const spectrogramUrl = (encounterId: string) =>
  `/api/inaturalist/visits/${encodeURIComponent(encounterId)}/sound.png`;

/** Keep a trim inside the window and at most SOUND_MAX_S long; `moved` says which end
 * the user moved, so the other one follows. */
export function clampTrim(
  [start, end]: [number, number],
  [w0, w1]: [number, number],
  moved: "start" | "end",
): [number, number] {
  let a = Math.max(w0, Math.min(start, w1 - 0.5));
  let b = Math.min(w1, Math.max(end, w0 + 0.5));
  if (b - a < 0.5) {
    if (moved === "start") b = Math.min(w1, a + 0.5);
    else a = Math.max(w0, b - 0.5);
  }
  if (b - a > SOUND_MAX_S) {
    if (moved === "start") b = a + SOUND_MAX_S;
    else a = b - SOUND_MAX_S;
  }
  return [Math.round(a * 100) / 100, Math.round(b * 100) / 100];
}

/** The sound choice for a visit (include + trim), kept in this browser until posted. */
export function savedTrim(
  encounterId: string,
): { include: boolean; trim: [number, number] } | null {
  try {
    const value = localStorage.getItem(`falcon.posting.sound.${encounterId}`);
    return value ? (JSON.parse(value) as { include: boolean; trim: [number, number] }) : null;
  } catch {
    return null;
  }
}
export function saveTrim(
  encounterId: string,
  value: { include: boolean; trim: [number, number] } | null,
) {
  try {
    const key = `falcon.posting.sound.${encounterId}`;
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch {
    /* storage may be unavailable */
  }
}

export const postVisit = (
  encounterId: string,
  frames: string[],
  sound: { start: number; end: number } | null,
  description: string,
  crops: Record<string, Crop> = {},
) =>
  api<{ observation_id: number; url: string; problems: string[] }>(
    `/inaturalist/visits/${encodeURIComponent(encounterId)}/post`,
    {
      method: "POST",
      // Crops are sent only when there are any, so an older FALCON keeps accepting posts.
      body: JSON.stringify(
        Object.keys(crops).length
          ? { frames, sound, description, crops }
          : { frames, sound, description },
      ),
    },
  );

export const MAX_PHOTOS = 3;

/** Where the crop tool starts: the box around the animal with room around it. */
export function suggestedCrop(box: number[] | null | undefined): Crop {
  if (!box || box.length !== 4) return [0.2, 0.2, 0.8, 0.8];
  const [x1, y1, x2, y2] = box;
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
  const w = Math.min(1, Math.max(0.25, (x2 - x1) * 2));
  const h = Math.min(1, Math.max(0.25, (y2 - y1) * 2));
  const left = Math.min(Math.max(0, cx - w / 2), 1 - w);
  const top = Math.min(Math.max(0, cy - h / 2), 1 - h);
  return [left, top, left + w, top + h];
}

/** Keep a crop inside the frame and at least `min` wide and high. */
export function clampCrop([x1, y1, x2, y2]: Crop, min = 0.08): Crop {
  const w = Math.min(1, Math.max(min, x2 - x1));
  const h = Math.min(1, Math.max(min, y2 - y1));
  const left = Math.min(Math.max(0, x1), 1 - w);
  const top = Math.min(Math.max(0, y1), 1 - h);
  return [left, top, left + w, top + h];
}

/** The owner's crops for a visit, kept in this browser until it is posted. */
export function savedCrops(encounterId: string): Record<string, Crop> {
  try {
    const value = localStorage.getItem(`falcon.posting.crops.${encounterId}`);
    const parsed = value ? (JSON.parse(value) as unknown) : null;
    return parsed && typeof parsed === "object" ? (parsed as Record<string, Crop>) : {};
  } catch {
    return {};
  }
}
export function saveCrops(encounterId: string, crops: Record<string, Crop> | null) {
  try {
    const key = `falcon.posting.crops.${encounterId}`;
    if (crops && Object.keys(crops).length) localStorage.setItem(key, JSON.stringify(crops));
    else localStorage.removeItem(key);
  } catch {
    /* storage may be unavailable */
  }
}

export interface VisitClip {
  evidence_id: string;
  start_s: number;
  end_s: number;
  detections: { event_id: string; t: number }[];
  filmstrip: number[];
  /** Where a frame may be picked, in seconds of the recording; present when FALCON
   * allows frames outside the visit's own part (from 19 Nov, after a restart). */
  pick_range?: [number, number];
}

/** "a Red-vented Bulbul", "an Oriental Magpie-Robin". */
export const withArticle = (name: string) => `${/^[aeiou]/i.test(name) ? "an" : "a"} ${name}`;

/** Whether a moment may be picked: inside the visit, or anywhere in the recording when
 * FALCON allows that. */
export function pickable(clip: VisitClip, seconds: number): { inside: boolean; allowed: boolean } {
  const inside = seconds >= clip.start_s - 0.01 && seconds <= clip.end_s + 0.01;
  const range = clip.pick_range;
  const allowed = inside || (!!range && seconds >= range[0] - 0.01 && seconds <= range[1] + 0.01);
  return { inside, allowed };
}
export const visitClip = (encounterId: string) =>
  api<VisitClip>(`/inaturalist/visits/${encodeURIComponent(encounterId)}/clip`);
export const filmstripUrl = (encounterId: string) =>
  `/api/inaturalist/visits/${encodeURIComponent(encounterId)}/filmstrip.jpg`;
/** A frame picked from the recording, by its time in the recording. */
export const pickedId = (seconds: number) => `t:${seconds.toFixed(3)}`;

/** The photos chosen for a visit, kept in this browser until it is posted. */
export function savedPhotos(encounterId: string): string[] | null {
  try {
    const value = localStorage.getItem(`falcon.posting.photos.${encounterId}`);
    const list = value ? (JSON.parse(value) as unknown) : null;
    return Array.isArray(list) ? list.filter((id) => typeof id === "string") : null;
  } catch {
    return null;
  }
}
export function savePhotos(encounterId: string, ids: string[] | null) {
  try {
    const key = `falcon.posting.photos.${encounterId}`;
    if (ids) localStorage.setItem(key, JSON.stringify(ids));
    else localStorage.removeItem(key);
  } catch {
    /* storage may be unavailable; the choice then lasts until the page closes */
  }
}

/** "25.12, 75.81" or "25.12 75.81" -> [lat, lon], else null. */
export function parseSpot(text: string): [number, number] | null {
  const match = text
    .trim()
    .match(/^(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)$/);
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
}

/** "valid until 14:05 (5 h 12 min left)" */
export function keyExpiry(expiresAt: string, now = new Date()): string {
  const end = new Date(expiresAt);
  const minutes = Math.max(0, Math.round((end.getTime() - now.getTime()) / 60000));
  const left =
    minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`;
  const time = end.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `valid until ${time} (${left} left)`;
}

/** The visit is the encounter id in the hash: "#/posting?visit=..." */
export function visitFromHash(hash: string): string | null {
  const query = hash.split("?")[1];
  return query ? new URLSearchParams(query).get("visit") : null;
}
