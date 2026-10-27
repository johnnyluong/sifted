import { describe, expect, it } from "vitest";
import { keyboardInset } from "@/lib/viewport";

describe("keyboardInset", () => {
  it("is the layout height the visual viewport no longer covers", () => {
    expect(keyboardInset(844, { height: 844, offsetTop: 0 })).toBe(0);
    expect(keyboardInset(844, { height: 508, offsetTop: 0 })).toBe(336);
    expect(keyboardInset(844, { height: 508, offsetTop: 120 })).toBe(216);
  });

  it("is zero when the visual viewport overshoots", () => {
    expect(keyboardInset(844, { height: 900, offsetTop: 0 })).toBe(0);
  });
});
