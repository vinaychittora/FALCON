// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect } from "react";
import Icon from "../components/Icon";

export const TOAST_MS = 3000;

/**
 * A short floating confirmation. It closes by itself or when tapped. While `paused`
 * (a popup covers the page) its time does not run, so it is still seen afterwards.
 */
export default function Toast({
  message,
  paused = false,
  onClose,
}: {
  message: string;
  paused?: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(onClose, TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [message, paused, onClose]);
  return (
    <div className="floating-toast" role="status">
      <button type="button" onClick={onClose} aria-label={`${message} Dismiss`}>
        <span>{message}</span>
        <Icon name="close" size={14} />
      </button>
    </div>
  );
}
