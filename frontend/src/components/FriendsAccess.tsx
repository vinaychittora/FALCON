// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import Icon from "./Icon";

interface Friend {
  viewer_id: string;
  name: string;
  email: string;
  created_at: string;
  revoked_at: string | null;
}

interface LogEntry {
  at: string;
  action: string;
  viewer_id: string;
  detail: string;
}

interface FriendsState {
  viewers: Friend[];
  log: LogEntry[];
  server: { running: boolean; address: string };
}

const ACTIONS: Record<string, string> = {
  invited: "invited",
  joined: "used the code",
  login: "opened the page",
  clip: "played a clip",
  revoked: "invitation withdrawn",
};

/**
 * Friends (view only): invite by name and email, withdraw, and see who viewed what.
 * The page they open is a separate view server (port 8081) with only the live
 * picture, recognised wildlife and video clips. Shown on the FALCON computer only.
 */
export function FriendsAccess() {
  const [state, setState] = useState<FriendsState | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState<{ name: string; code: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api<FriendsState>("/remote/viewers")
      .then(setState)
      .catch(() => setState(null));
  }
  useEffect(load, []);
  if (!state) return null;

  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const made = await api<{ viewer: Friend; code: string }>(
        "/remote/viewers",
        { method: "POST", body: JSON.stringify({ name, email }) },
      );
      setCode({ name: made.viewer.name, code: made.code });
      setName("");
      setEmail("");
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function withdraw(friend: Friend) {
    if (!window.confirm(`Withdraw ${friend.name}'s invitation? Their page stops working at once.`))
      return;
    await api(`/remote/viewers/${friend.viewer_id}`, { method: "DELETE" });
    load();
  }

  const names = new Map(state.viewers.map((f) => [f.viewer_id, f.name]));
  const active = state.viewers.filter((f) => !f.revoked_at);
  return (
    <section className="device-access-section" aria-labelledby="friends-heading">
      <div className="device-access-heading">
        <Icon name="eye" size={22} />
        <div>
          <h3 id="friends-heading">Friends (view only)</h3>
          <p>
            {state.server.running ? "View page ready on this computer" : "View page not running"}
            {" · "}
            {active.length} invited
          </p>
        </div>
      </div>
      <small>
        Friends see the live picture once a second, recognised animals and their
        video clips. No sound, no settings, nothing hidden or with a person. It is
        not on the internet yet.
      </small>
      {active.length > 0 && (
        <ul className="friends-list">
          {active.map((friend) => (
            <li key={friend.viewer_id}>
              <span>
                <strong>{friend.name}</strong> · {friend.email}
              </span>
              <button className="text-button" onClick={() => void withdraw(friend)}>
                Withdraw
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="friends-invite" onSubmit={(event) => void invite(event)}>
        <input
          aria-label="Friend's name"
          placeholder="Name"
          value={name}
          maxLength={60}
          required
          onChange={(event) => setName(event.target.value)}
        />
        <input
          aria-label="Friend's email"
          type="email"
          placeholder="Email"
          value={email}
          maxLength={200}
          required
          onChange={(event) => setEmail(event.target.value)}
        />
        <button className="subtle" disabled={busy} type="submit">
          Invite
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {code && (
        <p className="friends-code" role="status">
          Invitation code for {code.name}: <strong>{code.code}</strong>. Send it
          to them; it is shown only now.
        </p>
      )}
      {state.log.length > 0 && (
        <details>
          <summary>Who viewed what</summary>
          <ul className="friends-log">
            {state.log.slice(0, 30).map((entry, i) => (
              <li key={i}>
                {new Date(entry.at).toLocaleString()} ·{" "}
                {names.get(entry.viewer_id) ?? entry.viewer_id} ·{" "}
                {ACTIONS[entry.action] ?? entry.action}
                {entry.action === "clip" ? ` (${entry.detail.slice(0, 8)})` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
