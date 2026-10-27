import { useSyncExternalStore } from "react";

export type Theme = "system" | "light" | "dark";

const KEY = "sift-theme";
export const THEMES: readonly Theme[] = ["system", "light", "dark"];

function storedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return THEMES.find((t) => t === value) ?? "system";
  } catch {
    return "system";
  }
}

let current = storedTheme();
const listeners = new Set<() => void>();

function panIn(root: HTMLElement, scheme: "light" | "dark"): string {
  root.dataset.theme = scheme;
  return getComputedStyle(root).getPropertyValue("--pan").trim();
}

// The bars take --pan from styles.css. Under System each meta keeps its media query, so the browser follows the scheme.
function paint(theme: Theme): void {
  const root = document.documentElement;
  const bars = { light: panIn(root, "light"), dark: panIn(root, "dark") };
  if (theme === "system") root.removeAttribute("data-theme");
  else root.dataset.theme = theme;
  for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
    const scheme = theme === "system" ? (meta.getAttribute("media")?.includes("dark") ? "dark" : "light") : theme;
    meta.content = bars[scheme];
  }
}

function notify(): void {
  for (const listener of listeners) listener();
}

// Another tab, or the installed app, wrote the choice.
function onStorage(event: StorageEvent): void {
  if (event.key !== KEY && event.key !== null) return;
  current = storedTheme();
  paint(current);
  notify();
}

export function applyStoredTheme(): void {
  paint(current);
  window.addEventListener("storage", onStorage);
}

export function setTheme(theme: Theme): void {
  current = theme;
  paint(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {}
  notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, () => current);
}
