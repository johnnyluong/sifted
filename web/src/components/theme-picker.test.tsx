import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type ThemeModules = { theme: typeof import("@/lib/theme"); picker: typeof import("@/components/theme-picker") };

const STYLESHEET_LIGHT = "#eeeff2";
const STYLESHEET_DARK = "#111215";
const FIRST_PAINT_LIGHT = "#f3f4f6";
const FIRST_PAINT_DARK = "#0c0d10";

let modules: ThemeModules;
let head = "";

beforeEach(async () => {
  head = document.head.innerHTML;
  localStorage.clear();
  vi.resetModules();
  modules = { theme: await import("@/lib/theme"), picker: await import("@/components/theme-picker") };
  document.head.innerHTML = `
    <style>:root { --pan: ${STYLESHEET_LIGHT}; } :root[data-theme="dark"] { --pan: ${STYLESHEET_DARK}; }</style>
    <meta name="theme-color" content="${FIRST_PAINT_LIGHT}" media="(prefers-color-scheme: light)" />
    <meta name="theme-color" content="${FIRST_PAINT_DARK}" media="(prefers-color-scheme: dark)" />`;
});

afterEach(() => {
  document.head.innerHTML = head;
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

const bars = () => [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')].map((m) => m.content);

const picked = (picker: HTMLElement) =>
  within(picker)
    .getAllByRole<HTMLInputElement>("radio")
    .filter((r) => r.checked)
    .map((r) => r.labels?.[0]?.textContent);

describe("the theme pickers", () => {
  it("share one theme, and the browser bar color follows a manual choice", async () => {
    const { ThemePicker } = modules.picker;
    render(
      <>
        <ThemePicker />
        <ThemePicker />
      </>,
    );
    const [menu, sheet] = screen.getAllByRole("group", { name: "Theme" });
    if (!menu || !sheet) throw new Error("expected two pickers");
    expect(picked(sheet)).toEqual(["System"]);

    await userEvent.click(within(menu).getByRole("radio", { name: "Light" }));
    expect(picked(sheet)).toEqual(["Light"]);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(bars()).toEqual([STYLESHEET_LIGHT, STYLESHEET_LIGHT]);

    await userEvent.click(within(sheet).getByRole("radio", { name: "Dark" }));
    expect(picked(menu)).toEqual(["Dark"]);
    expect(bars()).toEqual([STYLESHEET_DARK, STYLESHEET_DARK]);

    await userEvent.click(within(menu).getByRole("radio", { name: "System" }));
    expect(picked(sheet)).toEqual(["System"]);
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(bars()).toEqual([STYLESHEET_LIGHT, STYLESHEET_DARK]);
  });

  it("follows a choice made in another tab", () => {
    modules.theme.applyStoredTheme();
    render(<modules.picker.ThemePicker />);
    const picker = screen.getByRole("group", { name: "Theme" });
    expect(picked(picker)).toEqual(["System"]);

    localStorage.setItem("sift-theme", "dark");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "sift-theme", newValue: "dark" })));
    expect(picked(picker)).toEqual(["Dark"]);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(bars()).toEqual([STYLESHEET_DARK, STYLESHEET_DARK]);

    localStorage.clear();
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: null })));
    expect(picked(picker)).toEqual(["System"]);
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});
