// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { fetchEncounters, liveSourceId, type Encounter } from "./api/encounters";
import { liveFeedFilters, splitLiveFeed } from "./api/liveFeed";
import DetectionBell, { RingOptions } from "./ui/DetectionBell";
import { formatElapsed } from "./api/format";
import { indexTaxonNames } from "./api/names";
import { listNodes } from "./api/nodes";
import { reviewsSavedMessage } from "./api/recordView";
import AnalysisDetails, { type SystemTab } from "./components/AnalysisDetails";
import DisplayPreferences from "./components/DisplayPreferences";
import Icon, { FalconMark, type IconName } from "./components/Icon";
import Inspector from "./components/Inspector";
import { TaxonNamesContext } from "./components/TaxonNames";
import { ListenDetails, ListenSwitch, NavRows, ShellSheet } from "./components/Shell";
import { defaultToReviewFilters } from "./api/reviewList";
import { usePoll } from "./hooks/usePoll";
import ExportPage from "./pages/ExportPage";
import HelpPage, { HelpLink, helpHref } from "./pages/HelpPage";
import LivePage, { liveStatus } from "./pages/LivePage";
import MediaTestsPage from "./pages/MediaTestsPage";
import PostingPage from "./pages/PostingPage";
import ReviewPage from "./pages/ReviewPage";
import SensorsPage from "./pages/SensorsPage";
import SummaryPage from "./pages/SummaryPage";
import Taxa, { type TaxaCache, type Taxon } from "./pages/Taxa";
import type { Config, LiveState, Models } from "./types";
import { confirm } from "./api/activity";
import { useActivity } from "./hooks/useActivity";
import ActivityLine from "./ui/ActivityLine";
import "./app.css";
import { CREDIT_LINE } from "./version";
import AboutFalcon from "./ui/AboutFalcon";

export type Page =
  | "live"
  | "review"
  | "summary"
  | "sensors"
  | "export"
  | "media"
  | "species"
  | "system"
  | "help"
  | "posting";

export const PAGES: {
  page: Page;
  label: string;
  icon: IconName;
  hint: string;
}[] = [
  {
    page: "live",
    label: "Live",
    icon: "eye",
    hint: "Watch and check detections as they happen",
  },
  {
    page: "review",
    label: "Review",
    icon: "check",
    hint: "Confirm, correct or discard animal visits",
  },
  {
    page: "summary",
    label: "Summary",
    icon: "list",
    hint: "Species counts and observation sessions",
  },
  {
    page: "sensors",
    label: "Sensors",
    icon: "node",
    hint: "Sensor nodes and cameras",
  },
  {
    page: "export",
    label: "Export",
    icon: "download",
    hint: "Clean data for researchers",
  },
  {
    page: "media",
    label: "Media tests",
    icon: "upload",
    hint: "Try FALCON on a recording",
  },
  {
    page: "species",
    label: "Species",
    icon: "leaf",
    hint: "Local species list",
  },
  {
    page: "system",
    label: "System",
    icon: "settings",
    hint: "Settings, models and health",
  },
  {
    page: "help",
    label: "Help",
    icon: "question",
    hint: "Guides and handbooks: everything about FALCON",
  },
];

/** A top-bar title that does not fit a phone's bar, and its short form: below 900 px
 * ("narrow", the phone bar) or only below 375 px ("tiny"). */
const SHORT_TITLES: Partial<Record<Page, [string, "narrow" | "tiny"]>> = {
  posting: ["iNaturalist", "narrow"],
  media: ["Media", "tiny"],
};

/** The guide section the top bar's Help button opens for each page. */
const PAGE_HELP: Partial<Record<Page, [string, string?]>> = {
  live: ["user-guide", "live"],
  review: ["user-guide", "review"],
  posting: ["user-guide", "review"],
  summary: ["user-guide", "summary"],
  sensors: ["sensor-node"],
  export: ["data-export"],
  media: ["user-guide", "media-tests"],
  species: ["user-guide", "species"],
  system: ["user-guide", "system"],
};

export function pageFromHash(hash: string): Page {
  const value = hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  // Posting to iNaturalist is reached from Review, not from the menu.
  if (value === "posting") return "posting";
  return PAGES.find((item) => item.page === value)?.page ?? "live";
}

/** "#/help/sensor-node/checks" -> "sensor-node/checks" */
export function helpRoute(hash: string): string {
  const match = hash.match(/^#\/?help\/(.*)$/);
  return match ? match[1] : "";
}

const ACTIVE = ["connecting", "live", "reconnecting", "stopping"];

/** The header dot (25 Nov): solid green only while observing with FALCON in reach; a
 * ring while connecting or reconnecting; a warning mark when FALCON cannot be reached. */
export function dotClass(down: boolean, status: string | undefined): string {
  if (down) return " down";
  if (status === "connecting" || status === "reconnecting") return " pending";
  return status && ACTIVE.includes(status) ? "" : " off";
}

export default function App() {
  const [page, setPage] = useState<Page>(() =>
    typeof window === "undefined" ? "live" : pageFromHash(window.location.hash),
  );
  const [route, setRoute] = useState(() =>
    typeof window === "undefined" ? "" : helpRoute(window.location.hash),
  );
  const [menuOpen, setMenuOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [systemTab, setSystemTab] = useState<SystemTab>("live");
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState("");
  const [inspect, setInspect] = useState<{
    encounter: Encounter;
    queue?: Encounter[];
    /** Review's page as it holds it, attached hidden rows included: the stays' chips. */
    pool?: Encounter[];
    nonce: number;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const [countsTick, setCountsTick] = useState(0);
  const recount = useCallback(() => setCountsTick((value) => value + 1), []);
  const taxa = usePoll(() => api<TaxaCache>("/taxa"), 60000);
  const reviewBirds = usePoll(() => api<Taxon[]>("/taxa/review-birds"), 3600000);
  const models = usePoll(() => api<Models>("/models"), 30000);
  const system = usePoll(
    () => api<{ upload_allowed?: boolean }>("/system"),
    60000,
  );
  // The live state is also the heartbeat of the activity sign (api/activity.ts).
  const live = usePoll(() => api<LiveState>("/live/state"), 3000);
  const heartbeat = live.refresh;
  const activity = useActivity(heartbeat);
  const nodes = usePoll(listNodes, 10000);
  const toReview = usePoll(
    () =>
      fetchEncounters({ ...defaultToReviewFilters(), limit: 1 }),
    30000,
    `${revision}-${countsTick}`,
  );
  // Names a reviewer can use: the local list plus the North India sound-list birds.
  const reviewTaxa = useMemo(
    () => [...(taxa.data?.taxa ?? []), ...(reviewBirds.data ?? [])],
    [taxa.data, reviewBirds.data],
  );
  const taxonNames = useMemo(() => indexTaxonNames(reviewTaxa), [reviewTaxa]);
  const liveState = live.data;
  const liveBusy = !!liveState && ACTIVE.includes(liveState.status);
  const status = liveStatus(liveState);
  const nodeList = nodes.data?.nodes ?? [];
  // The same visits Live lists (Likely and Confirmed, this session) feed the bar's Ring.
  const bellSource = liveBusy ? liveSourceId(liveState?.session_id) : undefined;
  const bellFeed = usePoll(
    () => fetchEncounters(liveFeedFilters(bellSource, "all", false)),
    liveBusy ? 3000 : 60000,
    bellSource ?? "recent",
  );
  const bellVisits = bellFeed.data
    ? splitLiveFeed(bellFeed.data.encounters, false).shown
    : null;
  const online = nodeList.filter((node) => node.online).length;

  useEffect(() => {
    const onHash = () => {
      setPage(pageFromHash(window.location.hash));
      if (/[?&]scenery=1/.test(window.location.hash)) setSystemTab("live");
      setRoute(helpRoute(window.location.hash));
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    let alive = true;
    api<Config>("/config")
      .then((value) => {
        if (alive) setConfig((current) => current ?? value);
      })
      .catch((reason: unknown) => {
        if (alive)
          setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      alive = false;
    };
  }, []);

  const navigate = useCallback((next: string) => {
    const target = pageFromHash(next);
    const query = next.includes("?") ? "?" + next.split("?")[1] : "";
    window.location.hash = `#/${target}${query}`;
    setPage(target);
    setMenuOpen(false);
    setStatusOpen(false);
  }, []);

  // Saving is allowed while observing: FALCON restarts the observation (a few seconds)
  // so the new settings apply at once.
  const [savingConfig, setSavingConfig] = useState(false);
  async function saveConfig() {
    setSavingConfig(true);
    try {
      setConfig(
        await api<Config>("/config", {
          method: "PUT",
          body: JSON.stringify(config),
        }),
      );
      confirm(
        liveBusy
          ? "Analysis settings saved. Observation restarted with the new settings."
          : "Analysis settings saved.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSavingConfig(false);
    }
  }

  const openEncounter = useCallback(
    (encounter: Encounter, queue?: Encounter[], pool?: Encounter[]) =>
      setInspect({ encounter, queue, pool, nonce: Date.now() }),
    [],
  );
  const badges: Partial<Record<Page, string>> = {
    review: toReview.data?.total ? toReview.data.total.toLocaleString() : "",
    sensors: nodeList.length ? `${online}/${nodeList.length}` : "",
    species: taxa.data?.taxa.length
      ? taxa.data.taxa.length.toLocaleString()
      : "",
  };
  const navRows = PAGES.map((item) => ({ ...item, badge: badges[item.page] }));
  const help = PAGE_HELP[page];
  const nodeText = nodeList.length
    ? `${online} of ${nodeList.length} node${nodeList.length === 1 ? "" : "s"} online`
    : "No sensor node";
  const current =
    page === "posting"
      ? { label: "Post to iNaturalist" }
      : (PAGES.find((item) => item.page === page) ?? PAGES[0]);
  const short = SHORT_TITLES[page];
  // A new "#/posting?visit=..." (from the Review popup) opens that visit's preview.
  const postingKey =
    typeof window === "undefined" ? "" : window.location.hash;
  return (
    <TaxonNamesContext.Provider value={taxonNames}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="app-shell fs-shell">
        <nav className="fs-side" aria-label="FALCON pages">
          <button
            className="brand"
            onClick={() => navigate("live")}
            aria-label="FALCON home"
          >
            <FalconMark />
            <span>
              <strong>FALCON</strong>
              <small>Field Acoustic, Lens &amp; Climate Observation Node</small>
            </span>
          </button>
          <div className="fs-rows">
            <NavRows rows={navRows} current={page} onGo={navigate} />
          </div>
          <div className="sidebar-foot">
            <DisplayPreferences />
            <button type="button" className="fs-credit" onClick={() => setAboutOpen(true)}>
              {CREDIT_LINE}
            </button>
          </div>
        </nav>
        <div className="main-column">
          <header className="fs-bar">
            <button
              type="button"
              className="rv-icon fs-menu"
              aria-label="Open the menu"
              aria-haspopup="dialog"
              onClick={() => setMenuOpen(true)}
            >
              <Icon name="menu" size={22} />
            </button>
            <h1 className={`fs-title${short ? ` fs-title-${short[1]}` : ""}`}>
              {short ? (
                <>
                  <span className="fs-t-long">{current.label}</span>
                  <span className="fs-t-short">{short[0]}</span>
                </>
              ) : (
                current.label
              )}
            </h1>
            <ActivityLine activity={activity} />
            <ListenSwitch />
            <DetectionBell
              bar
              encounters={bellVisits}
              resetKey={bellSource ?? "recent"}
            />
            <a
              className="rv-icon"
              href={help ? helpHref(help[0], help[1]) : "#/help"}
              aria-label="Help for this page"
            >
              <Icon name="question" size={22} />
            </a>
            <button
              type="button"
              className={`rv-icon fs-stat${dotClass(activity.down, liveState?.status)}`}
              aria-haspopup="dialog"
              aria-label={
                activity.down
                  ? `Station status: FALCON cannot be reached, ${nodeText}`
                  : `Station status: ${status.label.toLowerCase()}, ${nodeText}, ${(toReview.data?.total ?? 0).toLocaleString()} to review`
              }
              onClick={() => setStatusOpen(true)}
            >
              <Icon name="activity" size={22} />
              <i aria-hidden="true" />
            </button>
          </header>
          <main id="main" tabIndex={-1}>
            {error && (
              <p className="banner banner-bad toast" role="alert">
                {error}
                <button
                  className="icon-button"
                  onClick={() => setError("")}
                  aria-label="Dismiss"
                >
                  <Icon name="close" size={14} />
                </button>
              </p>
            )}
            {page === "live" && (
              <LivePage
                taxa={reviewTaxa}
                onOpen={openEncounter}
                onNavigate={navigate}
                onCounts={recount}
              />
            )}
            {page === "review" && (
              <ReviewPage
                taxa={reviewTaxa}
                onOpen={openEncounter}
                revision={revision}
                onCounts={recount}
              />
            )}
            {page === "summary" && <SummaryPage onNavigate={navigate} />}
            {page === "sensors" && <SensorsPage onNavigate={navigate} />}
            {page === "export" && <ExportPage />}
            {page === "media" && (
              <MediaTestsPage
                config={config}
                taxa={taxa.data}
                liveBusy={liveBusy}
                uploadAllowed={
                  system.data ? system.data.upload_allowed !== false : null
                }
                onSettings={() => {
                  setSystemTab("settings");
                  navigate("system");
                }}
                onOpenLive={() => navigate("live")}
              />
            )}
            {page === "species" && (
              <div className="page">
                <div className="page-help-row">
                  <HelpLink slug="user-guide" section="species" />
                </div>
                <Taxa />
              </div>
            )}
            {page === "help" && <HelpPage route={route} onAbout={() => setAboutOpen(true)} />}
            {page === "posting" && <PostingPage key={postingKey} />}
            {page === "system" && (
              <div className="page system-page">
                <header className="page-header">
                  <div>
                    <p>
                      Health of this inference computer, analysis settings,
                      models and remote access.
                    </p>
                  </div>
                </header>
                <AnalysisDetails
                  config={config}
                  models={models.data}
                  tab={systemTab}
                  onTab={setSystemTab}
                  busy={savingConfig}
                  onConfig={setConfig}
                  onSave={() => void saveConfig()}
                />
              </div>
            )}
          </main>
        </div>
      </div>
      {menuOpen && (
        <ShellSheet
          title="FALCON"
          onClose={() => setMenuOpen(false)}
          initialFocus='[aria-current="page"]'
        >
          <nav className="fs-nv rv-gut" aria-label="FALCON pages">
            <NavRows rows={navRows} current={page} onGo={navigate} />
            <div className="sidebar-foot">
              <DisplayPreferences />
              <button
                type="button"
                className="fs-credit"
                onClick={() => {
                  setMenuOpen(false);
                  setAboutOpen(true);
                }}
              >
                {CREDIT_LINE}
              </button>
            </div>
          </nav>
        </ShellSheet>
      )}
      {aboutOpen && <AboutFalcon onClose={() => setAboutOpen(false)} />}
      {statusOpen && (
        <ShellSheet title="Station status" onClose={() => setStatusOpen(false)}>
          {activity.down && (
            <p className="banner banner-bad fs-down rv-gut" role="alert">
              {activity.state.text} The values below are the last ones received.
            </p>
          )}
          <div className="fs-facts rv-gut">
            <dl className="fs-kv">
              <div>
                <dt>Station</dt>
                <dd>{status.label}</dd>
              </div>
              {liveBusy && (
                <>
                  <div>
                    <dt>Source</dt>
                    <dd>{liveState?.name}</dd>
                  </div>
                  <div>
                    <dt>Session time</dt>
                    <dd className="fs-mono">
                      {formatElapsed(liveState?.session_timestamp_ms)}
                    </dd>
                  </div>
                </>
              )}
              <div>
                <dt>Sensor nodes</dt>
                <dd>{nodeText}</dd>
              </div>
              <div>
                <dt>To review</dt>
                <dd>{(toReview.data?.total ?? 0).toLocaleString()}</dd>
              </div>
            </dl>
            <div className="fs-actions">
              <button type="button" className="rv-next" onClick={() => navigate("live")}>
                Go to Live
              </button>
              <button type="button" className="tlink" onClick={() => navigate("sensors")}>
                Sensor nodes
              </button>
              <button type="button" className="tlink" onClick={() => navigate("review")}>
                Review
              </button>
            </div>
            <ListenDetails />
            <section className="fs-listen" aria-labelledby="fs-ring-h">
              <h3 id="fs-ring-h">Ring</h3>
              <div className="fs-listen-options">
                <RingOptions />
              </div>
            </section>
          </div>
        </ShellSheet>
      )}
      {inspect && (
        <Inspector
          key={`${inspect.encounter.encounter_id}-${inspect.nonce}`}
          encounter={inspect.encounter}
          queue={inspect.queue}
          pool={inspect.pool}
          startIndex={
            inspect.queue?.findIndex(
              (item) => item.encounter_id === inspect.encounter.encounter_id,
            ) ?? 0
          }
          taxa={reviewTaxa}
          onClose={(saved) => {
            setInspect(null);
            if (saved) {
              setRevision((value) => value + 1);
              confirm(reviewsSavedMessage(saved));
            }
          }}
        />
      )}
    </TaxonNamesContext.Provider>
  );
}
