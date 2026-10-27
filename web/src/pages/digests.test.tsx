import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { describe, expect, it } from "vitest";
import { createQueryClient, type Digest, type DigestPick, type DigestsView, type Item } from "@/api";
import { route } from "@/test/fake-api";
import { detail, item, status } from "@/test/fixtures";
import { createAppRouter } from "../router";

function post(id: number, overrides: Partial<Item> = {}): Item {
  const title = overrides.title ?? `Post ${id}`;
  return item({ id, title, display_title: title, thumbnail_url: `/api/items/${id}/thumbnail`, ...overrides });
}

function pick(it: Item, refill = false): DigestPick {
  return { item: it, why: `Why ${it.id}`, next_action: `Next ${it.id}`, refill };
}

function digest(overrides: Partial<Digest> = {}): Digest {
  return {
    id: 7,
    period_start: "2026-10-18T22:00:00Z",
    period_end: "2026-10-25T22:00:00Z",
    created_at: "2026-10-25T22:00:00Z",
    model: "fake",
    sent_at: null,
    opening: "A week for tacos.",
    top: [pick(post(1)), pick(post(2)), pick(post(3))],
    done: [],
    groups: [{ kind: "goal", heading: "Cook more", lines: [{ item: post(4), line: "Line 4" }] }],
    item_ids: [1, 2, 3, 4],
    ...overrides,
  };
}

function renderDigests(view: () => DigestsView) {
  window.history.replaceState(null, "", "/digests");
  route("GET /api/status", () => status({ revision: "r1" }));
  route("GET /api/digests", view);
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="always">
        <RouterProvider router={createAppRouter(queryClient)} />
      </MotionConfig>
    </QueryClientProvider>,
  );
}

function topTitles(): string[] {
  const list = screen.getByRole("region", { name: "To act on this week" });
  return within(list)
    .getAllByRole("listitem")
    .map((li) => within(li).getAllByRole("link")[0]?.textContent ?? "");
}

function doneList(): HTMLElement {
  return screen.getByRole("heading", { name: "Done" }).nextElementSibling as HTMLElement;
}

describe("digest", () => {
  it("shows each pick's rank, why and next action, and the refill's label", async () => {
    renderDigests(() => ({
      latest: digest({ top: [pick(post(2)), pick(post(3)), pick(post(4), true)] }),
      earlier: [],
    }));
    await screen.findByText("A week for tacos.");
    expect(topTitles()).toEqual(["Post 2", "Post 3", "Post 4"]);
    const third = within(screen.getByRole("region", { name: "To act on this week" })).getAllByRole("listitem")[2];
    if (!third) throw new Error("no third pick");
    expect(within(third).getByText("3")).toBeTruthy();
    expect(within(third).getByText("Why 4")).toBeTruthy();
    expect(third.textContent).toContain("Next: Next 4");
    expect(within(third).getByText("Moved up")).toBeTruthy();
    expect(screen.getAllByText("Moved up")).toHaveLength(1);
  });

  it("marks a pick done and shows the next one in its place", async () => {
    let done = false;
    const actions: string[] = [];
    route("POST /api/items/1/actions/done", () => {
      actions.push("done");
      done = true;
      return detail({ id: 1, status: "done", actions: ["undone", "reprocess"] });
    });
    renderDigests(() => ({
      latest: done
        ? digest({
            top: [pick(post(2)), pick(post(3)), pick(post(4), true)],
            done: [pick(post(1, { status: "done", actions: ["undone"] }))],
            groups: [],
          })
        : digest(),
      earlier: [],
    }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Done: Post 1" }));
    await waitFor(() => expect(topTitles()).toEqual(["Post 2", "Post 3", "Post 4"]));
    expect(actions).toEqual(["done"]);
    expect(within(doneList()).getByRole("button", { name: "Undo: Post 1" })).toBeTruthy();
  });

  it("lists a moved-up post marked done under Done, where Undo puts it back", async () => {
    let done = true;
    const actions: string[] = [];
    route("POST /api/items/4/actions/undone", () => {
      actions.push("undone");
      done = false;
      return detail({ id: 4, status: "kept", actions: ["done"] });
    });
    const one = pick(post(1, { status: "done", actions: ["undone"] }));
    renderDigests(() => ({
      latest: done
        ? digest({
            top: [pick(post(2)), pick(post(3)), pick(post(5), true)],
            done: [one, pick(post(4, { status: "done", actions: ["undone"] }), true)],
            groups: [],
          })
        : digest({ top: [pick(post(2)), pick(post(3)), pick(post(4), true)], done: [one], groups: [] }),
      earlier: [],
    }));
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Done" });
    await user.click(within(doneList()).getByRole("button", { name: "Undo: Post 4" }));
    await waitFor(() => expect(topTitles()).toEqual(["Post 2", "Post 3", "Post 4"]));
    expect(actions).toEqual(["undone"]);
    expect(within(doneList()).queryByRole("button", { name: "Undo: Post 4" })).toBeNull();
  });

  it("never turns digest text into links or images", async () => {
    const hostile =
      "![x](https://evil.example/p.png) [y](https://evil.example) <img src=https://evil.example/i.png> <a href=https://evil.example>z</a>";
    const evil = post(1, { title: hostile, url: "https://www.instagram.com/reel/ABC/" });
    renderDigests(() => ({
      latest: digest({
        opening: hostile,
        top: [{ item: evil, why: hostile, next_action: hostile, refill: false }],
        groups: [{ kind: "places", heading: hostile, lines: [{ item: post(5), line: hostile }] }],
      }),
      earlier: [],
    }));
    await screen.findAllByText(hostile, { exact: false });
    const main = document.body;
    for (const img of main.querySelectorAll("img"))
      expect(img.getAttribute("src")).toMatch(/^\/api\/items\/\d+\/thumbnail$/);
    for (const a of main.querySelectorAll("a[href]")) expect(a.getAttribute("href")).not.toContain("evil.example");
    expect(main.querySelectorAll("a[href^='/items/']").length).toBeGreaterThan(0);
  });
});
