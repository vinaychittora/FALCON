import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import {
  canOpenAdminAccess,
  canEditAdminLogins,
  connectivityCheckLabel,
  parseAdminLogins,
  readDeviceAccess,
  sameAdmins,
  shareAddress,
  type ApplianceState,
  type DeviceResource,
  type RemoteAccessState,
} from "../api/deviceAccess";
import Icon from "./Icon";
import "./device-access.css";

export function ResourceNotice({
  resource,
}: {
  resource: DeviceResource<unknown> | null;
}) {
  if (!resource)
    return (
      <p className="muted" role="status">
        Loading device status…
      </p>
    );
  if (resource.kind === "unavailable")
    return (
      <p className="muted" role="status">
        Available after engine restart.
      </p>
    );
  if (resource.kind === "error")
    return (
      <p className="error" role="alert">
        {resource.message}
      </p>
    );
  return null;
}

export function StartupControls({
  appliance,
  pending,
  onChange,
}: {
  appliance: ApplianceState;
  pending: boolean;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <>
      <label className="device-auto-observe">
        <input
          type="checkbox"
          checked={appliance.auto_observe}
          disabled={
            (!appliance.camera_saved && !appliance.auto_observe) || pending
          }
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>Observe saved camera after startup</span>
      </label>
      <p className="muted">
        Enabling applies at the next engine startup. Turning it off cancels
        pending startup attempts; an active live observation keeps running.
      </p>
      {!appliance.camera_saved && (
        <p className="device-setup">
          Save a camera in Sources → Live camera to enable automatic
          observation.
        </p>
      )}
      {appliance.message && <p className="muted">{appliance.message}</p>}
      <span className="device-state">
        {appliance.state.replaceAll("_", " ")}
      </span>
    </>
  );
}

export default function DeviceAccess() {
  const [remoteResource, setRemoteResource] =
    useState<DeviceResource<RemoteAccessState> | null>(null);
  const [applianceResource, setApplianceResource] =
    useState<DeviceResource<ApplianceState> | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const edited = useRef(false);
  const mutation = useRef(0);
  const remote = remoteResource?.kind === "ready" ? remoteResource.value : null;
  const appliance =
    applianceResource?.kind === "ready" ? applianceResource.value : null;
  const dirty = !!remote && !sameAdmins(draft, remote.admin_logins);
  const address = remote ? shareAddress(remote) : null;

  useEffect(() => {
    let alive = true;
    let polling = false;
    const load = async () => {
      if (polling) return;
      polling = true;
      const revision = mutation.current;
      try {
        const next = await readDeviceAccess();
        if (!alive || revision !== mutation.current) return;
        setRemoteResource(next.remote);
        setApplianceResource(next.appliance);
        if (!edited.current && next.remote.kind === "ready")
          setDraft(next.remote.value.admin_logins.join("\n"));
      } finally {
        polling = false;
      }
    };
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  async function remoteAction(action: "admins" | "open" | "close" | "check") {
    if (pending) return;
    mutation.current += 1;
    setPending(action);
    setError("");
    setNotice("");
    try {
      const next = await api<RemoteAccessState>(`/remote/${action}`, {
        method: action === "admins" ? "PUT" : "POST",
        ...(action === "admins"
          ? { body: JSON.stringify({ admin_logins: parseAdminLogins(draft) }) }
          : {}),
      });
      setRemoteResource({ kind: "ready", value: next });
      if (action === "admins") {
        edited.current = false;
        setDraft(next.admin_logins.join("\n"));
      }
      setNotice(
        action === "admins"
          ? "Approved admin list saved."
          : action === "open"
            ? shareAddress(next)
              ? "Admin access opened."
              : "Admin access requested. The connection is not yet verified."
            : action === "close"
              ? "Admin access closed."
              : "Connection status checked.",
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 404)
        setRemoteResource({ kind: "unavailable" });
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      mutation.current += 1;
      setPending(null);
    }
  }

  async function saveAutoObserve(enabled: boolean) {
    if (pending) return;
    mutation.current += 1;
    setPending("appliance");
    setError("");
    setNotice("");
    try {
      const next = await api<ApplianceState>("/appliance", {
        method: "PUT",
        body: JSON.stringify({ auto_observe: enabled }),
      });
      setApplianceResource({ kind: "ready", value: next });
      setNotice(
        next.auto_observe
          ? "Startup preference saved. It applies at the next engine startup."
          : "Automatic startup observation disabled.",
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 404)
        setApplianceResource({ kind: "unavailable" });
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      mutation.current += 1;
      setPending(null);
    }
  }

  async function copyAddress() {
    if (!address) return;
    try {
      await navigator.clipboard.writeText(address);
      setNotice("Admin address copied.");
    } catch {
      setNotice("Select and copy the admin address below.");
    }
  }

  return (
    <section className="device-access" aria-label="Device access and startup">
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="device-access-grid">
        <section
          className="device-access-section"
          aria-labelledby="remote-access-heading"
        >
          <div className="device-access-heading">
            <Icon name="shield" size={22} />
            <div>
              <h3 id="remote-access-heading">Private admin access</h3>
              <p>Approved Tailscale admins only</p>
            </div>
          </div>
          <ResourceNotice resource={remoteResource} />
          {remote && (
            <>
              <div className="device-access-status">
                <span className={`device-state ${address ? "active" : ""}`}>
                  {remote.enabled
                    ? address
                      ? "Access open"
                      : "Access not verified"
                    : "Access closed"}
                </span>
                <span>
                  {remote.installed
                    ? remote.connected
                      ? "Tailscale connected"
                      : "Tailscale disconnected"
                    : "Tailscale not installed"}
                </span>
              </div>
              {remote.message && <p className="muted">{remote.message}</p>}
              {!remote.installed && (
                <p className="device-setup">
                  Install Tailscale on this device and sign in with your own
                  account.{" "}
                  <a
                    href="https://tailscale.com/docs/install/linux"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Linux setup instructions <Icon name="arrow" size={13} />
                  </a>
                </p>
              )}
              <label className="device-admin-list">
                Approved admin logins
                <textarea
                  rows={3}
                  value={draft}
                  disabled={!canEditAdminLogins(remote) || !!pending}
                  placeholder="admin@example.org"
                  spellCheck={false}
                  autoComplete="off"
                  aria-describedby="admin-list-help"
                  onChange={(event) => {
                    edited.current = true;
                    setDraft(event.target.value);
                  }}
                />
              </label>
              <small id="admin-list-help">
                Tailscale login email addresses, one per line. Save the list
                before opening access.
              </small>
              {remote.enabled && remote.can_manage && (
                <p className="muted">
                  Close admin access before changing the approved admin list.
                </p>
              )}
              {!remote.can_manage && (
                <p className="muted">
                  Change access settings from FALCON on the device itself.
                </p>
              )}
              <div className="device-access-actions">
                <button
                  disabled={!canEditAdminLogins(remote) || !dirty || !!pending}
                  onClick={() => void remoteAction("admins")}
                >
                  {pending === "admins" ? "Saving…" : "Save admins"}
                </button>
                {remote.enabled ? (
                  <button
                    disabled={!remote.can_manage || !!pending}
                    onClick={() => void remoteAction("close")}
                  >
                    {pending === "close" ? "Closing…" : "Close admin access"}
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={!canOpenAdminAccess(remote, dirty) || !!pending}
                    onClick={() => void remoteAction("open")}
                  >
                    {pending === "open" ? "Opening…" : "Open admin access"}
                  </button>
                )}
              </div>
              {address && (
                <div className="device-share-address">
                  <label>
                    Admin address
                    <input
                      readOnly
                      value={address}
                      onFocus={(event) => event.target.select()}
                    />
                  </label>
                  <button className="subtle" onClick={() => void copyAddress()}>
                    <Icon name="link" size={16} /> Copy address
                  </button>
                  <small>
                    Share only with approved admins. Their device must be signed
                    in to Tailscale.
                  </small>
                </div>
              )}
              <div className="device-connectivity">
                <span title="Result of the last check against one external endpoint; this does not test every network route.">
                  Connectivity check · {connectivityCheckLabel(remote.internet)}
                </span>
                <button
                  className="text-button"
                  disabled={!!pending}
                  onClick={() => void remoteAction("check")}
                >
                  <Icon name="refresh" size={15} />
                  {pending === "check" ? "Checking…" : "Check connection"}
                </button>
              </div>
            </>
          )}
        </section>
        <section
          className="device-access-section"
          aria-labelledby="device-startup-heading"
        >
          <div className="device-access-heading">
            <Icon name="power" size={22} />
            <div>
              <h3 id="device-startup-heading">Device startup</h3>
              <p>Saved camera observation</p>
            </div>
          </div>
          <ResourceNotice resource={applianceResource} />
          {appliance && (
            <StartupControls
              appliance={appliance}
              pending={!!pending}
              onChange={(enabled) => void saveAutoObserve(enabled)}
            />
          )}
        </section>
      </div>
    </section>
  );
}
