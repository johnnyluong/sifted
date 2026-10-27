import { afterEach, describe, expect, it, vi } from "vitest";
import { canReadClipboard, readClipboard } from "@/lib/clipboard";

function stubClipboard(clipboard: unknown): void {
  vi.stubGlobal("navigator", { ...navigator, clipboard });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readClipboard", () => {
  it("returns the clipboard's text", async () => {
    stubClipboard({ readText: () => Promise.resolve("https://www.instagram.com/reel/ABC/") });
    expect(canReadClipboard()).toBe(true);
    await expect(readClipboard()).resolves.toBe("https://www.instagram.com/reel/ABC/");
  });

  it("falls back to null when the API is missing, refused or empty", async () => {
    stubClipboard(undefined);
    expect(canReadClipboard()).toBe(false);
    await expect(readClipboard()).resolves.toBeNull();

    stubClipboard({ readText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) });
    await expect(readClipboard()).resolves.toBeNull();

    stubClipboard({ readText: () => Promise.resolve("   ") });
    await expect(readClipboard()).resolves.toBeNull();
  });
});
