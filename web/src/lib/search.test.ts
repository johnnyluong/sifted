import { describe, expect, it } from "vitest";
import { parseDigestSearch, parseId, parseLibrarySearch } from "@/lib/search";

describe("parseLibrarySearch", () => {
  it("keeps valid filters", () => {
    expect(parseLibrarySearch({ q: "tacos", goal: 3, type: "place", topic: 7, label: "date night" })).toEqual({
      q: "tacos",
      goal: 3,
      type: "place",
      topic: 7,
      label: "date night",
    });
  });

  it("drops what a stale or hand-edited URL can hold", () => {
    expect(parseLibrarySearch({ q: "  ", goal: "3", type: "restaurant" })).toEqual({});
    expect(parseLibrarySearch({ goal: 2.5 })).toEqual({});
    expect(parseLibrarySearch({ goal: -1 })).toEqual({});
    expect(parseLibrarySearch({ topic: "7", label: " " })).toEqual({});
    expect(parseLibrarySearch({ topic: 0, label: 4 })).toEqual({});
  });
});

describe("parseDigestSearch", () => {
  it("keeps a topic id and drops anything else", () => {
    expect(parseDigestSearch({ topic: 7 })).toEqual({ topic: 7 });
    for (const bad of ["7", 0, -2, 1.5, null])
      expect(parseDigestSearch({ topic: bad }).topic, String(bad)).toBeUndefined();
  });
});

describe("parseId", () => {
  it("accepts positive integers and turns anything else into not-found", () => {
    expect(parseId("12")).toBe(12);
    for (const bad of ["0", "-1", "1.5", "12x", "", "NaN", "012"]) {
      expect(() => parseId(bad), bad).toThrow();
    }
  });
});
