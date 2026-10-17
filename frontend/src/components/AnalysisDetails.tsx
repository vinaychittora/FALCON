import { useState } from "react";
import type { Config, Detection, Job, Models } from "../types";
import Settings from "./Settings";
import RunDetails from "./RunDetails";
import DeviceAccess from "./DeviceAccess";

export default function AnalysisDetails({
  config,
  models,
  job,
  events,
  sourceName,
  busy,
  onConfig,
  onSave,
}: {
  config: Config | null;
  models: Models | null;
  job: Job | null;
  events: Detection[];
  sourceName?: string;
  busy: boolean;
  onConfig: (value: Config) => void;
  onSave: () => void;
}) {
  const [tab, setTab] = useState("settings");
  const activeTab = tab;
  const tabs = [
    ["settings", "Configuration"],
    ["models", "Model status"],
    ["device", "Device access"],
    ["progress", "Selected run"],
    ["raw", "Raw records"],
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
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
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
      {activeTab === "progress" && (
        <RunDetails job={job} sourceName={sourceName} />
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
      {activeTab === "raw" && (
        <>
          <p className="raw-caption">
            {sourceName ?? "No media selected"} · Original predictions and saved
            review fields.
          </p>
          <pre className="json-view">{JSON.stringify(events, null, 2)}</pre>
        </>
      )}
    </div>
  );
}
