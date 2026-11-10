import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { fetchEncounters, type Encounter } from "./api/encounters";
import { formatElapsed } from "./api/format";
import { indexTaxonNames } from "./api/names";
import { listNodes } from "./api/nodes";
import AnalysisDetails, { type SystemTab } from "./components/AnalysisDetails";
import DisplayPreferences from "./components/DisplayPreferences";
import LiveListen from "./ui/LiveListen";
import Icon, { FalconMark, type IconName } from "./components/Icon";
import Inspector from "./components/Inspector";
import { TaxonNamesContext } from "./components/TaxonNames";
import { usePoll } from "./hooks/usePoll";
import ExportPage from "./pages/ExportPage";
import HelpPage, { HelpLink } from "./pages/HelpPage";
import LivePage, { liveStatus } from "./pages/LivePage";
import MediaTestsPage from "./pages/MediaTestsPage";
import ReviewPage from "./pages/ReviewPage";
import SensorsPage from "./pages/SensorsPage";
import SummaryPage from "./pages/SummaryPage";
import Taxa, { type TaxaCache } from "./pages/Taxa";
import type { Config, Detection, LiveState, Models } from "./types";
import Pill from "./ui/Pill";
import "./app.css";

export type Page =
  | "live"
  | "review"
  | "summary"
  | "sensors"
  | "export"
  | "media"
  | "species"
  | "system"
  | "help";

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

export function pageFromHash(hash: string): Page {
  const value = hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  return PAGES.find((item) => item.page === value)?.page ?? "live";
}

/** "#/help/sensor-node/checks" -> "sensor-node/checks" */
export function helpRoute(hash: string): string {
  const match = hash.match(/^#\/?help\/(.*)$/);
  return match ? match[1] : "";
}

const ACTIVE = ["connecting", "live", "reconnecting", "stopping"];

export default function App() {
  const [page, setPage] = useState<Page>(() =>
    typeof window === "undefined" ? "live" : pageFromHash(window.location.hash),
  );
  const [route, setRoute] = useState(() =>
    typeof window === "undefined" ? "" : helpRoute(window.location.hash),
  );
  const [menuOpen, setMenuOpen] = useState(false);
  const [systemTab, setSystemTab] = useState<SystemTab>("live");
  const [config, setConfig] = useState<Config | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [inspect, setInspect] = useState<{
    event: Detection;
    encounter: Encounter;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const taxa = usePoll(() => api<TaxaCache>("/taxa"), 60000);
  const models = usePoll(() => api<Models>("/models"), 30000);
  const system = usePoll(
    () => api<{ upload_allowed?: boolean }>("/system"),
    60000,
  );
  const live = usePoll(() => api<LiveState>("/live/state"), 3000);
  const nodes = usePoll(listNodes, 10000);
  const toReview = usePoll(
    () =>
      fetchEncounters({ scope: "live", review_status: "unreviewed", limit: 1 }),
    30000,
    String(revision),
  );
  const taxonNames = useMemo(
    () => indexTaxonNames(taxa.data?.taxa ?? []),
    [taxa.data],
  );
  const liveState = live.data;
  const liveBusy = !!liveState && ACTIVE.includes(liveState.status);
  const status = liveStatus(liveState);
  const nodeList = nodes.data?.nodes ?? [];
  const online = nodeList.filter((node) => node.online).length;

  useEffect(() => {
    const onHash = () => {
      setPage(pageFromHash(window.location.hash));
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
      setNotice(
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
    (encounter: Encounter) => setInspect({ event: encounter.event, encounter }),
    [],
  );
  const badges: Partial<Record<Page, string>> = {
    review: toReview.data?.total ? toReview.data.total.toLocaleString() : "",
    sensors: nodeList.length ? `${online}/${nodeList.length}` : "",
    species: taxa.data?.taxa.length
      ? taxa.data.taxa.length.toLocaleString()
      : "",
  };
  const current = PAGES.find((item) => item.page === page) ?? PAGES[0];
  return (
    <TaxonNamesContext.Provider value={taxonNames}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className={`app-shell${menuOpen ? " menu-open" : ""}`}>
        <aside className="sidebar" aria-label="FALCON">
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
          <nav aria-label="Main">
            {PAGES.map((item) => (
              <a
                key={item.page}
                href={`#/${item.page}`}
                className={page === item.page ? "active" : ""}
                aria-current={page === item.page ? "page" : undefined}
                title={item.hint}
                onClick={() => setMenuOpen(false)}
              >
                <Icon name={item.icon} size={19} />
                <span>{item.label}</span>
                {badges[item.page] && <em>{badges[item.page]}</em>}
              </a>
            ))}
          </nav>
          <div className="sidebar-foot">
            <DisplayPreferences />
            <small>FALCON 1.0 · Vinay Chittora</small>
          </div>
        </aside>
        <button
          className="scrim"
          aria-label="Close menu"
          tabIndex={-1}
          onClick={() => setMenuOpen(false)}
        />
        <div className="main-column">
          <div className="status-bar" aria-label="System status">
            <button
              className="icon-button menu-button"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-label="Menu"
              aria-expanded={menuOpen}
            >
              <Icon name="menu" size={20} />
            </button>
            <span className="status-page">{current.label}</span>
            {/* While listening, a small switch here keeps it controllable from any page. */}
            <LiveListen compact />
            <button
              className="status-item"
              onClick={() => navigate("live")}
              title="Live observation"
            >
              <Pill tone={status.tone}>{status.label}</Pill>
              {liveBusy && (
                <>
                  <span className="status-source">{liveState?.name}</span>
                  <code>{formatElapsed(liveState?.session_timestamp_ms)}</code>
                </>
              )}
            </button>
            <button
              className="status-item"
              onClick={() => navigate("sensors")}
              title="Sensor nodes"
            >
              <Icon name="node" size={16} />
              <span>
                {nodeList.length
                  ? `${online} of ${nodeList.length} node${nodeList.length === 1 ? "" : "s"} online`
                  : "No sensor node"}
              </span>
            </button>
            {!!toReview.data?.total && (
              <button
                className="status-item"
                onClick={() => navigate("review")}
              >
                <Icon name="check" size={16} />{" "}
                <span>{toReview.data.total.toLocaleString()} to review</span>
              </button>
            )}
          </div>
          <main id="main" tabIndex={-1}>
            {notice && (
              <p className="banner banner-good toast" role="status">
                {notice}
                <button
                  className="icon-button"
                  onClick={() => setNotice("")}
                  aria-label="Dismiss"
                >
                  <Icon name="close" size={14} />
                </button>
              </p>
            )}
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
                taxa={taxa.data?.taxa ?? []}
                onOpen={openEncounter}
                onNavigate={navigate}
              />
            )}
            {page === "review" && (
              <ReviewPage
                taxa={taxa.data?.taxa ?? []}
                onOpen={openEncounter}
                revision={revision}
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
            {page === "help" && <HelpPage route={route} />}
            {page === "system" && (
              <div className="page system-page">
                <header className="page-header">
                  <div>
                    <h1>
                      System <HelpLink slug="user-guide" section="system" />
                    </h1>
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
      {inspect && (
        <Inspector
          key={inspect.event.event_id}
          event={inspect.event}
          encounter={inspect.encounter}
          taxa={taxa.data?.taxa ?? []}
          onClose={() => setInspect(null)}
          onSaved={(updated) => {
            setInspect((value) =>
              value ? { ...value, event: updated } : value,
            );
            setRevision((value) => value + 1);
            setNotice("Review saved.");
          }}
        />
      )}
    </TaxonNamesContext.Provider>
  );
}
