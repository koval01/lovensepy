import { useCallback, useSyncExternalStore } from "react";

export type Theme = "dark" | "light" | "system";

const STORAGE_KEY = "lovensepy.theme";

function readStored(): Theme {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (value === "dark" || value === "light" || value === "system") return value;
  } catch {
    // Private mode in Safari can throw on localStorage access.
  }
  return "system";
}

const media = window.matchMedia?.("(prefers-color-scheme: dark)");

let current: Theme = readStored();
const listeners = new Set<() => void>();

function systemPrefersDark() {
  return media ? media.matches : true;
}

function resolve(theme: Theme): "dark" | "light" {
  if (theme === "system") return systemPrefersDark() ? "dark" : "light";
  return theme;
}

function syncThemeColor(resolved: "dark" | "light") {
  const color = resolved === "dark" ? "#000000" : "#ffffff";
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    meta.setAttribute("content", color);
  }
}

function apply() {
  const resolved = resolve(current);
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  syncThemeColor(resolved);
}

function emit() {
  apply();
  for (const listener of listeners) listener();
}

// Follow the OS while in "system" mode. `addEventListener` on MediaQueryList is
// unsupported on Safari < 14, which still needs the deprecated addListener.
if (media) {
  const onChange = () => {
    if (current === "system") emit();
  };
  if (typeof media.addEventListener === "function") media.addEventListener("change", onChange);
  else media.addListener?.(onChange);
}

apply();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme() {
  const theme = useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );

  const setTheme = useCallback((next: Theme) => {
    current = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore: theme preference is a nicety, not state we must persist.
    }
    emit();
  }, []);

  return { theme, setTheme, resolved: resolve(theme) } as const;
}
