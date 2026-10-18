import type { ReactNode } from "react";

export type Tone = "good" | "warn" | "bad" | "muted" | "neutral" | "live";

export default function Pill({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      <i aria-hidden="true" />
      {children}
    </span>
  );
}
