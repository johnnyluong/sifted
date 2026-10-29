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
    await expect(readClipboard()).resolves.toEqual({ text: "https://www.instagram.com/reel/ABC/", files: [] });
  });

  it("returns a copied screenshot as an image file, and the text that came with it", async () => {
    const items = [
      { types: ["image/png"], getType: () => Promise.resolve(new Blob(["png"], { type: "image/png" })) },
      { types: ["text/uri-list"], getType: () => Promise.resolve(new Blob(["https://cdn.example/a.png"])) },
    ];
    stubClipboard({ read: () => Promise.resolve(items), readText: () => Promise.reject(new Error("second read")) });
    expect(canReadClipboard()).toBe(true);
    const clip = await readClipboard();
    expect(clip?.text).toBe("https://cdn.example/a.png");
    expect(clip?.files.map((f) => [f.name, f.type])).toEqual([["pasted-1.png", "image/png"]]);
  });

  it("reads the first image type Sift takes, and a link beside an image that cannot be read", async () => {
    const png = new Blob(["png"], { type: "image/png" });
    stubClipboard({
      read: () =>
        Promise.resolve([
          {
            types: ["image/svg+xml", "image/png"],
            getType: (type: string) => Promise.resolve(type === "image/png" ? png : new Blob()),
          },
          { types: ["text/plain"], getType: () => Promise.resolve(new Blob([" "])) },
          {
            types: ["image/png", "text/uri-list", "text/plain"],
            getType: (type: string) =>
              type === "text/plain"
                ? Promise.resolve(new Blob(["https://www.threads.com/@a/post/B"]))
                : type === "text/uri-list"
                  ? Promise.resolve(new Blob(["https://cdn.example/b.png"]))
                  : Promise.reject(new DOMException("gone", "NotFoundError")),
          },
        ]),
    });
    const clip = await readClipboard();
    expect(clip?.files.map((f) => f.type)).toEqual(["image/png"]);
    expect(clip?.text).toBe("https://www.threads.com/@a/post/B");
  });

  it("returns null when an image cannot be read", async () => {
    const items = [{ types: ["image/png"], getType: () => Promise.reject(new DOMException("gone", "NotFoundError")) }];
    stubClipboard({ read: () => Promise.resolve(items) });
    await expect(readClipboard()).resolves.toBeNull();
  });

  it("falls back to null when the API is missing, refused or empty", async () => {
    stubClipboard(undefined);
    expect(canReadClipboard()).toBe(false);
    await expect(readClipboard()).resolves.toBeNull();

    stubClipboard({ readText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) });
    await expect(readClipboard()).resolves.toBeNull();

    stubClipboard({ readText: () => Promise.resolve("   ") });
    await expect(readClipboard()).resolves.toBeNull();

    stubClipboard({
      read: () => Promise.resolve([{ types: ["text/html"], getType: () => Promise.resolve(new Blob()) }]),
    });
    await expect(readClipboard()).resolves.toBeNull();
  });
});
