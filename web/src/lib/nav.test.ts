import { describe, expect, it } from "vitest";
import { inMore, sidebarTopics } from "@/lib/nav";
import { topicSummary } from "@/test/fixtures";

describe("inMore", () => {
  it("lights More for its destinations and their pages, not for dock tabs or look-alikes", () => {
    expect(inMore("/archived")).toBe(true);
    expect(inMore("/goals")).toBe(true);
    expect(inMore("/import")).toBe(true);
    expect(inMore("/share")).toBe(true);
    expect(inMore("/topics")).toBe(true);
    expect(inMore("/topics/3")).toBe(true);
    expect(inMore("/roadmap")).toBe(true);
    expect(inMore("/digests")).toBe(false);
    expect(inMore("/inbox")).toBe(false);
    expect(inMore("/items/4")).toBe(false);
    expect(inMore("/importer")).toBe(false);
  });
});

describe("sidebarTopics", () => {
  it("lists every goal's topics with kept posts in one run, most kept first, then by name", () => {
    const groups = [
      { goal: { id: 1, title: "Food" }, topics: [topicSummary({ id: 1, name: "Pizza", kept: 2 })] },
      {
        goal: null,
        topics: [
          topicSummary({ id: 2, name: "Bars", kept: 2 }),
          topicSummary({ id: 3, name: "Hikes", kept: 5 }),
          topicSummary({ id: 4, name: "Empty", kept: 0 }),
        ],
      },
    ];
    expect(sidebarTopics({ groups }).map((t) => t.name)).toEqual(["Hikes", "Bars", "Pizza"]);
  });
});
