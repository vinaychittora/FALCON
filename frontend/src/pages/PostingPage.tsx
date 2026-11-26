// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef, useState } from "react";
import {
  saveCrops,
  savedCrops,
  suggestedCrop,
  type Crop,
  forgetKey,
  keyExpiry,
  keyStatus,
  MAX_PHOTOS,
  pasteKey,
  saveApplicationId,
  signInStatus,
  startSignIn,
  AUTHORIZE,
  type SignInStatus,
  photoUrl,
  savedPhotos,
  savePhotos,
  savedTrim,
  saveTrim,
  postPreview,
  postVisit,
  postableVisits,
  visitClip,
  visitFromHash,
  withArticle,
  type InatAccount,
  type PostableVisit,
  type PostPreview,
  type VisitList,
} from "../api/inaturalist";
import { ApiError } from "../api/client";
import { confirm, startTask } from "../api/activity";
import { thumbnailUrl } from "../api/encounters";
import { formatDuration } from "../api/format";
import { cardWhen } from "../api/reviewList";
import Icon from "../components/Icon";
import Pill from "../ui/Pill";
import { StatusText, useLayerStatus } from "../ui/LayerStatus";

const POSTED_EXTRA = ["Posted to iNaturalist"];
import { LIST_COVERS, postFooter, splitByName, verdictPill } from "./postingView";
import { useBackToClose } from "../hooks/useBackToClose";
import CropTool from "../ui/CropTool";
import "../ui/review-list.css";
import "../ui/posting.css";
import FramePicker, { clockAt } from "../ui/FramePicker";
import Lightbox from "../ui/Lightbox";
import SoundTrim from "../ui/SoundTrim";

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function when(iso: string | null): string {
  if (!iso) return "time unknown";
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The personal key: from signing in on the PC, or pasted; held by FALCON in memory only. */
function KeyCard({
  account,
  onAccount,
}: {
  account: InatAccount | null;
  onAccount: (a: InatAccount | null) => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [signin, setSignin] = useState<SignInStatus | null>(null);
  const [appId, setAppId] = useState("");
  useEffect(() => {
    signInStatus()
      .then(setSignin)
      .catch(() => setSignin(null));
  }, [account]);
  async function submit() {
    setBusy(true);
    setError("");
    try {
      onAccount((await pasteKey(value)).account);
      setValue("");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }
  async function signIn() {
    setBusy(true);
    setError("");
    const location = await startSignIn().catch(() => null);
    // Only iNaturalist's own authorize page is ever followed.
    if (location && location.startsWith(AUTHORIZE)) window.location.assign(location);
    else {
      setError("Sign-in could not start. Press Sign in again.");
      setBusy(false);
    }
  }
  async function saveAppId() {
    setBusy(true);
    setError("");
    try {
      await saveApplicationId(appId);
      setAppId("");
      setSignin(await signInStatus());
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }
  const notice = signin?.notice ? (
    <p className="banner banner-warn" role="status">
      {signin.notice}
    </p>
  ) : null;
  // Signed in, the page's top line says so; only a sign-in notice still shows here.
  if (account) return notice;
  const pasteBox = (
    <>
      <p>
        Open{" "}
        <a
          href="https://www.inaturalist.org/users/api_token"
          target="_blank"
          rel="noopener noreferrer"
        >
          inaturalist.org/users/api_token
        </a>{" "}
        (signed in), copy the key and paste it here. It lasts 24 hours; FALCON keeps it
        in memory only, until it restarts.
      </p>
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="Paste today's key"
          aria-label="iNaturalist key"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button className="primary" disabled={busy || !value.trim()}>
          {busy ? "Checking…" : "Use this key"}
        </button>
      </form>
    </>
  );
  return (
    <section className="card posting-key pp-key">
      {notice}
      <h2 className="pp-key-h">Sign in to iNaturalist to post</h2>
      {signin?.here && signin.application_id === "set" ? (
        <>
          <button
            type="button"
            className="primary pp-signin"
            disabled={busy}
            onClick={() => void signIn()}
          >
            Sign in to iNaturalist
          </button>
          <details className="pp-paste">
            <summary>Use a 24-hour key instead</summary>
            {pasteBox}
          </details>
        </>
      ) : signin?.here ? (
        <>
          <div className="pp-setup">
            <h3>Set up sign-in</h3>
            <p>
              Once only: copy the Application ID of FALCON's application from{" "}
              <a
                href="https://www.inaturalist.org/oauth/applications"
                target="_blank"
                rel="noopener noreferrer"
              >
                inaturalist.org/oauth/applications
              </a>{" "}
              and save it here.
            </p>
            <form
              className="inline-form"
              onSubmit={(event) => {
                event.preventDefault();
                void saveAppId();
              }}
            >
              <input
                autoComplete="off"
                spellCheck={false}
                aria-label="Application ID"
                placeholder="Application ID"
                value={appId}
                onChange={(event) => setAppId(event.target.value)}
              />
              <button className="primary" disabled={busy || !appId.trim()}>
                Save
              </button>
            </form>
          </div>
          {pasteBox}
        </>
      ) : (
        <>
          {signin && (
            <p className="muted">Sign in on the PC at http://localhost:8000</p>
          )}
          {pasteBox}
        </>
      )}
      {error && (
        <p className="banner banner-bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** One visit as it would be posted. Only the Post button sends anything. The panel has
 * three parts (25 Nov, build 4): its top (Back on a phone, the name and the date line),
 * the body that scrolls, and the Post footer that is always in view. */
export function PostPreviewCard({
  encounterId,
  account,
  onPosted,
  row,
  onBack,
}: {
  encounterId: string;
  account: InatAccount | null;
  onPosted: () => void;
  /** The list's row for this visit, for the top while the preview is on its way. */
  row?: PostableVisit;
  /** A phone's full-screen panel: Back to the list. */
  onBack?: () => void;
}) {
  const back = useRef<HTMLButtonElement>(null);
  const hasBack = !!onBack;
  useEffect(() => {
    if (hasBack) back.current?.focus();
  }, [hasBack]);
  const [preview, setPreview] = useState<PostPreview | null>(null);
  const [error, setError] = useState("");
  const [frames, setFramesState] = useState<string[]>([]);
  const setFrames = (update: string[] | ((list: string[]) => string[])) =>
    setFramesState((list) => {
      const next = typeof update === "function" ? update(list) : update;
      savePhotos(encounterId, next);
      return next;
    });
  const [picking, setPicking] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);
  const [crops, setCropsState] = useState<Record<string, Crop>>(() => savedCrops(encounterId));
  const setCrops = (next: Record<string, Crop>) => {
    setCropsState(next);
    saveCrops(encounterId, next);
  };
  const [cropping, setCropping] = useState<string | null>(null);
  // Which chosen pictures have loaded or failed, by "id + crop"; a failed one never shows a
  // broken image, and Post waits until every chosen picture has loaded.
  const [loaded, setLoaded] = useState<Record<string, "ok" | "failed">>({});
  const [retries, setRetries] = useState<Record<string, number>>({});
  // Where this visit lies in its recording, to say why a picked frame cannot be used.
  const [span, setSpan] = useState<[number, number] | null>(null);
  const [outsideAllowed, setOutsideAllowed] = useState(false);
  useEffect(() => {
    let alive = true;
    visitClip(encounterId)
      .then((value) => {
        if (!alive) return;
        setSpan([value.start_s, value.end_s]);
        setOutsideAllowed(!!value.pick_range);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [encounterId]);
  const outsideVisit = (id: string) => {
    if (!span || !id.startsWith("t:")) return false;
    const t = Number(id.slice(2));
    return Number.isFinite(t) && (t < span[0] - 0.01 || t > span[1] + 0.01);
  };
  const [limitHint, setLimitHint] = useState(false);
  const [soundChoice, setSoundChoice] = useState<{
    include: boolean;
    trim: [number, number];
  } | null>(null);
  const chooseSound = (value: { include: boolean; trim: [number, number] }) => {
    setSoundChoice(value);
    saveTrim(encounterId, value);
  };
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ url: string; problems: string[] } | null>(
    null,
  );
  useEffect(() => {
    // The card is keyed by the visit, so a new visit starts with an empty preview.
    let alive = true;
    postPreview(encounterId)
      .then((value) => {
        if (!alive) return;
        setPreview(value);
        setFramesState((savedPhotos(encounterId) ?? []).slice(0, MAX_PHOTOS));
        setDescription(value.description);
        if (value.sound)
          setSoundChoice(
            savedTrim(encounterId) ?? {
              include: value.sound.include,
              trim: value.sound.trim,
            },
          );
      })
      .catch((reason) => alive && setError(errorText(reason)));
    return () => {
      alive = false;
    };
  }, [encounterId]);
  // A FALCON from 19 Nov on posts whole frames and accepts crops; an older one still
  // crops suggested frames itself until it is restarted.
  const canCrop = preview?.max_photos !== undefined;
  function choose(id: string) {
    if (frames.includes(id)) {
      setFrames((list) => list.filter((item) => item !== id));
      setLimitHint(false);
      return;
    }
    if (frames.length >= MAX_PHOTOS) {
      setLimitHint(true);
      return;
    }
    setFrames((list) => [...list, id]);
  }
  async function post() {
    if (busy) return;
    setBusy(true);
    setError("");
    const done = startTask("Posting…");
    try {
      const sound =
        preview?.sound && soundChoice?.include
          ? { start: soundChoice.trim[0], end: soundChoice.trim[1] }
          : null;
      const chosenCrops = Object.fromEntries(
        Object.entries(crops).filter(([id]) => frames.includes(id)),
      );
      const answer = await postVisit(
        encounterId,
        frames,
        sound,
        description,
        canCrop ? chosenCrops : {},
      );
      setResult(answer);
      savePhotos(encounterId, null);
      saveTrim(encounterId, null);
      saveCrops(encounterId, null);
      done();
      confirm("Posted to iNaturalist");
      onPosted();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      done();
      setBusy(false);
    }
  }
  // On a phone the panel covers the app bar: its own top bar carries the status, Posting…
  // and Posted to iNaturalist included (this is where Post is pressed).
  const layerStatus = useLayerStatus(POSTED_EXTRA);
  const shown = onBack ? layerStatus.shown : null;
  const top = (title: string, line: string) => (
    <div className="pp-top-bar">
      {onBack && (
        <button
          ref={back}
          type="button"
          className="rv-icon"
          aria-label="Back to the list"
          onClick={onBack}
        >
          <Icon name="chevronLeft" size={22} />
        </button>
      )}
      <div className="rv-position">
        <span className="first">{title}</span>
        {shown ? (
          <span className="second">
            <StatusText state={shown} />
          </span>
        ) : (
          line && <span className="second">{line}</span>
        )}
      </div>
      {onBack && (
        <span className={`fs-progress${layerStatus.busy ? " on" : ""}`} aria-hidden="true" />
      )}
    </div>
  );
  const rowTitle = row ? row.name || row.scientific_name || "No species name" : "Visit";
  const rowLine = row
    ? `${row.modality === "audio" ? "Sound" : "Visit"} · ${cardWhen(row.first_captured_at)} · ${formatDuration(row.duration_ms)}`
    : "";
  if (!preview)
    return (
      <article className="card posting-preview pp-panel" aria-label={`Post ${rowTitle}`}>
        {top(rowTitle, rowLine)}
        <div className="pp-body">
          {error ? (
            <p className="banner banner-bad">{error}</p>
          ) : (
            <p className="muted">Preparing the preview…</p>
          )}
        </div>
      </article>
    );
  const posted = result ?? preview.posted;
  const name =
    preview.species.common_name || preview.species.scientific_name || "No species name";
  // A post needs a photo or the sound (a sound visit has no photos).
  const hasSound = !!preview.sound && !!soundChoice?.include;
  const pictureKey = (id: string) => `${id}|${(canCrop && crops[id]) ? crops[id].join(",") : ""}|${retries[id] ?? 0}`;
  const failedPictures = frames.filter((id) => loaded[pictureKey(id)] === "failed").length;
  const waitingPictures = frames.filter((id) => !loaded[pictureKey(id)]).length;
  const footer = postFooter({
    problems: posted ? [] : preview.problems,
    account: !!account,
    kind: preview.kind,
    soundOffered: !!preview.sound,
    pictures: frames.length,
    sound: hasSound,
    failed: failedPictures,
    waiting: waitingPictures,
    busy,
  });
  const outsideCount = frames.filter(outsideVisit).length;
  const kindWord = preview.kind === "sound" ? "Sound" : "Visit";
  return (
    <article className="card posting-preview pp-panel" aria-label={`Post ${name}`}>
      {top(
        name,
        `${kindWord} · ${cardWhen(preview.observed_at)} · ${formatDuration(preview.duration_ms)}`,
      )}
      <div className="pp-body">
        <div className="pp-identity">
          {preview.species.scientific_name && (
            <div className="rv-sci">{preview.species.scientific_name}</div>
          )}
          <div className="pp-meta">
            {preview.taxon
              ? `iNaturalist: ${preview.taxon.name} (taxon ${preview.taxon.id}) · `
              : ""}
            {preview.node}
          </div>
        </div>
      {posted ? (
        <p className="muted">This visit is on iNaturalist.</p>
      ) : (
        <>
          {preview.warnings.map((warning) => (
            <p className="banner banner-warn" key={warning}>
              {warning}
            </p>
          ))}
          {preview.kind !== "sound" && preview.problems.length === 0 && (
            <section className="pp-pictures" aria-labelledby={`pp-pictures-${encounterId}`}>
              <h3 className="pp-h" id={`pp-pictures-${encounterId}`}>
                Pictures · choose 1 to {MAX_PHOTOS}
              </h3>
              {!canCrop && (
                <p className="pp-note">
                  Until FALCON's next restart the suggested frames are still cropped by
                  FALCON and Crop is not available.
                </p>
              )}
              <p className="pp-note">
                Suggested frames: tap one to choose it. Nothing is chosen for you.
              </p>
              <div className="pp-strip" role="group" aria-label="Suggested frames to choose from">
                {preview.frames.map((f, index) => {
                  const on = frames.includes(f.event_id);
                  return (
                    <button
                      key={f.event_id}
                      type="button"
                      className="pp-thumb"
                      aria-pressed={on}
                      aria-label={`Frame ${index + 1}, ${when(f.captured_at)}${on ? ", chosen" : ""}`}
                      onClick={() => choose(f.event_id)}
                    >
                      <img src={photoUrl(encounterId, f.event_id)} alt="" loading="lazy" />
                      <span>{when(f.captured_at)}</span>
                      {on && <Icon name="check" size={16} />}
                    </button>
                  );
                })}
                <button type="button" className="pp-pick" onClick={() => setPicking((v) => !v)}>
                  <Icon name="camera" size={16} />
                  {picking ? "Close the recording" : "Pick frames from the recording"}
                </button>
              </div>
              <p className="pp-count" role="status">
                {limitHint
                  ? `At most ${MAX_PHOTOS} pictures`
                  : frames.length
                    ? `${frames.length} of ${MAX_PHOTOS} chosen`
                    : "No picture chosen yet. Tap a suggested frame or pick one from the recording."}
              </p>
              {picking && (
                <FramePicker
                  species={name}
                  encounterId={encounterId}
                  canAdd={frames.length < MAX_PHOTOS}
                  onUse={(id) => choose(id)}
                  onClose={() => setPicking(false)}
                />
              )}
              {frames.length > 0 && (
                <ol className="pp-chosen">
                  {frames.map((id, index) => {
                    const crop = crops[id] ?? null;
                    const frame = preview.frames.find((f) => f.event_id === id);
                    return (
                      <li key={id} className="pp-chosen-item">
                        {loaded[pictureKey(id)] === "failed" ? (
                          <div className="pp-failed" role="alert">
                            <p>
                              This picture could not be loaded.
                              {outsideVisit(id) && span && !outsideAllowed
                                ? ` Its moment (${clockAt(Number(id.slice(2)))}) is outside this visit, which runs from ${clockAt(span[0])} to ${clockAt(span[1])} of the recording. Remove it and pick a frame inside the visit.`
                                : ""}
                            </p>
                            <button
                              type="button"
                              className="pp-btn"
                              onClick={() => setRetries({ ...retries, [id]: (retries[id] ?? 0) + 1 })}
                            >
                              Retry
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="pp-zoom"
                            onClick={() => setZoom(photoUrl(encounterId, id, canCrop ? crop : null))}
                            aria-label={`Picture ${index + 1}: open full size`}
                          >
                            <img
                              key={pictureKey(id)}
                              src={`${photoUrl(encounterId, id, canCrop ? crop : null)}${retries[id] ? `${canCrop && crop ? "&" : "?"}retry=${retries[id]}` : ""}`}
                              alt={`Picture ${index + 1}`}
                              onLoad={() => setLoaded((all) => ({ ...all, [pictureKey(id)]: "ok" }))}
                              onError={() => setLoaded((all) => ({ ...all, [pictureKey(id)]: "failed" }))}
                            />
                          </button>
                        )}
                        <div className="pp-chosen-bar">
                          <span>
                            Picture {index + 1}
                            {frame ? ` · ${when(frame.captured_at)}` : " · picked"}
                            {outsideVisit(id) && outsideAllowed && (
                              <span className="pp-mark pp-mark-outside">Outside the visit</span>
                            )}
                            {crop && canCrop && <span className="pp-mark">Cropped</span>}
                          </span>
                          <span className="pp-chosen-actions">
                            <button
                              type="button"
                              className="pp-btn"
                              disabled={!canCrop}
                              title={canCrop ? undefined : "Available after FALCON's next restart"}
                              onClick={() => setCropping(id)}
                            >
                              Crop
                            </button>
                            {crop && canCrop && (
                              <button
                                type="button"
                                className="pp-btn"
                                onClick={() => {
                                  const next = { ...crops };
                                  delete next[id];
                                  setCrops(next);
                                }}
                              >
                                Reset
                              </button>
                            )}
                            <button
                              type="button"
                              className="pp-btn"
                              onClick={() => choose(id)}
                            >
                              Remove
                            </button>
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
              {cropping && (
                <CropTool
                  src={photoUrl(encounterId, cropping)}
                  start={crops[cropping] ?? suggestedCrop(preview.frames.find((f) => f.event_id === cropping)?.box)}
                  onUse={(crop) => {
                    setCrops({ ...crops, [cropping]: crop });
                    setCropping(null);
                  }}
                  onWhole={() => {
                    const next = { ...crops };
                    delete next[cropping];
                    setCrops(next);
                    setCropping(null);
                  }}
                  onCancel={() => setCropping(null)}
                />
              )}
              {zoom && (
                <Lightbox src={zoom} alt="Picture at full size" onClose={() => setZoom(null)} />
              )}
            </section>
          )}
          {preview.sound && soundChoice && preview.problems.length === 0 && (
            <section className="pp-section">
              <h3 className="pp-h">Sound</h3>
              <SoundTrim
                encounterId={encounterId}
                sound={preview.sound}
                include={soundChoice.include}
                trim={soundChoice.trim}
                onInclude={(include) => chooseSound({ ...soundChoice, include })}
                onTrim={(trim) => chooseSound({ ...soundChoice, trim })}
              />
            </section>
          )}
          {preview.problems.length === 0 && (
            <>
              <section className="pp-section">
                <label className="posting-description">
                  <span className="pp-h">Description</span>
                  <textarea
                    rows={8}
                    value={description}
                    maxLength={5000}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
              </section>
              <section className="pp-section">
                <h3 className="pp-h">Details</h3>
                <p className="pp-meta">
                  Location:{" "}
                  {preview.location === "obscured"
                    ? "the node's camera spot, shown publicly only as an obscured area"
                    : "not set"}{" "}
                  · Tags: {preview.tags} · Today {preview.posted_today} of{" "}
                  {preview.daily_cap} posts
                </p>
              </section>
            </>
          )}
        </>
      )}
      </div>
      <footer className="pp-foot">
        {posted ? (
          <p className="pp-foot-line pp-posted" role="status">
            <Icon name="check" size={16} /> Posted.{" "}
            <a href={posted.url} target="_blank" rel="noopener noreferrer">
              Open on iNaturalist <Icon name="external" size={13} />
            </a>
            {result?.problems.length ? ` ${result.problems.join(" ")}` : ""}
          </p>
        ) : (
          <>
            {error && (
              <p className="banner banner-bad" role="alert">
                {error}
              </p>
            )}
            {outsideAllowed && outsideCount > 0 && (
              <p className="pp-outside-line" role="status">
                {outsideCount === 1
                  ? `1 picture is from outside this visit. Check that it shows ${withArticle(name)}.`
                  : `${outsideCount} pictures are from outside this visit. Check that they show ${withArticle(name)}.`}
              </p>
            )}
            <p
              className={`pp-foot-line${footer.reason ? " pp-reason" : ""}${footer.ready ? " pp-ready" : ""}`}
              role="status"
            >
              {footer.text}
            </p>
            {!footer.reason && (
              <button
                type="button"
                className="primary pp-post"
                disabled={!footer.ready || busy}
                aria-busy={busy || undefined}
                onClick={() => void post()}
              >
                <Icon name="upload" size={15} /> {busy ? "Posting…" : "Post to iNaturalist"}
              </button>
            )}
          </>
        )}
      </footer>
    </article>
  );
}

/** Small screens show the list, then the chosen visit as a full-screen step. */
function useNarrow(): boolean {
  const query = "(max-width: 899px)";
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches,
  );
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (!list) return;
    const update = () => setNarrow(list.matches);
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, []);
  return narrow;
}

/** The chosen visit as a full-screen step on a phone; the panel inside has Back. */
function PanelLayer({ title, onBack, children }: { title: string; onBack: () => void; children: React.ReactNode }) {
  useBackToClose(onBack);
  return (
    <div className="pp-layer" role="dialog" aria-modal="true" aria-label={title}>
      {children}
    </div>
  );
}

/** One visit of the list in Review's card look; no tick box and no decisions here. */
function PostRow({
  visit,
  current,
  tabbable,
  onOpen,
  setRef,
}: {
  visit: PostableVisit;
  current: boolean;
  tabbable: boolean;
  onOpen: () => void;
  setRef: (element: HTMLButtonElement | null) => void;
}) {
  const [failed, setFailed] = useState(false);
  const sound = visit.modality === "audio";
  const name = visit.name || visit.scientific_name || "No species name";
  const pill = verdictPill(visit.review_status);
  const tile =
    visit.tile_url !== undefined
      ? visit.tile_url
      : visit.thumbnail_event_id
        ? thumbnailUrl(visit.thumbnail_event_id)
        : "";
  return (
    <li className={`rl-card pp-card${current ? " picked" : ""}`}>
      <button
        type="button"
        ref={setRef}
        className="c-open"
        aria-current={current ? "true" : undefined}
        tabIndex={tabbable ? 0 : -1}
        onClick={onOpen}
      >
        {tile && !failed ? (
          <img
            src={tile}
            alt=""
            loading="lazy"
            onError={() => setFailed(true)}
          />
        ) : (
          <span className="c-noimg" aria-hidden="true">
            <Icon name={sound ? "sound" : "eye"} size={26} />
          </span>
        )}
        <span className="c-t">
          <span className="c-nm">{name}</span>
          {visit.name && visit.scientific_name && (
            <span className="c-sci">{visit.scientific_name}</span>
          )}
          <span className="c-l">
            {pill && <Pill tone="good">{pill}</Pill>}
            <span className="wh">
              <span className="nw">{sound ? "Sound" : "Visit"} ·</span>{" "}
              <span className="nw">{cardWhen(visit.first_captured_at)} ·</span>{" "}
              <span className="nw">{formatDuration(visit.duration_ms)}</span>
            </span>
          </span>
        </span>
        <Icon name="chevron" size={18} />
      </button>
    </li>
  );
}

/** The record selected when the list arrives: the one already chosen (from Review or by a
 * tap) whether or not it is listed. Only a page opened without a visit in its address
 * starts on the first listed one (25 Nov 2026: a linked visit switched to the newest record). */
export function selectionOnLoad(
  current: string | null,
  ids: readonly string[],
  linked: string | null,
): string | null {
  if (linked) return current;
  return current ?? ids[0] ?? null;
}

/** Why the visit in the address cannot be posted, in one plain sentence, or "". */
export function linkProblem(preview: Pick<PostPreview, "problems" | "posted">): string {
  if (preview.posted || preview.problems.includes("Already posted."))
    return "This visit is already on iNaturalist.";
  if (preview.problems.includes("Only visits you confirmed or corrected can be posted."))
    return "This visit cannot be posted: confirm or correct it on Review first.";
  return "";
}

export const LINK_NOT_FOUND =
  "This visit cannot be posted: it was not found. It may have been discarded or cleared.";

/** The visit in the address as a row of the list, when it is older than the listed ones. */
export function rowFromPreview(preview: PostPreview): PostableVisit {
  return {
    encounter_id: preview.encounter_id,
    name: preview.species.common_name,
    scientific_name: preview.species.scientific_name,
    first_captured_at: preview.observed_at,
    duration_ms: preview.duration_ms,
    records: preview.frames.length,
    review_status: "",
    thumbnail_event_id: preview.frames[0]?.event_id ?? "",
    node: preview.node,
    modality: preview.kind === "sound" ? "audio" : "visual",
    // The first suggested frame at the same address as the panel's (never the detection
    // thumbnail, which came out black for an older visit); no frame: the neutral tile.
    tile_url: preview.frames[0]
      ? photoUrl(preview.encounter_id, preview.frames[0].event_id)
      : "",
  };
}

export default function PostingPage() {
  const [account, setAccount] = useState<InatAccount | null>(null);
  const [accountKnown, setAccountKnown] = useState(false);
  const [list, setList] = useState<VisitList | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(() =>
    typeof window === "undefined" ? null : visitFromHash(window.location.hash),
  );
  const [panelOpen, setPanelOpen] = useState(() =>
    typeof window !== "undefined" && !!visitFromHash(window.location.hash),
  );
  const narrow = useNarrow();
  const rows = useRef(new Map<string, HTMLButtonElement>());
  // The visit named in the address (from a record view): it stays selected until another is picked
  // another; if it is older than the listed ones it leads the list.
  const [linked] = useState(() =>
    typeof window === "undefined" ? null : visitFromHash(window.location.hash),
  );
  const [linkRow, setLinkRow] = useState<PostableVisit | null>(null);
  const [linkNote, setLinkNote] = useState("");
  useEffect(() => {
    if (!linked) return;
    let alive = true;
    postPreview(linked)
      .then((value) => {
        if (!alive) return;
        const why = linkProblem(value);
        if (why) {
          setLinkNote(why);
          setSelected((current) => (current === linked ? null : current));
          return;
        }
        setLinkRow(rowFromPreview(value));
      })
      .catch((reason) => {
        if (!alive) return;
        if (reason instanceof ApiError && (reason.status === 404 || reason.status === 422)) {
          setLinkNote(LINK_NOT_FOUND);
          setSelected((current) => (current === linked ? null : current));
        } else setError(errorText(reason));
      });
    return () => {
      alive = false;
    };
  }, [linked]);
  useEffect(() => {
    keyStatus()
      .then((value) => setAccount(value.account))
      .catch(() => setAccount(null))
      .finally(() => setAccountKnown(true));
  }, []);
  useEffect(() => {
    postableVisits()
      .then((value) => {
        setList(value);
        const ids = splitByName(value.visits).named.map((visit) => visit.encounter_id);
        // The linked record stays selected, also when it is older than the listed
        // ones (25 Nov 2026: a linked visit switched to the newest record). Only an empty
        // selection takes the first of the list.
        setSelected((current) => selectionOnLoad(current, ids, linked));
      })
      .catch((reason) => setError(errorText(reason)));
  }, [linked]);
  const listed = list?.visits ?? [];
  const visits =
    linkRow &&
    !listed.some((visit) => visit.encounter_id === linkRow.encounter_id) &&
    !list?.posted.some((item) => item.encounter_id === linkRow.encounter_id)
      ? [linkRow, ...listed]
      : listed;
  // Visits without a species name cannot be posted: they wait behind their own expander.
  const { named, unnamed } = splitByName(visits);
  const [unnamedOpen, setUnnamedOpen] = useState(false);
  const ordered = unnamedOpen ? [...named, ...unnamed] : named;
  function select(id: string, focus = false) {
    setSelected(id);
    if (narrow) setPanelOpen(true);
    if (focus) window.setTimeout(() => rows.current.get(id)?.focus(), 0);
  }
  function onListKey(event: React.KeyboardEvent<HTMLElement>) {
    if (!ordered.length) return;
    const index = Math.max(0, ordered.findIndex((visit) => visit.encounter_id === selected));
    const next =
      event.key === "ArrowDown" ? Math.min(ordered.length - 1, index + 1)
      : event.key === "ArrowUp" ? Math.max(0, index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? ordered.length - 1
      : null;
    if (next === null) return;
    event.preventDefault();
    setSelected(ordered[next].encounter_id);
    rows.current.get(ordered[next].encounter_id)?.focus();
  }
  const selectedVisit = visits.find((visit) => visit.encounter_id === selected);
  const closePanel = () => {
    setPanelOpen(false);
    if (selected) window.setTimeout(() => rows.current.get(selected)?.focus(), 0);
  };
  const panel = selected ? (
    <PostPreviewCard
      key={selected}
      encounterId={selected}
      account={account}
      row={selectedVisit}
      onBack={narrow ? closePanel : undefined}
      onPosted={() => {
        // The posted record leaves the list; it stays selected (its panel shows "Posted"),
        // and the next one is picked by hand. Nothing is selected or posted by itself.
        postableVisits()
          .then(setList)
          .catch((reason) => setError(errorText(reason)));
      }}
    />
  ) : (
    <p className="muted posting-empty">{linkNote || "Select a visit to see what would be posted."}</p>
  );
  const rowFor = (visit: PostableVisit, first: boolean) => (
    <PostRow
      key={visit.encounter_id}
      visit={visit}
      current={visit.encounter_id === selected && !narrow}
      tabbable={visit.encounter_id === selected || (!selected && first)}
      onOpen={() => select(visit.encounter_id)}
      setRef={(element) => {
        if (element) rows.current.set(visit.encounter_id, element);
        else rows.current.delete(visit.encounter_id);
      }}
    />
  );
  return (
    <div className="page posting-page">
      <div className="pp-top">
        {list && (
          <p className="pp-top-line">
            <b>{list.posted_today}</b> of {list.daily_cap} posted today
          </p>
        )}
        {account && (
          <p className="pp-top-line" title={keyExpiry(account.expires_at)}>
            <Icon name="check" size={15} />
            <span>
              Signed in to iNaturalist as <strong>{account.name || account.login}</strong>
            </span>
          </p>
        )}
      </div>
      {accountKnown && <KeyCard account={account} onAccount={setAccount} />}
      {error && <p className="banner banner-bad">{error}</p>}
      <div className="posting-layout pp-layout">
        <section className="pp-list" aria-labelledby="pp-list-h" onKeyDown={onListKey}>
          <h2 id="pp-list-h" className="pp-list-h">
            Not posted yet
          </h2>
          {narrow && linkNote && !selected && <p className="pp-note pp-link-note">{linkNote}</p>}
          {list && named.length === 0 && (
            <p className="muted">
              No confirmed or corrected visits waiting. Confirm visits on the
              Review page first.
            </p>
          )}
          <ul className="rl-cards pp-cards" aria-labelledby="pp-list-h">
            {named.map((visit, index) => rowFor(visit, index === 0))}
          </ul>
          {unnamed.length > 0 && (
            <details
              className="rl-about pp-unnamed"
              onToggle={(event) => setUnnamedOpen(event.currentTarget.open)}
            >
              <summary>
                <span>
                  <b>{unnamed.length}</b> visit{unnamed.length === 1 ? "" : "s"} without a
                  species name
                </span>
              </summary>
              <p>These cannot be posted. Correct each one to a species on Review first.</p>
              <ul className="rl-cards pp-cards" aria-label="No species name">
                {unnamed.map((visit) => rowFor(visit, false))}
              </ul>
            </details>
          )}
          {list && <p className="pp-note pp-covers">{LIST_COVERS}</p>}
          {!!list?.posted.length && (
            <details className="rl-about">
              <summary>
                <span>
                  Posted lately · <b>{list.posted.length}</b>
                </span>
              </summary>
              <ul className="posting-done">
                {list.posted.map((item) => (
                  <li key={item.encounter_id}>
                    <a href={item.url} target="_blank" rel="noopener noreferrer">
                      {item.scientific_name} · {when(item.posted_at)}{" "}
                      <Icon name="external" size={12} />
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <details className="rl-about">
            <summary>
              <span>About this page</span>
            </summary>
            <p>
              Visits you confirmed or corrected, newest first. Select one to see exactly
              what would be posted; nothing is sent until you press Post. One press posts
              one visit, with the pictures you chose (1 to {MAX_PHOTOS}) and, if you
              include it, the sound. At most {list?.daily_cap ?? 20} posts a day.
            </p>
            {account && (
              <p>
                Your key is {keyExpiry(account.expires_at)}.{" "}
                <button
                  type="button"
                  className="text-button pp-forget"
                  onClick={() => void forgetKey().then(() => setAccount(null))}
                >
                  Forget the key
                </button>
              </p>
            )}
          </details>
        </section>
        {narrow ? (
          panelOpen && selected ? (
            <PanelLayer
              title={selectedVisit?.name || selectedVisit?.scientific_name || "Visit"}
              onBack={closePanel}
            >
              {panel}
            </PanelLayer>
          ) : null
        ) : (
          <div className="posting-previews pp-side">{panel}</div>
        )}
      </div>
    </div>
  );
}
