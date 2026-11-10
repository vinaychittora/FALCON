export type DisplayPreferences = {
  theme: "dark" | "light" | "system";
  textSize: "standard" | "large" | "extra-large";
  contrast: "standard" | "high";
  /** Where the page links sit: a side column (default) or a bar along the top. */
  navigation: "side" | "top";
};

export const DISPLAY_STORAGE_KEY = "falcon.display-preferences.v1";
export const DEFAULT_DISPLAY: DisplayPreferences = {
  theme: "dark",
  textSize: "standard",
  contrast: "standard",
  navigation: "side",
};

export function parseDisplayPreferences(
  raw: string | null,
): DisplayPreferences {
  try {
    const value: unknown = JSON.parse(raw ?? "null");
    if (!value || typeof value !== "object") return { ...DEFAULT_DISPLAY };
    const candidate = value as Record<string, unknown>;
    return {
      theme:
        candidate.theme === "light" || candidate.theme === "system"
          ? candidate.theme
          : "dark",
      textSize:
        candidate.textSize === "large" || candidate.textSize === "extra-large"
          ? candidate.textSize
          : "standard",
      contrast: candidate.contrast === "high" ? "high" : "standard",
      navigation: candidate.navigation === "top" ? "top" : "side",
    };
  } catch {
    return { ...DEFAULT_DISPLAY };
  }
}

export function readDisplayPreferences(): DisplayPreferences {
  try {
    return parseDisplayPreferences(localStorage.getItem(DISPLAY_STORAGE_KEY));
  } catch {
    return { ...DEFAULT_DISPLAY };
  }
}

export function saveDisplayPreferences(value: DisplayPreferences): boolean {
  try {
    localStorage.setItem(DISPLAY_STORAGE_KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function resolvedTheme(value: DisplayPreferences, systemDark: boolean) {
  return value.theme === "system"
    ? systemDark
      ? "dark"
      : "light"
    : value.theme;
}

export function applyDisplayPreferences(value: DisplayPreferences) {
  const systemDark =
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  const theme = resolvedTheme(value, systemDark);
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.textSize = value.textSize;
  document.documentElement.dataset.contrast = value.contrast;
  document.documentElement.dataset.nav = value.navigation;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#14191e" : "#f5f7f9");
}
