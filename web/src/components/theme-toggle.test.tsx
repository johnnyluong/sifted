import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type ThemeModules = { theme: typeof import("@/lib/theme"); toggle: typeof import("@/components/theme-toggle") };

// Not the index.html colors, so a match proves the bars came from the stylesheet.
const LIGHT = "#eeeff2";
const DARK = "#111215";

let modules: ThemeModules;
let head = "";

beforeEach(async () => {
  head = document.head.innerHTML;
  localStorage.clear();
  vi.resetModules();
  modules = { theme: await import("@/lib/theme"), toggle: await import("@/components/theme-toggle") };
  document.head.innerHTML = `
    <style>:root { --pan: ${LIGHT}; } :root[data-theme="dark"] { --pan: ${DARK}; }</style>
    <meta name="theme-color" content="#f3f4f6" media="(prefers-color-scheme: light)" />
    <meta name="theme-color" content="#0c0d10" media="(prefers-color-scheme: dark)" />`;
});

afterEach(() => {
  document.head.innerHTML = head;
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

const bars = () => [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')].map((m) => m.content);

describe("the theme toggles", () => {
  it("share one theme, and the browser bar color follows a manual choice", async () => {
    const { ThemeToggle } = modules.toggle;
    render(
      <>
        <ThemeToggle />
        <ThemeToggle />
      </>,
    );
    const [sidebar, sheet] = screen.getAllByRole("button");
    if (!sidebar || !sheet) throw new Error("expected two toggles");

    await userEvent.click(sidebar);
    expect(sheet.textContent).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(bars()).toEqual([LIGHT, LIGHT]);

    await userEvent.click(sheet);
    expect(sidebar.textContent).toBe("dark");
    expect(bars()).toEqual([DARK, DARK]);

    await userEvent.click(sidebar);
    expect(sheet.textContent).toBe("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(bars()).toEqual([LIGHT, DARK]);
  });

  it("follows a choice made in another tab", () => {
    modules.theme.applyStoredTheme();
    render(<modules.toggle.ThemeToggle />);
    expect(screen.getByRole("button").textContent).toBe("system");

    localStorage.setItem("sift-theme", "dark");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "sift-theme", newValue: "dark" })));
    expect(screen.getByRole("button").textContent).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(bars()).toEqual([DARK, DARK]);

    localStorage.clear();
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: null })));
    expect(screen.getByRole("button").textContent).toBe("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});
