import { api, ApiError } from "./client";

export interface RemoteAccessState {
  installed: boolean;
  connected: boolean;
  enabled: boolean;
  verified?: boolean;
  url: string | null;
  hostname: string | null;
  admin_logins: string[];
  message: string;
  internet: "online" | "offline" | "unchecked";
  can_manage: boolean;
}

export interface ApplianceState {
  auto_observe: boolean;
  camera_saved: boolean;
  state: string;
  message: string;
}

export type DeviceResource<T> =
  | { kind: "ready"; value: T }
  | { kind: "unavailable" }
  | { kind: "error"; message: string };

async function readResource<T>(path: string): Promise<DeviceResource<T>> {
  try {
    return { kind: "ready", value: await api<T>(path) };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404)
      return { kind: "unavailable" };
    return {
      kind: "error",
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

export async function readDeviceAccess() {
  const [remote, appliance] = await Promise.all([
    readResource<RemoteAccessState>("/remote"),
    readResource<ApplianceState>("/appliance"),
  ]);
  return { remote, appliance };
}

export const parseAdminLogins = (draft: string) => [
  ...new Set(
    draft
      .split(/[\n,;]+/)
      .map((login) => login.trim().toLocaleLowerCase("en"))
      .filter(Boolean),
  ),
];

export function sameAdmins(draft: string, saved: readonly string[]) {
  const current = parseAdminLogins(draft).sort();
  const previous = parseAdminLogins(saved.join("\n")).sort();
  return (
    current.length === previous.length &&
    current.every((login, index) => login === previous[index])
  );
}

export function canOpenAdminAccess(state: RemoteAccessState, dirty: boolean) {
  return (
    state.can_manage &&
    state.installed &&
    state.connected &&
    !state.enabled &&
    state.admin_logins.length > 0 &&
    !dirty
  );
}

export const canEditAdminLogins = (state: RemoteAccessState) =>
  state.can_manage && !state.enabled;

export const connectivityCheckLabel = (
  internet: RemoteAccessState["internet"],
) =>
  internet === "unchecked"
    ? "Not checked"
    : internet === "online"
      ? "Endpoint responded"
      : "Check failed";

export function shareAddress(state: RemoteAccessState): string | null {
  if (
    !state.enabled ||
    !state.connected ||
    state.verified === false ||
    !state.url
  )
    return null;
  try {
    const url = new URL(state.url);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
