import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api/client";
import {
  endTestSession,
  heartbeatTestSession,
  openTestSession,
  readTestSession,
  rememberTestSession,
  storedTestSession,
  testSessionHeaders,
  type TestSession,
} from "./api/testSessions";
import { initialResourceLoader } from "./api/initialLoad";
import { uploadMedia } from "./api/upload";
import UploadStatus from "./components/UploadStatus";
import { indexTaxonNames } from "./api/names";
import { TaxonNamesContext } from "./components/TaxonNames";
import {
  canResumeAnalysis,
  controlAnalysis,
  isActiveAnalysis,
  supportsAnalysisControl,
} from "./api/analysis";
import { observationOverlays } from "./api/overlays";
import { currentEvents, formatTime } from "./api/timeline";
import { useAnalysis } from "./hooks/useAnalysis";
import { useActiveAnalysis } from "./hooks/useActiveAnalysis";
import type { Config, Detection, Job, Models, Video } from "./types";
import AudioPlayer from "./components/AudioPlayer";
import SourceTechnical from "./components/SourceTechnical";
import AnalysisActions from "./components/AnalysisActions";
import AnalysisDetails, { type SystemTab } from "./components/AnalysisDetails";
import RunDetails from "./components/RunDetails";
import ClimatePanel from "./components/ClimatePanel";
import Icon, { FalconMark } from "./components/Icon";
import ImagePlayer from "./components/ImagePlayer";
import Inspector from "./components/Inspector";
import InstallApp from "./components/InstallApp";
import DisplayPreferences from "./components/DisplayPreferences";
import WorkspaceTabs, { type WorkspaceTab } from "./components/WorkspaceTabs";
import LiveCamera from "./components/LiveCamera";
import ObservationHistory from "./components/ObservationHistory";
import ObservationArchive from "./components/ObservationArchive";
import SensorHistory from "./components/SensorHistory";
import SourceLibrary from "./components/SourceLibrary";
import ObservationRail from "./components/ObservationRail";
import Timeline from "./components/Timeline";
import VideoPlayer from "./components/VideoPlayer";
import Taxa, { type TaxaCache } from "./pages/Taxa";

function sourceName(filename: string) {
  return filename
    .replace(/\.[^.]+$/, "")
    .replaceAll(/[-_]+/g, " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

export default function App() {
  const [videos, setVideos] = useState<Video[]>([]),
    [selected, setSelected] = useState(""),
    [time, setTime] = useState(0),
    [runId, setRunId] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [show, setShow] = useState(true);
  const [resourceErrors, setResourceErrors] = useState({
    library: "",
    config: "",
    system: "",
  });
  const resourceError = Object.values(resourceErrors).filter(Boolean).join(" ");
  const [config, setConfig] = useState<Config | null>(null),
    [models, setModels] = useState<Models | null>(null),
    [taxa, setTaxa] = useState<TaxaCache | null>(null);
  const [page, setPage] = useState<
      "watch" | "observations" | "taxa" | "system"
    >("watch"),
    [sourceMode, setSourceMode] = useState<"library" | "live">("live"),
    [inspect, setInspect] = useState<Detection | null>(null);
  const [inspectPlayback, setInspectPlayback] = useState(false);
  const [systemTab, setSystemTab] = useState<SystemTab>("live");
  function openInspector(event: Detection, play = false) {
    setInspectPlayback(play);
    setInspect(event);
  }
  const [seek, setSeek] = useState({ ms: 0, nonce: 0 }),
    [starting, setStarting] = useState(false),
    [uploading, setUploading] = useState(false),
    [liveBusy, setLiveBusy] = useState(false),
    [archiveRevision, setArchiveRevision] = useState(0);
  const [uploadFilename, setUploadFilename] = useState("");
  const [uploadAllowed, setUploadAllowed] = useState<boolean | null>(null);
  const [testSession, setTestSession] = useState<TestSession | null>(null);
  const [endingTests, setEndingTests] = useState(false);
  const testSessionId = useRef<string | null>(null);
  const testSessionEnding = useRef(false);
  const openingTests = useRef<Promise<TestSession> | null>(null);
  const [pendingControl, setPendingControl] = useState<
    "pause" | "resume" | null
  >(null);
  const selectionEpoch = useRef(0);
  const activeAnalysis = useActiveAnalysis();
  const video = videos.find((item) => item.source_id === selected);
  const {
    job,
    jobs,
    events,
    error: analysisError,
    refresh,
  } = useAnalysis(selected, runId);
  const busy = starting || pendingControl === "resume" || isActiveAnalysis(job);
  const fileBusy =
    endingTests ||
    starting ||
    !!pendingControl ||
    activeAnalysis.loading ||
    !!activeAnalysis.error ||
    isActiveAnalysis(activeAnalysis.job) ||
    jobs.some(isActiveAnalysis);
  const resumable = canResumeAnalysis(job, selected);
  const loadVideos = useCallback(async () => {
    try {
      const catalog = await api<{ videos: Video[]; errors: string[] }>(
        "/videos",
      );
      setVideos(catalog.videos);
      setSelected((previous) =>
        catalog.videos.some((item) => item.source_id === previous)
          ? previous
          : (catalog.videos[0]?.source_id ?? ""),
      );
      setResourceErrors((previous) => ({
        ...previous,
        library: catalog.errors.join("; "),
      }));
      return true;
    } catch (e) {
      setResourceErrors((previous) => ({
        ...previous,
        library: e instanceof Error ? e.message : String(e),
      }));
      return false;
    }
  }, []);
  const refreshActiveAnalysis = activeAnalysis.refresh;
  const finishTestSession = useCallback(() => {
    testSessionId.current = null;
    testSessionEnding.current = false;
    rememberTestSession(null);
    setTestSession(null);
    setEndingTests(false);
    setRunId("");
    setInspect((current) => (current?.source_kind === "live" ? current : null));
    void loadVideos();
    refresh();
    refreshActiveAnalysis();
    setNotice(
      "Test session ended. Temporary uploads and results were cleared; previously saved sources are retained.",
    );
  }, [loadVideos, refresh, refreshActiveAnalysis]);
  useEffect(() => {
    let active = true;
    const id = storedTestSession();
    testSessionId.current = id;
    if (id)
      void heartbeatTestSession(id)
        .then((session) => {
          if (
            !active ||
            testSessionId.current !== id ||
            testSessionEnding.current
          )
            return;
          if (session.status === "ended") finishTestSession();
          else {
            testSessionEnding.current = session.status === "ending";
            setTestSession(session);
            setEndingTests(session.status === "ending");
          }
        })
        .catch((error) => {
          if (
            !active ||
            testSessionId.current !== id ||
            testSessionEnding.current
          )
            return;
          if (error instanceof ApiError && [404, 410].includes(error.status))
            finishTestSession();
          else
            setError(
              "The temporary test session could not be restored. Check the connection before starting another test.",
            );
        });
    return () => {
      active = false;
    };
  }, [finishTestSession]);
  const currentTestId = testSession?.session_id;
  const currentTestStatus = testSession?.status;
  useEffect(() => {
    if (!currentTestId) return;
    let active = true;
    const tick = async () => {
      try {
        const next =
          currentTestStatus === "ending"
            ? await readTestSession(currentTestId)
            : await heartbeatTestSession(currentTestId);
        if (
          !active ||
          testSessionId.current !== currentTestId ||
          (testSessionEnding.current && currentTestStatus !== "ending")
        )
          return;
        if (next.status === "ended") finishTestSession();
        else {
          testSessionEnding.current = next.status === "ending";
          setTestSession(next);
          setEndingTests(next.status === "ending");
        }
      } catch (error) {
        if (
          !active ||
          testSessionId.current !== currentTestId ||
          (testSessionEnding.current && currentTestStatus !== "ending")
        )
          return;
        if (error instanceof ApiError && [404, 410].includes(error.status))
          finishTestSession();
        else
          setError(
            "The test session connection was interrupted. Temporary data is retained until cleanup can complete.",
          );
      }
    };
    const timer = setInterval(
      () => void tick(),
      currentTestStatus === "ending" ? 1500 : 60000,
    );
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [currentTestId, currentTestStatus, finishTestSession]);
  async function ensureTestSession() {
    if (testSessionEnding.current)
      throw new Error(
        "Wait for the test session to finish closing before starting another test.",
      );
    if (!openingTests.current)
      openingTests.current = openTestSession(testSessionId.current)
        .then((session) => {
          testSessionId.current = session.session_id;
          rememberTestSession(session.session_id);
          setTestSession(session);
          return session;
        })
        .finally(() => {
          openingTests.current = null;
        });
    return openingTests.current;
  }
  async function endTests() {
    const id = testSessionId.current;
    if (
      !id ||
      testSessionEnding.current ||
      uploading ||
      starting ||
      pendingControl
    )
      return;
    testSessionEnding.current = true;
    setEndingTests(true);
    try {
      const session = await endTestSession(id);
      if (session.status === "ended") finishTestSession();
      else setTestSession(session);
    } catch (error) {
      // The request may have reached the server. Reconcile its status before enabling tests.
      setTestSession((current) =>
        current ? { ...current, status: "ending" } : current,
      );
      setError(
        error instanceof Error
          ? error.message
          : "The test session could not be ended.",
      );
    }
  }
  useEffect(() => {
    let alive = true;
    const initialLoad = initialResourceLoader([
      loadVideos,
      async () => {
        try {
          const value = await api<Config>("/config");
          if (alive) {
            // Never replace a configuration the user has already begun editing.
            setConfig((current) => current ?? value);
            setResourceErrors((previous) => ({ ...previous, config: "" }));
          }
          return true;
        } catch (e) {
          if (alive)
            setResourceErrors((previous) => ({
              ...previous,
              config: e instanceof Error ? e.message : String(e),
            }));
          return false;
        }
      },
      async () => {
        try {
          const value = await api<{ device: string; upload_allowed?: boolean }>(
            "/system",
          );
          if (alive) {
            setUploadAllowed(value.upload_allowed !== false);
            setResourceErrors((previous) => ({ ...previous, system: "" }));
          }
          return true;
        } catch (e) {
          if (alive)
            setResourceErrors((previous) => ({
              ...previous,
              system: e instanceof Error ? e.message : String(e),
            }));
          return false;
        }
      },
    ]);
    const retryInitial = () => {
      void initialLoad();
    };
    const load = () => {
      api<Models>("/models")
        .then((value) => {
          if (alive) setModels(value);
        })
        .catch(() => {});
      api<TaxaCache>("/taxa")
        .then((value) => {
          if (alive) setTaxa(value);
        })
        .catch(() => {});
    };
    retryInitial();
    load();
    const timer = setInterval(() => {
      retryInitial();
      load();
    }, 5000);
    window.addEventListener("focus", retryInitial);
    window.addEventListener("online", retryInitial);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener("focus", retryInitial);
      window.removeEventListener("online", retryInitial);
    };
  }, [loadVideos]);
  const current = useMemo(() => currentEvents(events, time), [events, time]);
  const taxonNames = useMemo(() => indexTaxonNames(taxa?.taxa ?? []), [taxa]);
  const boxesAt = useCallback(
    (ms: number) =>
      observationOverlays(currentEvents(events, ms).visual, taxonNames),
    [events, taxonNames],
  );
  const doSeek = useCallback((ms: number) => {
    setSeek((previous) => ({ ms, nonce: previous.nonce + 1 }));
    setTime(ms);
  }, []);
  function selectSource(id: string) {
    selectionEpoch.current += 1;
    setSelected(id);
    setSeek((previous) => ({ ms: 0, nonce: previous.nonce + 1 }));
    setRunId("");
    setTime(0);
    setInspect(null);
  }
  function openSettings() {
    setSystemTab("settings");
    setPage("system");
  }
  function openSource(id: string, event?: Detection) {
    selectSource(id);
    setPage("watch");
    setSourceMode("library");
    if (event) {
      setRunId(event.job_id);
      doSeek(event.modality === "visual" ? event.timestamp_ms : event.start_ms);
    }
  }
  async function start() {
    if (!video || !config || fileBusy || liveBusy) return;
    const epoch = selectionEpoch.current;
    setError("");
    setStarting(true);
    try {
      const session = await ensureTestSession();
      const started = await api<Job>(`/videos/${video.source_id}/analyze`, {
        method: "POST",
        headers: testSessionHeaders(session.session_id),
        body: JSON.stringify(
          video.media_kind === "audio"
            ? { ...config, audio_enabled: true }
            : config,
        ),
      });
      if (selectionEpoch.current === epoch) setRunId(started.job_id);
      refresh();
      activeAnalysis.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }
  async function changeAnalysis(action: "pause" | "resume") {
    if (!job || job.source_id !== selected || pendingControl) return;
    if (action === "resume" && (fileBusy || liveBusy)) return;
    setError("");
    setPendingControl(action);
    try {
      await controlAnalysis(action, job, selected, testSessionId.current);
      refresh();
      activeAnalysis.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPendingControl(null);
    }
  }
  function openActiveAnalysis() {
    const active = activeAnalysis.job;
    if (!active) return;
    selectSource(active.source_id);
    setRunId(active.job_id);
    setSourceMode("library");
    setPage("watch");
  }
  async function save() {
    try {
      setConfig(
        await api<Config>("/config", {
          method: "PUT",
          body: JSON.stringify(config),
        }),
      );
      setNotice("System configuration saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function upload(file: File) {
    if (uploadAllowed === false) {
      setError("Upload media from the device itself.");
      return;
    }
    setUploading(true);
    setUploadFilename(file.name);
    setError("");
    try {
      const session = await ensureTestSession();
      const media = await uploadMedia(file, session.session_id);
      await loadVideos();
      selectSource(media.source_id);
      setSourceMode("library");
      setPage("watch");
      setNotice("Media added to this temporary test session.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      setUploadFilename("");
    }
  }
  const workspaceTab: WorkspaceTab =
    page === "watch" ? (sourceMode === "live" ? "monitor" : "media") : page;
  function selectWorkspace(tab: WorkspaceTab) {
    if (tab === "monitor" || tab === "media") {
      setPage("watch");
      setSourceMode(tab === "monitor" ? "live" : "library");
    } else {
      if (tab === "system") setSystemTab("live");
      setPage(tab);
    }
  }
  return (
    <TaxonNamesContext.Provider value={taxonNames}>
      <a className="skip-link" href="#workspace-panel">
        Skip to workspace
      </a>
      <header className="app-header">
        <button
          className="brand"
          aria-label="FALCON home"
          onClick={() => {
            setPage("watch");
            setSourceMode("live");
          }}
        >
          <FalconMark />
          <span>
            <strong>FALCON</strong>
            <small>WILDLIFE OBSERVATION SYSTEM</small>
          </span>
        </button>
        <WorkspaceTabs
          selected={workspaceTab}
          onSelect={selectWorkspace}
          liveBusy={liveBusy}
          taxaCount={taxa?.taxa.length}
        />
        <div className="header-tools">
          <InstallApp />
          <DisplayPreferences />
        </div>
      </header>
      <main>
        <section
          id="workspace-panel"
          className="workspace-panel"
          role="tabpanel"
          aria-labelledby={`workspace-tab-${workspaceTab}`}
          tabIndex={0}
        >
          <h1 className="sr-only">
            {page === "taxa"
              ? "Taxonomy"
              : page === "system"
                ? "System"
                : page === "observations"
                  ? "Field observations"
                  : sourceMode === "live"
                    ? "Monitor"
                    : "Media tests"}
          </h1>
          {(error ||
            resourceError ||
            (page === "watch" &&
              sourceMode === "library" &&
              (analysisError || activeAnalysis.error))) && (
            <div role="alert" className="error">
              {error || resourceError || analysisError || activeAnalysis.error}
              <button
                className="icon-button"
                onClick={() => {
                  setError("");
                  setResourceErrors({ library: "", config: "", system: "" });
                }}
                aria-label="Dismiss error"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {uploading && <UploadStatus filename={uploadFilename} />}
          {notice && (
            <div role="status" className="notice">
              {notice}
              <button
                className="icon-button"
                onClick={() => setNotice("")}
                aria-label="Dismiss notice"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {page === "taxa" && <Taxa />}
          {page === "observations" && (
            <>
              <ObservationArchive
                revision={archiveRevision}
                onInspect={openInspector}
              />
              <SensorHistory />
            </>
          )}
          {page === "system" && (
            <AnalysisDetails
              config={config}
              models={models}
              tab={systemTab}
              onTab={setSystemTab}
              busy={!!fileBusy || liveBusy}
              onConfig={setConfig}
              onSave={() => void save()}
            />
          )}
          <div hidden={page !== "watch"}>
            {sourceMode === "library" && (
              <div className="source-bar">
                <span className="privacy-note">
                  {videos.length} retained test sources
                </span>
                <label className="upload-button" aria-busy={uploading}>
                  <Icon name="upload" size={17} />
                  {uploading ? "Adding…" : "Add media"}
                  <input
                    aria-label="Upload photo, video or audio"
                    type="file"
                    disabled={
                      uploading || endingTests || uploadAllowed !== true
                    }
                    accept=".jpg,.jpeg,.png,.webp,.mp4,.mov,.m4v,.mkv,.avi,.webm,.mts,.wav,.flac,.mp3,.m4a,.aac,.ogg,.opus"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void upload(file);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
            )}
            {sourceMode === "library" && (
              <div className="test-session-bar">
                <div>
                  <strong>
                    {testSession
                      ? endingTests
                        ? "Ending test session…"
                        : "Temporary test session"
                      : "Temporary media tests"}
                  </strong>
                  <span>
                    New uploads and new analysis runs are cleared when this
                    session ends. Previously saved sources and runs are
                    retained.
                  </span>
                  {testSession && (
                    <small>
                      Closed or disconnected browser sessions expire after 24
                      hours without a heartbeat.
                    </small>
                  )}
                </div>
                {testSession && (
                  <button
                    disabled={
                      endingTests || uploading || starting || !!pendingControl
                    }
                    onClick={() => void endTests()}
                  >
                    {endingTests
                      ? "Clearing temporary data…"
                      : "End test session"}
                  </button>
                )}
              </div>
            )}
            {sourceMode === "library" && uploadAllowed === false && (
              <p className="muted">Upload media from the device itself.</p>
            )}
            <div hidden={sourceMode !== "live"}>
              <LiveCamera
                visible={page === "watch" && sourceMode === "live"}
                fileBusy={fileBusy}
                config={config}
                onInspect={openInspector}
                onBusy={setLiveBusy}
                onSettings={openSettings}
              />
            </div>
            {sourceMode === "library" && (
              <>
                <SourceLibrary
                  videos={videos}
                  selected={selected}
                  onSelect={openSource}
                  onRefresh={() => void loadVideos()}
                />
                <div className="workspace">
                  <section
                    className="media-stage"
                    aria-label="Selected recording"
                  >
                    <div className="stage-heading">
                      <div>
                        <span className="source-type">
                          <Icon
                            name={
                              video?.media_kind === "image"
                                ? "eye"
                                : video?.media_kind === "audio"
                                  ? "sound"
                                  : "play"
                            }
                            size={13}
                          />
                          {video?.media_kind === "image"
                            ? "PHOTOGRAPH"
                            : video?.media_kind === "audio"
                              ? "AUDIO RECORDING"
                              : "VIDEO RECORDING"}
                        </span>
                        <h3>
                          {video
                            ? sourceName(video.filename)
                            : "No source selected"}
                        </h3>
                      </div>
                      {video && (
                        <span className="media-metadata">
                          {video.media_kind === "audio"
                            ? "Audio"
                            : video.width + " × " + video.height}
                          <small>
                            {video.media_kind === "image"
                              ? "Original image"
                              : video.audio
                                ? "Original picture & audio"
                                : "Original picture"}
                          </small>
                        </span>
                      )}
                    </div>
                    {video ? (
                      video.media_kind === "image" ? (
                        <ImagePlayer
                          key={video.source_id}
                          video={video}
                          show={show}
                          boxesAt={boxesAt}
                        />
                      ) : video.media_kind === "audio" ? (
                        <AudioPlayer
                          key={video.source_id}
                          source={video}
                          onTime={setTime}
                          seek={seek}
                        />
                      ) : (
                        <VideoPlayer
                          key={video.source_id}
                          video={video}
                          onTime={setTime}
                          show={show}
                          boxesAt={boxesAt}
                          seek={seek}
                        />
                      )
                    ) : (
                      <div className="empty">
                        <Icon name="camera" size={38} />
                        <h3>No media in the library</h3>
                        <p>
                          Add a photograph, video or audio recording to begin an
                          analysis.
                        </p>
                      </div>
                    )}
                    <div className="toolbar playback-toolbar">
                      <AnalysisActions
                        source={video}
                        job={job}
                        blocked={fileBusy || liveBusy}
                        canStart={!!config && !!taxa?.taxa.length}
                        pending={starting ? "start" : pendingControl}
                        onStart={() => void start()}
                        onPause={() => void changeAnalysis("pause")}
                        onResume={() => void changeAnalysis("resume")}
                      />
                      {video?.media_kind !== "audio" && (
                        <label>
                          <input
                            type="checkbox"
                            checked={show}
                            onChange={(e) => setShow(e.target.checked)}
                          />{" "}
                          Show detections
                        </label>
                      )}
                      <code className="playback-time">
                        {formatTime(time)}{" "}
                        <span>/ {formatTime(video?.duration_ms ?? 0)}</span>
                      </code>
                      <button
                        className="icon-button"
                        onClick={openSettings}
                        aria-label="Recording analysis settings"
                      >
                        <Icon name="settings" size={18} />
                      </button>
                    </div>
                    {liveBusy && (
                      <div className="analysis-busy-note" role="status">
                        <p id="file-analysis-live-reason">
                          FALCON analyzes one source at a time. Stop live
                          observation to analyze this file.
                        </p>
                        <button
                          className="text-button"
                          onClick={() => setSourceMode("live")}
                        >
                          Open Live camera <Icon name="arrow" size={15} />
                        </button>
                      </div>
                    )}
                    {isActiveAnalysis(activeAnalysis.job) &&
                      activeAnalysis.job?.job_id !== job?.job_id && (
                        <div className="analysis-busy-note" role="status">
                          <p>
                            Analysis is running for{" "}
                            {videos.find(
                              (item) =>
                                item.source_id ===
                                activeAnalysis.job?.source_id,
                            )?.filename ?? "another source"}
                            . Pause it before starting another analysis or the
                            live camera.
                          </p>
                          <button
                            className="text-button"
                            onClick={openActiveAnalysis}
                          >
                            Open active analysis <Icon name="arrow" size={15} />
                          </button>
                        </div>
                      )}
                    {resumable && (
                      <div className="analysis-busy-note" role="status">
                        <p>
                          {job?.resume_stage === "audio"
                            ? "Visual progress is saved. The unfinished audio stage restarts when resumed."
                            : `Progress saved through ${formatTime(job?.resume_from_ms ?? job?.coverage_ms ?? 0)}. Resume continues this run with its saved settings.`}
                        </p>
                      </div>
                    )}
                    {job &&
                      ["paused", "interrupted", "cancelled", "failed"].includes(
                        job.status,
                      ) &&
                      !resumable &&
                      job.resume_reason && (
                        <div className="analysis-busy-note" role="status">
                          <p>{job.resume_reason}</p>
                        </div>
                      )}
                    {(busy || resumable || job?.error) && (
                      <div className="analysis-status">
                        <div>
                          <span>
                            {job?.status === "pausing" ||
                            pendingControl === "pause"
                              ? supportsAnalysisControl(job)
                                ? "Saving progress…"
                                : "Stopping…"
                              : (job?.stage ?? "Starting analysis")}
                          </span>
                          <span>{Math.round((job?.progress ?? 0) * 100)}%</span>
                        </div>
                        <progress max="1" value={job?.progress ?? 0} />
                        {job?.error && <p className="error">{job.error}</p>}
                      </div>
                    )}
                    {video && video.media_kind !== "image" && (
                      <Timeline
                        events={events}
                        duration={video.duration_ms}
                        time={time}
                        coverage={job?.coverage_ms ?? 0}
                        onSeek={doSeek}
                      />
                    )}
                    <div className="stage-caption">
                      <span>
                        {job?.status === "completed"
                          ? `${events.length} observation records · analysis complete`
                          : busy
                            ? "Observations appear as analysis progresses"
                            : resumable
                              ? `${events.length} observation records saved · analysis ${job?.status}`
                              : "Select an observation to review its source frame"}
                      </span>
                      <span>
                        {video?.media_kind === "image"
                          ? "Single frame"
                          : video?.media_kind === "audio"
                            ? "Acoustic analysis"
                            : `${config?.sample_fps ?? "—"} frames / second`}
                      </span>
                    </div>
                    {video && <SourceTechnical source={video} />}
                    {video?.playback_warning && (
                      <details className="codec-note">
                        <summary>About this video format</summary>
                        <p>{video.playback_warning}</p>
                      </details>
                    )}
                  </section>
                  <ObservationRail
                    audioOnly={video?.media_kind === "audio"}
                    visual={current.visual.filter(
                      (event) => event.review.status !== "false_positive",
                    )}
                    audio={current.audio}
                    audioStatus={
                      job?.audio_status ??
                      (video?.audio ? "Ready for analysis" : "No audio stream")
                    }
                    onInspect={openInspector}
                  />
                </div>
              </>
            )}
            {sourceMode === "live" && <ClimatePanel />}
            {sourceMode === "library" && (
              <>
                <ObservationHistory
                  key={selected}
                  events={events}
                  jobs={jobs}
                  runId={runId}
                  video={video}
                  onRun={(id) => {
                    selectionEpoch.current += 1;
                    setRunId(id);
                  }}
                  onSeek={doSeek}
                  onInspect={openInspector}
                />
                <details className="system-workspace media-test-diagnostics">
                  <summary>Selected test · analysis diagnostics</summary>
                  <RunDetails job={job} sourceName={video?.filename} />
                  <details className="media-test-records">
                    <summary>
                      Test records · original predictions and saved reviews
                    </summary>
                    <pre className="json-view">
                      {JSON.stringify(events, null, 2)}
                    </pre>
                  </details>
                </details>
              </>
            )}
          </div>
        </section>
        <footer className="scientific-footer">
          <span>FALCON · Field Acoustic, Lens & Climate Observation Node</span>
          <span>Developer · Vinay Chittora</span>
        </footer>
      </main>
      {inspect && (
        <Inspector
          key={inspect.event_id}
          event={inspect}
          playEvidence={inspectPlayback}
          source={videos.find((item) => item.source_id === inspect.source_id)}
          taxa={taxa?.taxa ?? []}
          onClose={() => setInspect(null)}
          onSeek={
            sourceMode === "library" && inspect.source_id === selected
              ? (ms) => {
                  setPage("watch");
                  doSeek(ms);
                }
              : undefined
          }
          onSaved={(updated) => {
            setInspect(updated);
            refresh();
            setArchiveRevision((value) => value + 1);
            setNotice("Review saved.");
          }}
        />
      )}
    </TaxonNamesContext.Provider>
  );
}
