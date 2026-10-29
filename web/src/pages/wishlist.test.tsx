import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { toast } from "sonner";
import { afterEach, describe, expect, it } from "vitest";
import { type Card, createQueryClient, type Digest, type Item, type ItemDetail } from "@/api";
import { route } from "@/test/fake-api";
import { detail, item, status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const jacket = (overrides: Partial<Item> = {}): Item =>
  item({
    id: 1,
    title: "Packable rain jacket",
    display_title: "Packable rain jacket",
    item_type: "product",
    wishlist: true,
    wishlist_post: true,
    state_label: "On wishlist",
    threshold_decision: "archive",
    relevance_score: 30,
    product: { name: "Rain jacket", price: "$90", link: "https://shop.example/jacket" },
    ...overrides,
  });

function renderAt(url: string, rows: Item[] = [jacket()]): { views: (string | null)[] } {
  const views: (string | null)[] = [];
  window.history.replaceState(null, "", url);
  route("GET /api/status", () => status());
  route("GET /api/items", (request) => {
    views.push(new URL(request.url).searchParams.get("view"));
    return rows;
  });
  route("GET /api/goals", () => []);
  route("GET /api/imports", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="always">
        <RouterProvider router={createAppRouter(queryClient)} />
      </MotionConfig>
    </QueryClientProvider>,
  );
  return { views };
}

afterEach(() => {
  toast.dismiss();
});

let current: ItemDetail;

function renderItem(item: ItemDetail): void {
  current = item;
  route("GET /api/items/1", () => current);
  renderAt("/items/1");
}

describe("wishlist shelf", () => {
  it("lists each post's product name, price and link from the wishlist view", async () => {
    const { views } = renderAt("/wishlist", [
      jacket(),
      jacket({ id: 2, product: { name: "Desk lamp", price: null, link: "javascript:alert(1)" } }),
    ]);
    expect(await screen.findByRole("heading", { name: "Wishlist" })).toBeTruthy();
    expect(screen.getByText("Rain jacket")).toBeTruthy();
    expect(screen.getByText("$90")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the link for Rain jacket" }).getAttribute("href")).toBe(
      "https://shop.example/jacket",
    );
    expect(screen.getByText("Desk lamp")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open the link for Desk lamp" })).toBeNull();
    expect(views).toEqual(["wishlist"]);
  });

  it("asks Kept for the kept view, which leaves wishlist posts out", async () => {
    const { views } = renderAt("/kept", [item()]);
    await screen.findByRole("heading", { name: "Kept" });
    expect(views).toEqual(["kept"]);
  });

  it("counts the wishlist beside Kept in the sidebar and in the phone's More sheet", async () => {
    renderAt("/wishlist");
    const shelves = await screen.findAllByRole("navigation", { name: "Shelves" });
    const sidebar = shelves.map((nav) => within(nav).queryByRole("link", { name: /^Wishlist/ })).find(Boolean);
    expect(sidebar?.textContent).toBe("Wishlist3");
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    const more = await screen.findByRole("link", { name: /Things you want to buy/ });
    expect(more.textContent).toContain("3");
    expect(more.getAttribute("href")).toBe("/wishlist");
  });
});

describe("bought", () => {
  it("labels Done as Bought on a wishlist post and toasts Marked bought", async () => {
    renderItem(detail({ ...jacket(), actions: ["archive", "done", "reprocess"] }));
    route("POST /api/items/1/actions/done", () => detail({ ...jacket(), status: "done", actions: ["undone"] }));
    const [bought] = await screen.findAllByRole("button", { name: "Bought" });
    expect(screen.queryByRole("button", { name: "Mark done" })).toBeNull();
    if (!bought) throw new Error("no Bought button");
    await userEvent.click(bought);
    expect(await screen.findByText("Marked bought")).toBeTruthy();
  });

  it("keeps Mark done for a post that is not on the wishlist", async () => {
    renderItem(detail({ actions: ["archive", "done", "reprocess"] }));
    expect((await screen.findAllByRole("button", { name: "Mark done" })).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Bought" })).toBeNull();
  });

  it("shows the digest's wishlist picks with their price, link and Bought", async () => {
    const latest: Digest = {
      id: 7,
      period_start: "2026-10-18T22:00:00Z",
      period_end: "2026-10-25T22:00:00Z",
      created_at: "2026-10-25T22:00:00Z",
      model: "fake",
      sent_at: null,
      opening: null,
      top: [],
      done: [],
      groups: [],
      wishlist: [jacket({ actions: ["archive", "done", "reprocess"] })],
      item_ids: [],
    };
    route("GET /api/digests", () => ({ latest, earlier: [], topics: [] }));
    renderAt("/digests");
    route("POST /api/items/1/actions/done", () => detail({ ...jacket(), status: "done", actions: ["undone"] }));
    const section = (await screen.findByText("On your wishlist")).closest("section");
    if (!section) throw new Error("no wishlist section");
    expect(within(section).getByText("$90")).toBeTruthy();
    expect(within(section).getByRole("link", { name: "Open the link for Rain jacket" })).toBeTruthy();
    await userEvent.click(within(section).getByRole("button", { name: "Bought: Rain jacket" }));
    expect(await screen.findByText("Marked bought: Packable rain jacket")).toBeTruthy();
  });
});

describe("wishlist toggle", () => {
  it("adds a post to the wishlist and then offers to remove it", async () => {
    const bodies: unknown[] = [];
    renderItem(detail({ status: "archived", threshold_decision: "archive", actions: ["keep", "done", "reprocess"] }));
    route("PUT /api/items/1/wishlist", async (request) => {
      const body = (await request.json()) as { on: boolean };
      bodies.push(body);
      current = detail({
        status: "kept",
        wishlist: body.on,
        wishlist_post: body.on,
        wishlist_override: body.on,
        actions: ["archive", "done", "reprocess"],
      });
      return current;
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add to wishlist" }));
    expect(await screen.findByText("Added to wishlist")).toBeTruthy();
    await userEvent.click(await screen.findByRole("button", { name: "Remove from wishlist" }));
    expect(await screen.findByText("Removed from wishlist")).toBeTruthy();
    expect(bodies).toEqual([{ on: true }, { on: false }]);
  });

  it("undoes an add by restoring the choice the post had before, not by removing it for good", async () => {
    const bodies: unknown[] = [];
    renderItem(detail({ status: "archived", threshold_decision: "archive", actions: ["keep", "done", "reprocess"] }));
    route("PUT /api/items/1/wishlist", async (request) => {
      bodies.push(await request.json());
      return current;
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add to wishlist" }));
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(bodies).toEqual([{ on: true }, { on: null }]));
  });

  it("undoes removing a post you added by adding it back", async () => {
    const bodies: unknown[] = [];
    renderItem(detail({ ...jacket(), wishlist_override: true }));
    route("PUT /api/items/1/wishlist", async (request) => {
      bodies.push(await request.json());
      return current;
    });
    await userEvent.click(await screen.findByRole("button", { name: "Remove from wishlist" }));
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(bodies).toEqual([{ on: false }, { on: true }]));
  });

  it("hides the toggle when the post cannot move", async () => {
    renderItem(detail({ status: "done", can_wishlist: false, actions: ["undone"] }));
    await screen.findAllByRole("button", { name: "Not done" });
    expect(screen.queryByRole("button", { name: /wishlist/ })).toBeNull();
  });

  it("links a kept wishlist post back to the Wishlist", async () => {
    renderItem(detail({ ...jacket() }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Wishlist" }).getAttribute("href")).toBe("/wishlist"));
  });
});

const productCard = (link: string | null): Card => ({
  item_type: "product",
  title: "Packable rain jacket",
  summary: "A creator packs a rain jacket into its own pocket.",
  next_action: "Buy it before the fall.",
  details: {
    name: "Rain jacket",
    what_it_is: "A shell that packs into its own pocket.",
    price: "$90",
    link,
    wishlist: true,
  },
});

const wishlistPost = (overrides: Partial<ItemDetail> = {}): ItemDetail =>
  detail({
    ...jacket(),
    thumbnail_url: "/api/items/1/thumbnail",
    card: productCard("https://www.shop.example/jacket"),
    product: { name: "Rain jacket", price: "$90", link: "https://www.shop.example/jacket" },
    next_action: "Buy it before the fall.",
    matched_goal_title: "NYC food and experiences",
    relevance_reason: "No clear link to your active goals.",
    actions: ["archive", "done", "reprocess"],
    ...overrides,
  });

function expectNoGoalAnalysis(): void {
  expect(screen.queryByRole("meter")).toBeNull();
  expect(screen.queryByText(/No clear link/)).toBeNull();
  expect(screen.queryByText(/NYC food and experiences/)).toBeNull();
  expect(screen.queryByText("Next action")).toBeNull();
  expect(screen.queryByText("Buy it before the fall.")).toBeNull();
  expect(screen.queryByText("NYC restaurants")).toBeNull();
  expect(screen.queryByText("tacos")).toBeNull();
}

describe("wishlist item page", () => {
  it("shows the picture, name, what it is, price and where to get it, and no goal analysis", async () => {
    renderItem(wishlistPost());
    expect(await screen.findByRole("heading", { name: "Rain jacket" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Rain jacket" }).getAttribute("src")).toBe("/api/items/1/thumbnail");
    expect(screen.getByText("A shell that packs into its own pocket.")).toBeTruthy();
    expect(screen.getByText("$90")).toBeTruthy();
    const shop = screen.getByRole("link", { name: /Where to get it/ });
    expect(shop.getAttribute("href")).toBe("https://www.shop.example/jacket");
    expect(shop.textContent).toBe("Where to get itshop.example");
    expect(screen.queryByRole("link", { name: "Find it online" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Bought" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Archive" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Remove from wishlist" })).toBeTruthy();
    expect(screen.queryByText("Product")).toBeNull();
    expectNoGoalAnalysis();
  });

  it("keeps Reprocess reachable, and the wishlist page while the post is read again", async () => {
    renderItem(wishlistPost());
    const reprocessed: string[] = [];
    route("POST /api/items/1/actions/reprocess", () => {
      reprocessed.push("reprocess");
      current = wishlistPost({
        status: "queued",
        state_label: "Queued",
        in_motion: true,
        stage: "extract",
        actions: [],
        can_wishlist: false,
        wishlist: false,
        card: null,
        product: null,
        item_type: null,
        title: null,
        display_title: "@nycfoodie post",
        summary: null,
        next_action: null,
        relevance_score: null,
        threshold_decision: null,
        relevance_reason: null,
        matched_goal_id: null,
        matched_goal_title: null,
        extract_model: null,
        score_model: null,
        processed_at: null,
        topic: null,
        gist: null,
        labels: [],
      });
      return current;
    });
    await screen.findByRole("heading", { name: "Rain jacket" });
    const [reprocess] = screen.getAllByRole("button", { name: "Reprocess" });
    if (!reprocess) throw new Error("no Reprocess button");
    await userEvent.click(reprocess);
    expect(await screen.findByText("Reprocessing")).toBeTruthy();
    expect(reprocessed).toEqual(["reprocess"]);
    expect((await screen.findByRole("img", { name: "@nycfoodie post" })).getAttribute("src")).toBe(
      "/api/items/1/thumbnail",
    );
    expect(screen.getByText("Working on it. This page updates on its own.")).toBeTruthy();
    expect(screen.getByRole("img", { name: "2 of 4 stages done" })).toBeTruthy();
    expect(screen.queryByText("The post does not say where to get it.")).toBeNull();
    expect(screen.queryByText("Details")).toBeNull();
  });

  it("keeps the wishlist page for a wishlist post you archived, with what archived allows", async () => {
    renderItem(
      wishlistPost({
        status: "archived",
        wishlist: false,
        state_label: "Archived",
        status_reason: "Archived by you",
        actions: ["keep", "done", "reprocess"],
      }),
    );
    expect(await screen.findByRole("heading", { name: "Rain jacket" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Where to get it/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Archived" }).getAttribute("href")).toBe("/archived");
    const panel = screen.getByRole("button", { name: "Add to wishlist" }).closest("section");
    if (!panel) throw new Error("no state panel");
    expect(within(panel).getByText("Archived")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Keep anyway" })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Bought" })).toBeTruthy();
    expectNoGoalAnalysis();
  });

  it("says plainly when the post names no shop, and offers the original post", async () => {
    const link = "javascript:alert(1)";
    renderItem(wishlistPost({ card: productCard(link), product: { name: "Rain jacket", price: null, link } }));
    expect(await screen.findByText("The post does not say where to get it.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the original post" }).getAttribute("href")).toBe(
      "https://www.instagram.com/reel/ABC/",
    );
    expect(screen.queryByRole("link", { name: /Where to get it/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Find it online" }).getAttribute("href")).toBe(
      "https://www.google.com/search?q=Rain%20jacket",
    );
  });

  it("searches by the post's title when it has no product name", async () => {
    renderItem(
      wishlistPost({ card: null, product: { name: " ", price: null, link: null }, title: "Packable rain jacket" }),
    );
    expect(await screen.findByRole("heading", { name: "Packable rain jacket" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Find it online" }).getAttribute("href")).toBe(
      "https://www.google.com/search?q=Packable%20rain%20jacket",
    );
  });

  it("offers no search for a post with no name to search for", async () => {
    renderItem(wishlistPost({ card: null, product: null, title: null, display_title: "@nycfoodie post" }));
    expect(await screen.findByRole("heading", { name: "@nycfoodie post" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the original post" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Find it online" })).toBeNull();
  });

  it("shows a post you added by hand by its title and summary", async () => {
    renderItem(wishlistPost({ card: null, product: null, item_type: "place", wishlist_override: true }));
    expect(await screen.findByRole("heading", { name: "Packable rain jacket" })).toBeTruthy();
    expect(screen.getByText("Adobada tacos in Chelsea Market.")).toBeTruthy();
    expect(screen.getByText("The post does not say where to get it.")).toBeTruthy();
  });

  it("keeps the details of a place you added by hand", async () => {
    const place: Card = {
      item_type: "place",
      title: "Los Tacos No. 1",
      summary: "Adobada tacos in Chelsea Market.",
      next_action: "Go on a weekday before noon.",
      details: {
        name: "Los Tacos No. 1",
        kind: "Taqueria",
        neighborhood: "Chelsea",
        city: "New York",
        address: "75 9th Ave",
        why_notable: null,
        what_to_order_or_do: ["Adobada"],
        price_hint: null,
        maps_query: "Los Tacos No. 1, New York",
      },
    };
    renderItem(wishlistPost({ card: place, product: null, item_type: "place", wishlist_override: true }));
    expect(await screen.findByText("Adobada tacos in Chelsea Market.")).toBeTruthy();
    expect(screen.getByText("75 9th Ave")).toBeTruthy();
    expect(screen.getByText("Chelsea, New York")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Open in Maps/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Find it online" })).toBeNull();
    expect(screen.queryByText("Go on a weekday before noon.")).toBeNull();
  });

  it("leads an image set with its first image and keeps the rest reachable", async () => {
    const images = ["/uploads/a.png", "/uploads/b.png", "/uploads/c.png"];
    renderItem(wishlistPost({ source: "image", images, thumbnail_url: null }));
    expect((await screen.findByRole("img", { name: "Rain jacket" })).getAttribute("src")).toBe("/uploads/a.png");
    expect(within(screen.getByRole("list", { name: "Images" })).getAllByRole("link")).toHaveLength(3);
  });

  it("uses the same page once bought, with Not bought to put it back", async () => {
    renderItem(wishlistPost({ status: "done", wishlist: false, state_label: "Bought", actions: ["undone"] }));
    route("POST /api/items/1/actions/undone", () => wishlistPost());
    expect(await screen.findByRole("heading", { name: "Rain jacket" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Where to get it/ })).toBeTruthy();
    expect(screen.getByText("Bought")).toBeTruthy();
    expectNoGoalAnalysis();
    const [undo] = screen.getAllByRole("button", { name: "Not bought" });
    if (!undo) throw new Error("no Not bought button");
    await userEvent.click(undo);
    expect(await screen.findByText("Back on your wishlist")).toBeTruthy();
  });

  it("shows a settled post with no score as just its card, with no score rail or stage track", async () => {
    renderItem(
      detail({
        ...wishlistPost({ wishlist: false, wishlist_post: false, state_label: "Kept" }),
        relevance_score: null,
        threshold_decision: null,
        relevance_reason: null,
        matched_goal_title: null,
        stage: null,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Packable rain jacket" })).toBeTruthy();
    expect(screen.getByText("A shell that packs into its own pocket.")).toBeTruthy();
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.queryByRole("img", { name: /stages done/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Mark done" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Add to wishlist" })).toBeTruthy();
  });

  it("leaves a post that is not on the wishlist on the full page", async () => {
    renderItem(detail({ next_action: "Go on a weekday before noon." }));
    expect(await screen.findByRole("heading", { name: "Los Tacos No. 1" })).toBeTruthy();
    expect(screen.getByRole("meter")).toBeTruthy();
    expect(screen.getByText("Next action")).toBeTruthy();
    expect(screen.getByText(/Goal:/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Where to get it/ })).toBeNull();
  });
});
