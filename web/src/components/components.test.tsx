import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Card } from "@/api";
import { CardBody } from "@/components/card-body";
import { hasLink, isEditable } from "@/components/paste-box";
import { railMark, tetherSpan, verdict } from "@/components/score-rail";
import { canDrop, type DropTarget, restoredTopic, SIFTS_PICK } from "@/components/shelf";
import { stageSteps } from "@/components/stage-track";
import { Thumb } from "@/components/thumb";
import { SHELVES } from "@/lib/nav";
import { primaryAction } from "@/lib/vocabulary";
import { item } from "@/test/fixtures";

const [, keptShelf, archivedShelf] = SHELVES;

describe("railMark", () => {
  it("puts the mark at the score and colors it by status", () => {
    expect(railMark(item({ relevance_score: 72 }))).toEqual({ at: 72, tone: "kept", overruled: false });
    expect(railMark(item({ status: "done" }))?.tone).toBe("done");
    expect(railMark(item({ status: "archived" }))?.tone).toBe("archived");
  });

  it("flags an override that crosses the line, so it reads as being on the wrong side", () => {
    const keptAnyway = item({ relevance_score: 41, threshold_decision: "archive", user_override: "keep" });
    expect(railMark(keptAnyway)).toEqual({ at: 41, tone: "kept", overruled: true });
    const agreed = item({ threshold_decision: "keep", user_override: "keep" });
    expect(railMark(agreed)?.overruled).toBe(false);
  });

  it("draws nothing before scoring", () => {
    expect(railMark(item({ relevance_score: null }))).toBeNull();
  });
});

describe("the override tether", () => {
  it("runs from the mark across the line toward the user's call", () => {
    expect(tetherSpan(41, 60, "keep")).toEqual({ left: 41, width: 27 });
    expect(tetherSpan(80, 60, "archive")).toEqual({ left: 52, width: 28 });
    expect(tetherSpan(98, 96, "keep")).toEqual({ left: 98, width: 2 });
  });
});

describe("verdict", () => {
  it("names the filter's call from the stored decision, and the user's call when it differs", () => {
    expect(verdict(item({ relevance_score: 72, threshold_decision: "keep" }), 60)).toBe("Above your line of 60");
    expect(verdict(item({ relevance_score: 72, threshold_decision: "archive", status: "archived" }), 80)).toBe(
      "Below your line of 80",
    );
    const keptAnyway = item({ relevance_score: 41, threshold_decision: "archive", user_override: "keep" });
    expect(verdict(keptAnyway, 60)).toBe("You kept this; the filter said archive.");
  });
});

describe("canDrop", () => {
  const shelf = (s: (typeof SHELVES)[number] | undefined): DropTarget => {
    if (!s) throw new Error("no shelf");
    return { kind: "shelf", shelf: s };
  };
  const topic = (id: number): DropTarget => ({ kind: "topic", topic: { id, name: `Topic ${id}` } });

  it("lets a shelf take a row only when the server allows its action", () => {
    const kept = item({ actions: ["archive", "done", "reprocess"] });
    expect(canDrop(kept, shelf(keptShelf))).toBe(false);
    expect(canDrop(kept, shelf(archivedShelf))).toBe(true);
  });

  it("lets a topic take an organized post from another topic or from none", () => {
    expect(canDrop(item({ topic: { id: 1, name: "NYC restaurants" } }), topic(3))).toBe(true);
    expect(canDrop(item({ topic: null }), topic(3))).toBe(true);
  });

  it("turns a topic away for a post not organized yet, or one already in it", () => {
    expect(canDrop(item({ gist: null, topic: null }), topic(3))).toBe(false);
    expect(canDrop(item({ topic: { id: 3, name: "Topic 3" } }), topic(3))).toBe(false);
  });

  it("judges each kind of target by its own rule", () => {
    const unorganized = item({ gist: null, topic: null, actions: ["archive"] });
    expect(canDrop(unorganized, shelf(archivedShelf))).toBe(true);
    expect(canDrop(unorganized, topic(3))).toBe(false);
    const noActions = item({ actions: [] });
    expect(canDrop(noActions, shelf(archivedShelf))).toBe(false);
    expect(canDrop(noActions, topic(3))).toBe(true);
  });
});

describe("restoredTopic", () => {
  it("returns a post to Sift's pick when that is where it was", () => {
    expect(restoredTopic({ id: 1, name: "A" }, { sift_topic: { id: 1, name: "A" } })).toBe(SIFTS_PICK);
    expect(restoredTopic(null, { sift_topic: null })).toBe(SIFTS_PICK);
  });

  it("returns a post to the topic the user had chosen", () => {
    expect(restoredTopic({ id: 5, name: "B" }, { sift_topic: { id: 1, name: "A" } })).toBe(5);
  });
});

describe("primaryAction", () => {
  it("fills the button the item is waiting for", () => {
    expect(primaryAction(item({ status: "failed", actions: ["retry"] }))).toBe("retry");
    expect(primaryAction(item({ status: "archived", actions: ["keep", "done", "reprocess"] }))).toBe("keep");
    expect(primaryAction(item({ status: "kept", actions: ["archive", "done", "reprocess"] }))).toBe("done");
    expect(primaryAction(item({ status: "done", actions: ["undone", "reprocess"] }))).toBeUndefined();
  });
});

describe("paste anywhere", () => {
  it("submits only clipboard text holding a URL", () => {
    expect(hasLink("look https://www.instagram.com/reel/ABC/?igsh=1")).toBe(true);
    expect(hasLink("dinner at 8?")).toBe(false);
  });

  it("leaves a paste into a field to the field", () => {
    document.body.innerHTML = `<input id="a"><textarea id="b"></textarea><div id="c" contenteditable="true"><span id="d"></span></div><p id="e"></p>`;
    for (const id of ["a", "b", "c", "d"]) expect(isEditable(document.getElementById(id)), id).toBe(true);
    expect(isEditable(document.getElementById("e"))).toBe(false);
    expect(isEditable(null)).toBe(false);
  });
});

describe("stageSteps", () => {
  const states = (overrides: Parameters<typeof item>[0]) => stageSteps(item(overrides)).map((s) => s.state);

  it("reads Transcribing as step 2 running", () => {
    expect(states({ status: "fetching", stage: "media", in_motion: true })).toEqual(["done", "active", "todo", "todo"]);
  });

  it("shows a stage blocked outside the app as waiting, and a queued one as next", () => {
    expect(states({ status: "queued", stage: "extract", in_motion: false })).toEqual([
      "done",
      "done",
      "waiting",
      "todo",
    ]);
    expect(states({ status: "queued", stage: "fetch", in_motion: true })).toEqual(["queued", "todo", "todo", "todo"]);
  });

  it("marks the stage that failed", () => {
    expect(states({ status: "failed", stage: "fetch", in_motion: false })).toEqual(["failed", "todo", "todo", "todo"]);
  });

  it("is all done once scored", () => {
    expect(states({ status: "kept", stage: null })).toEqual(["done", "done", "done", "done"]);
  });
});

const base = { title: "T", summary: "S", next_action: null };

describe("CardBody", () => {
  it("renders a place with its facts and a maps link", () => {
    const card: Card = {
      ...base,
      item_type: "place",
      details: {
        name: "Los Tacos No. 1",
        kind: "Taqueria",
        neighborhood: "Chelsea",
        city: "New York",
        address: null,
        why_notable: null,
        what_to_order_or_do: ["Adobada"],
        price_hint: null,
        maps_query: "Los Tacos No. 1, New York",
      },
    };
    render(<CardBody card={card} />);
    expect(screen.getByText("Chelsea, New York")).toBeTruthy();
    expect(screen.queryByText("Address")).toBeNull();
    expect(screen.getByRole("link", { name: /Open in Maps/ }).getAttribute("href")).toBe(
      "https://www.google.com/maps/search/?api=1&query=Los%20Tacos%20No.%201%2C%20New%20York",
    );
  });

  it("renders a recipe's amounts and numbered steps", () => {
    const card: Card = {
      ...base,
      item_type: "recipe",
      details: {
        dish: "Rigatoni",
        ingredients: [{ name: "Vodka", amount: "2 tbsp" }],
        steps: ["Boil", "Stir"],
        total_time: "25 min",
        notes: [],
      },
    };
    render(<CardBody card={card} />);
    expect(screen.getByText("2 tbsp")).toBeTruthy();
    expect(screen.getByText("2").nextSibling?.textContent).toBe("Stir");
  });

  it("links a product only over http(s)", () => {
    const product = (link: string): Card => ({
      ...base,
      item_type: "product",
      details: { name: "Pan", what_it_is: "A pan", price: null, link },
    });
    const { unmount } = render(<CardBody card={product("javascript:alert(1)")} />);
    expect(screen.queryByRole("link")).toBeNull();
    unmount();
    render(<CardBody card={product("https://example.com/pan")} />);
    expect(screen.getByRole("link", { name: /Open link/ }).getAttribute("href")).toBe("https://example.com/pan");
  });
});

describe("Thumb", () => {
  it("shows the image when there is one, and the placeholder at the same size when not", () => {
    const { container, rerender } = render(<Thumb url="/api/items/1/thumbnail" size={28} placeholder="IG" />);
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/api/items/1/thumbnail");
    expect(img?.className).toContain("size-7");
    expect(screen.queryByText("IG")).toBeNull();

    rerender(<Thumb url={null} size={28} placeholder="IG" />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("IG").className).toContain("size-7");
  });
});
