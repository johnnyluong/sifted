import { describe, expect, it } from "vitest";
import { keyByText } from "@/lib/keys";

const keys = (texts: string[]) => keyByText(texts, (t) => t).map((k) => k.key);

describe("keyByText", () => {
  it("gives repeated text distinct keys", () => {
    expect(new Set(keys(["a", "a", "b", "a"])).size).toBe(4);
  });

  it("never collides when a text looks like a generated key", () => {
    expect(new Set(keys(["x", "x", "2:x"])).size).toBe(3);
  });

  it("changes a row's key when its text is rewritten", () => {
    expect(keys(["old", "same"])[0]).not.toBe(keys(["new", "same"])[0]);
    expect(keys(["old", "same"])[1]).toBe(keys(["new", "same"])[1]);
  });
});
