import { useCallback, useEffect, useState, type RefObject } from "react";

type FullscreenDocument = Pick<
  Document,
  "fullscreenElement" | "exitFullscreen"
>;

/** Enter full screen on `element`, or leave it if it is already full screen. */
export async function toggleFullscreen(
  element: HTMLElement | null,
  doc: FullscreenDocument = document,
): Promise<void> {
  if (doc.fullscreenElement) {
    await doc.exitFullscreen();
    return;
  }
  if (element?.requestFullscreen) await element.requestFullscreen();
}

/** True when a key press should not trigger page shortcuts (the user is typing). */
export function typingTarget(target: EventTarget | null): boolean {
  const element = target as Partial<HTMLElement> | null;
  if (!element || typeof element.tagName !== "string") return false;
  return (
    Boolean(element.isContentEditable) ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName)
  );
}

/**
 * Full screen for one element, with the F key as a shortcut.
 * Esc leaves full screen through the browser itself.
 */
export function useFullscreen(ref: RefObject<HTMLElement | null>) {
  const [active, setActive] = useState(false);
  const toggle = useCallback(() => {
    toggleFullscreen(ref.current).catch(() => undefined);
  }, [ref]);
  useEffect(() => {
    const onChange = () =>
      setActive(
        Boolean(ref.current) && document.fullscreenElement === ref.current,
      );
    const onKey = (event: KeyboardEvent) => {
      if (
        (event.key === "f" || event.key === "F") &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !typingTarget(event.target)
      ) {
        event.preventDefault();
        toggle();
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, toggle]);
  const supported =
    typeof document !== "undefined" &&
    Boolean(document.fullscreenEnabled ?? true);
  return { active, toggle, supported };
}
