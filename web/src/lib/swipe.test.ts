import { describe, expect, it } from "vitest";
import { commitDistance, lockAxis, swipeActions, swipeOffset, swipeResult } from "@/lib/swipe";

describe("swipeActions", () => {
  it("offers the server's allowed actions on each side", () => {
    expect(swipeActions({ actions: ["archive", "done", "reprocess"] })).toEqual({
      right: "done",
      left: "archive",
    });
    expect(swipeActions({ actions: ["keep", "done", "reprocess"] })).toEqual({ right: "keep", left: undefined });
    expect(swipeActions({ actions: ["archive", "retry"] })).toEqual({ right: undefined, left: "archive" });
    expect(swipeActions({ actions: ["reprocess"] })).toEqual({ right: undefined, left: undefined });
  });
});

describe("lockAxis", () => {
  it("waits for the slop, then follows the larger movement", () => {
    expect(lockAxis(5, 3)).toBeNull();
    expect(lockAxis(12, 4)).toBe("x");
    expect(lockAxis(-12, 4)).toBe("x");
    expect(lockAxis(6, 10)).toBe("y");
  });
});

describe("swipeResult", () => {
  const actions = { right: "keep", left: "archive" } as const;
  const width = 358;
  const commit = commitDistance(width);

  it("commits only past the distance, to the side's action", () => {
    expect(swipeResult(commit - 1, width, actions)).toBeNull();
    expect(swipeResult(commit, width, actions)).toBe("keep");
    expect(swipeResult(-commit, width, actions)).toBe("archive");
  });

  it("never commits a side without an action", () => {
    expect(swipeResult(-width, width, { right: "keep" })).toBeNull();
  });

  it("scales with the row but stays reachable on narrow and wide rows", () => {
    expect(commitDistance(200)).toBe(80);
    expect(commitDistance(358)).toBeCloseTo(107.4);
    expect(commitDistance(900)).toBe(140);
  });
});

describe("swipeOffset", () => {
  it("follows the finger toward an action and resists toward none", () => {
    expect(swipeOffset(60, 358, { right: "keep" })).toBe(60);
    expect(swipeOffset(-60, 358, { right: "keep" })).toBe(-15);
    expect(swipeOffset(-400, 358, { right: "keep" })).toBe(-24);
    expect(swipeOffset(500, 358, { right: "keep" })).toBe(358);
  });
});
