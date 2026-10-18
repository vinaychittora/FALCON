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
  | "display"
  | "rain"
  | "check"
  | "trash"
  | "edit"
  | "question"
  | "stop"
  | "plus"
  | "node"
  | "filter"
  | "wifi"
  | "thermometer"
  | "grid"
  | "list"
  | "keyboard"
  | "chevron"
  | "external"
  | "focus"
  | "pause"
  | "menu"
  | "map";
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
  rain: "M7 15a4 4 0 1 1 .9-7.9A6 6 0 0 1 19 9a3 3 0 0 1 0 6H7M8 18l-1 3M12 18l-1 3M16 18l-1 3",
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
  check: "m4 12 5 5L20 6",
  trash: "M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v6m4-6v6",
  edit: "M4 20h4L19 9l-4-4L4 16v4Zm9-13 4 4",
  question:
    "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4.5M12 18h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  stop: "M6 6h12v12H6z",
  plus: "M12 5v14M5 12h14",
  node: "M12 21v-8m0 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM7.8 15.2a6 6 0 0 1 0-8.4m8.4 8.4a6 6 0 0 0 0-8.4M5 18a10 10 0 0 1 0-14m14 14a10 10 0 0 0 0-14",
  filter: "M3 5h18l-7 8v6l-4 2v-8L3 5Z",
  wifi: "M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01",
  thermometer: "M14 14.8V4a2 2 0 1 0-4 0v10.8a4 4 0 1 0 4 0ZM12 9v7",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  keyboard: "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10",
  chevron: "m9 6 6 6-6 6",
  external: "M14 4h6v6m0-6-9 9M18 14v6H4V6h6",
  focus: "M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5M12 12h.01",
  pause: "M8 5v14m8-14v14",
  menu: "M4 6h16M4 12h16M4 18h16",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Zm0 0v14m6-12v14",
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
