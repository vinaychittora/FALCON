import { useEffect, useState } from "react";
import Icon from "./Icon";
import { requestAppInstall, type AppInstallPrompt } from "../api/install";

type InstallPrompt = Event & AppInstallPrompt;

export default function InstallApp() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const ready = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallPrompt);
      setFailed(false);
    };
    const installed = () => {
      setPrompt(null);
      setFailed(false);
    };
    window.addEventListener("beforeinstallprompt", ready);
    window.addEventListener("appinstalled", installed);
    return () => {
      window.removeEventListener("beforeinstallprompt", ready);
      window.removeEventListener("appinstalled", installed);
    };
  }, []);
  if (!prompt)
    return failed ? (
      <small role="status">Use the browser menu to install FALCON.</small>
    ) : null;
  return (
    <button
      className="subtle"
      disabled={pending}
      title="Install the local FALCON interface as an app window"
      onClick={async () => {
        setPending(true);
        const outcome = await requestAppInstall(prompt);
        setFailed(outcome === "failed");
        setPrompt(null);
        setPending(false);
      }}
    >
      <Icon name="download" size={16} />
      Install app
    </button>
  );
}
