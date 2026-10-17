import type { Config, Models } from "../types";
import Settings from "./Settings";
import DeviceAccess from "./DeviceAccess";
import LiveSystem from "./LiveSystem";

export type SystemTab = "live" | "settings" | "models" | "device";

export default function AnalysisDetails({
  config,
  models,
  tab,
  onTab,
  busy,
  onConfig,
  onSave,
}: {
  config: Config | null;
  models: Models | null;
  tab: SystemTab;
  onTab: (tab: SystemTab) => void;
  busy: boolean;
  onConfig: (value: Config) => void;
  onSave: () => void;
}) {
  const activeTab = tab;
  const tabs: [SystemTab, string][] = [
    ["live", "Live status"],
    ["settings", "Configuration"],
    ["models", "Model status"],
    ["device", "Device access"],
  ];
  return (
    <div className="system-workspace">
      <div className="tabs" role="tablist" aria-label="System sections">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={activeTab === key}
            className={activeTab === key ? "active" : ""}
            onClick={() => onTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === "live" && <LiveSystem />}
      {activeTab === "settings" && config && (
        <>
          <Settings
            value={config}
            onChange={onConfig}
            onSave={onSave}
            busy={busy}
          />
        </>
      )}
      {activeTab === "device" && <DeviceAccess />}
      {activeTab === "models" && (
        <div className="progress-detail">
          <h3>Currently loaded models</h3>
          <div className="model-strip">
            {models?.models.map((model) => (
              <span key={model.name} title={model.version}>
                <i className={model.loaded ? "loaded" : ""} />
                {model.name}
                <small>
                  {model.loaded
                    ? "loaded"
                    : model.device.includes("subprocess")
                      ? "CPU · on demand"
                      : "on demand"}
                </small>
              </span>
            ))}
          </div>
          <details>
            <summary>Current model versions and memory</summary>
            <pre className="json-view">{JSON.stringify(models, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
