import Icon, { type IconName } from "./Icon";

export const WORKSPACE_TABS = [
  "monitor",
  "observations",
  "media",
  "taxa",
  "system",
] as const;
export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];

const tabLabels: Record<WorkspaceTab, [string, IconName]> = {
  monitor: ["Monitor", "camera"],
  observations: ["Observations", "eye"],
  media: ["Media tests", "library"],
  taxa: ["Taxonomy", "leaf"],
  system: ["System", "settings"],
};

export function nextWorkspaceTab(
  current: WorkspaceTab,
  key: string,
): WorkspaceTab | null {
  const index = WORKSPACE_TABS.indexOf(current);
  if (key === "Home") return WORKSPACE_TABS[0];
  if (key === "End") return WORKSPACE_TABS[WORKSPACE_TABS.length - 1];
  if (key === "ArrowRight")
    return WORKSPACE_TABS[(index + 1) % WORKSPACE_TABS.length];
  if (key === "ArrowLeft")
    return WORKSPACE_TABS[
      (index + WORKSPACE_TABS.length - 1) % WORKSPACE_TABS.length
    ];
  return null;
}

export default function WorkspaceTabs({
  selected,
  onSelect,
  liveBusy,
  taxaCount,
}: {
  selected: WorkspaceTab;
  onSelect: (tab: WorkspaceTab) => void;
  liveBusy: boolean;
  taxaCount?: number;
}) {
  return (
    <nav role="tablist" aria-label="Main navigation">
      {WORKSPACE_TABS.map((key) => (
        <button
          key={key}
          id={`workspace-tab-${key}`}
          role="tab"
          aria-selected={selected === key}
          aria-controls="workspace-panel"
          tabIndex={selected === key ? 0 : -1}
          className={selected === key ? "active" : ""}
          onClick={() => onSelect(key)}
          onKeyDown={(event) => {
            const next = nextWorkspaceTab(key, event.key);
            if (!next) return;
            event.preventDefault();
            onSelect(next);
            document.getElementById(`workspace-tab-${next}`)?.focus();
          }}
        >
          <Icon name={tabLabels[key][1]} size={18} />
          {tabLabels[key][0]}
          {key === "monitor" && liveBusy && (
            <i className="quiet-dot" aria-label="Observing" />
          )}
          {key === "taxa" && (
            <span className="nav-count">
              {taxaCount?.toLocaleString() ?? "—"}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}
