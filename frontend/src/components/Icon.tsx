import type { CSSProperties } from "react";

export type IconName =
  | "camera"
  | "library"
  | "upload"
  | "eye"
  | "sound"
  | "leaf"
  | "settings"
  | "arrow"
  | "refresh"
  | "download"
  | "sun"
  | "drop"
  | "wind"
  | "close"
  | "clock"
  | "activity"
  | "chip"
  | "play"
  | "shield"
  | "link"
  | "power"
  | "display";
const paths: Record<IconName, string> = {
  camera: "M14 7h-3L9 4H5L3 7H1v12h20V7h-4M15 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  library: "M4 3v18M9 3v18M14 5l5-1 4 16-5 1-4-16Z",
  upload: "M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  sound: "M3 10v4m4-8v12m5-15v18m5-15v12m4-8v4",
  leaf: "M5 19C-3 8 10 3 21 3c0 12-4 20-16 16Zm0 0L16 8M4 20l-2 2",
  settings: "M4 4v16m8-16v16m8-16v16M1 8h6m2 8h6m2-9h6",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  refresh: "M20 8a8 8 0 1 0 0 8M20 3v5h-5",
  download: "M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4",
  sun: "M12 1v2m0 18v2M1 12h2m18 0h2M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0Z",
  drop: "M12 2S5 10 5 15a7 7 0 0 0 14 0c0-5-7-13-7-13Z",
  wind: "M2 8h12a3 3 0 1 0-3-3M2 12h17a3 3 0 1 1-3 3M2 16h6a3 3 0 1 1-3 3",
  close: "m6 6 12 12M6 18 18 6",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2",
  activity: "M2 12h4l3-8 6 16 3-8h4",
  chip: "M7 7h10v10H7V7ZM10 10h4v4h-4v-4ZM9 3v4m6-4v4M9 17v4m6-4v4M3 9h4m-4 6h4m10-6h4m-4 6h4",
  play: "m8 4 13 8-13 8V4Z",
  shield: "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Zm-4 9 3 3 5-6",
  link: "m9 15 6-6M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 10a4 4 0 0 0 6 0l4-4a4 4 0 0 0-6-6l-1 1",
  power: "M12 2v10M6 5a9 9 0 1 0 12 0",
  display: "M2 19 8 5l6 14M4 14h8m3-3h7m-3.5 0v8",
};

export default function Icon({
  name,
  size = 20,
  style,
}: {
  name: IconName;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function FalconMark() {
  return (
    <svg
      className="falcon-mark"
      aria-hidden="true"
      viewBox="0 0 48 48"
      fill="none"
    >
      <path
        d="M6 8c10 4 18 9 23 15l11-4-5 8 7 9-15-5-8 11 1-17C14 20 9 14 6 8Z"
        fill="currentColor"
      />
      <path
        d="m22 18 12-7-4 10"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="m29 24 5 1"
        stroke="#f9f8f4"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
