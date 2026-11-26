// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState } from "react";
import { getNote, saveNote } from "../api/inaturalist";

/** The fixed note added to every iNaturalist post (editable). */
export default function PostingNote() {
  const [note, setNote] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    getNote()
      .then((value) => {
        setNote(value.note);
        setSaved(value.note);
      })
      .catch(() => setNote(null));
  }, []);
  if (note === null) return null;
  async function save() {
    setBusy(true);
    setError("");
    try {
      const value = await saveNote(note ?? "");
      setNote(value.note);
      setSaved(value.note);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <h3>Posting to iNaturalist</h3>
      <label className="setting">
        <span className="setting-label">Note added to every post</span>
        <textarea
          rows={5}
          maxLength={2000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <p className="muted">
        Each post is obscured on the map, tagged “camera trap, FALCON”, at most
        20 a day. The camera spot is set per node under Sensors.
      </p>
      {error && (
        <p className="banner banner-bad" role="alert">
          {error}
        </p>
      )}
      <button
        disabled={busy || note === saved || !note.trim()}
        onClick={() => void save()}
      >
        Save note
      </button>{" "}
      <a href="#/posting">Open posting</a>
    </div>
  );
}
