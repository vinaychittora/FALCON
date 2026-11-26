// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { startListening, stopListening, useListen } from "../api/listenStore";
import { useBackToClose } from "../hooks/useBackToClose";
import { LevelMeter, ListenOptions } from "../ui/LiveListen";
import Icon, { type IconName } from "./Icon";
import "./record-view.css";
import "./shell.css";

export type NavRow = {
  page: string;
  label: string;
  icon: IconName;
  hint: string;
  badge?: string;
};

/** One full-screen layer on the phone, a dialog on desktop (like the species chooser).
 * The page under it is inert, Esc and Android Back close it, focus goes back on close. */
export function ShellSheet({
  title,
  onClose,
  children,
  initialFocus,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  initialFocus?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  useBackToClose(onClose);
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element) return;
    opener.current = document.activeElement;
    if (!element.open) element.showModal();
    const first = initialFocus
      ? element.querySelector<HTMLElement>(initialFocus)
      : null;
    (first ?? element.querySelector<HTMLElement>("button"))?.focus();
    return () => {
      element.close();
      const back = opener.current;
      window.setTimeout(() => {
        if (back instanceof HTMLElement && back.isConnected) back.focus();
      }, 0);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <dialog
      ref={dialog}
      className="rv-sheet fs-sheet"
      aria-labelledby="fs-sheet-title"
      onCancel={(change) => {
        change.preventDefault();
        onClose();
      }}
      onClick={(change) => {
        if (change.target === change.currentTarget) onClose();
      }}
    >
      <div className="rv-sheet-top rv-gut">
        <h2 id="fs-sheet-title">{title}</h2>
        <button type="button" className="rv-icon" aria-label="Close" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}

/** The page rows, the same in the phone menu and the desktop sidebar. */
export function NavRows({
  rows,
  current,
  onGo,
}: {
  rows: NavRow[];
  current: string;
  onGo: (page: string) => void;
}) {
  return (
    <>
      {rows.map((row) => (
        <a
          key={row.page}
          href={`#/${row.page}`}
          className="fs-row"
          data-page={row.page}
          aria-current={current === row.page ? "page" : undefined}
          title={row.hint}
          onClick={(change) => {
            change.preventDefault();
            onGo(row.page);
          }}
        >
          <Icon name={row.icon} size={20} />
          <span>{row.label}</span>
          {row.badge ? <span className="fs-n">{row.badge}</span> : <span />}
        </a>
      ))}
    </>
  );
}

/** The app-wide Listen switch of the top bar (the same player as on Live). */
export function ListenSwitch() {
  const listen = useListen();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={listen.on}
      className="fs-switch"
      title={listen.error || "Hear the sensor's microphone on this computer"}
      onClick={() => (listen.on ? stopListening() : void startListening())}
    >
      <span className="rv-switch-track" aria-hidden="true" />
      Listen
    </button>
  );
}

/** Listen's level and options, in the station status layer under "Listen". */
export function ListenDetails() {
  const listen = useListen();
  return (
    <section className="fs-listen" aria-labelledby="fs-listen-h">
      <h3 id="fs-listen-h">Listen</h3>
      <p className="fs-muted">
        {listen.on ? "On" : "Off"}
        {listen.error ? ` · ${listen.error}` : ""}
      </p>
      {listen.on && <LevelMeter rms={listen.rms} peak={listen.peak} />}
      <div className="fs-listen-options">
        <ListenOptions />
      </div>
    </section>
  );
}
