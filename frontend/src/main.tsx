import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./style.css";
import {
  applyDisplayPreferences,
  readDisplayPreferences,
} from "./api/displayPreferences";

applyDisplayPreferences(readDisplayPreferences());

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  const register = () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      // Offline help is optional; local analysis remains available without it.
    });
  };
  if (document.readyState === "complete") register();
  else window.addEventListener("load", register, { once: true });
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
