import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { toast } from "sonner";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { createQueryClient, type Item, type ItemDetail } from "@/api";
import { callCount, route } from "@/test/fake-api";
import { detail, item, status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const DELETE = "DELETE /api/items/1";
const GET_ITEM = "GET /api/items/1";
const KEEP = "POST /api/items/1/actions/keep";
const CONFLICT = "Only an archived post can be deleted; this one is queued.";

const archivedItem = (overrides: Partial<Item> = {}): Item =>
  item({
    status: "archived",
    state_label: "Archived",
    threshold_decision: "archive",
    actions: ["keep", "done", "reprocess"],
    can_delete: true,
    ...overrides,
  });

let rows: Item[] = [];
let page: ItemDetail = detail();

function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  route("GET /api/status", () => status());
  route("GET /api/items", () => rows);
  route(GET_ITEM, () => page);
  route("GET /api/goals", () => []);
  route("GET /api/imports", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  route(DELETE, () => {
    rows = rows.filter((r) => r.id !== 1);
    route(GET_ITEM, () => {
      throw { status: 404, detail: "Item not found" };
    });
    return new Response(null, { status: 204 });
  });
  const queryClient = createQueryClient();
  const router = createAppRouter(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="always">
        <RouterProvider router={router} />
      </MotionConfig>
    </QueryClientProvider>,
  );
  return router;
}

async function confirmDialog(): Promise<HTMLElement> {
  const dialog = await screen.findByRole("dialog", { name: "Delete this post?" });
  expect(within(dialog).getByText("It is removed from Sift with its saved media. This can't be undone.")).toBeTruthy();
  return dialog;
}

afterEach(() => {
  toast.dismiss();
  rows = [];
});

describe("deleting from the item page", () => {
  it("offers Delete on an archived post", async () => {
    page = detail({ ...archivedItem() });
    renderAt("/items/1");
    expect(await screen.findByRole("button", { name: "Delete" })).toBeTruthy();
  });

  it("offers Delete on an archived wishlist post's short page", async () => {
    page = detail({ ...archivedItem({ wishlist_post: true, item_type: "product" }) });
    renderAt("/items/1");
    expect(await screen.findByRole("link", { name: /Open the original post/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy();
  });

  it("offers no Delete on a kept post", async () => {
    page = detail();
    renderAt("/items/1");
    await screen.findAllByRole("button", { name: "Mark done" });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("follows the server's can_delete, not the status", async () => {
    page = detail({ ...archivedItem({ can_delete: false }) });
    renderAt("/items/1");
    await screen.findAllByRole("button", { name: "Keep anyway" });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("confirms, deletes, toasts and goes back to Archived", async () => {
    page = detail({ ...archivedItem() });
    rows = [archivedItem()];
    const router = renderAt("/items/1");
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await confirmDialog();
    expect(callCount(DELETE)).toBe(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Deleted: Los Tacos No. 1")).toBeTruthy();
    expect(callCount(DELETE)).toBe(1);
    await waitFor(() => expect(router.state.location.pathname).toBe("/archived"));
    expect(await screen.findByText("Nothing archived")).toBeTruthy();
  });

  it("forgets the deleted post, so its page loads as not found afterwards", async () => {
    page = detail({ ...archivedItem() });
    rows = [archivedItem()];
    const router = renderAt("/items/1");
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const fetched = callCount(GET_ITEM);
    await userEvent.click(within(await confirmDialog()).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/archived"));
    await screen.findByText("Nothing archived");
    expect(callCount(GET_ITEM), "no refetch of the deleted post").toBe(fetched);

    await router.navigate({ to: "/items/$itemId", params: { itemId: 1 } });
    expect(await screen.findByRole("heading", { name: "Not here" })).toBeTruthy();
    expect(callCount(GET_ITEM)).toBe(fetched + 1);
  });

  it("keeps the page's shortcuts off while the confirmation is open", async () => {
    page = detail({ ...archivedItem() });
    renderAt("/items/1");
    route(KEEP, () => detail());
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await confirmDialog();
    await userEvent.keyboard("k");
    await userEvent.click(within(await confirmDialog()).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(callCount(KEEP)).toBe(0);
    await userEvent.keyboard("k");
    await waitFor(() => expect(callCount(KEEP), "the shortcut works once the sheet is closed").toBe(1));
  });

  it("does nothing on Cancel", async () => {
    page = detail({ ...archivedItem() });
    const router = renderAt("/items/1");
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(within(await confirmDialog()).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(callCount(DELETE)).toBe(0);
    expect(router.state.location.pathname).toBe("/items/1");
  });

  it("toasts the server's refusal and keeps the page", async () => {
    page = detail({ ...archivedItem() });
    const router = renderAt("/items/1");
    route(DELETE, () => {
      throw { status: 409, detail: CONFLICT };
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(within(await confirmDialog()).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(CONFLICT)).toBeTruthy();
    expect(screen.queryByText("Deleted: Los Tacos No. 1")).toBeNull();
    expect(router.state.location.pathname).toBe("/items/1");
    expect(screen.getByRole("heading", { name: "Los Tacos No. 1" })).toBeTruthy();
  });
});

const at = (pointerType: string, x: number) => ({
  pointerId: 1,
  pointerType,
  isPrimary: true,
  clientX: x,
  clientY: 40,
});

function swipe(target: Element, dx: number): void {
  fireEvent.pointerDown(target, at("touch", 200));
  for (let i = 1; i <= 8; i++) fireEvent.pointerMove(target, at("touch", 200 + (dx * i) / 8));
  fireEvent.pointerUp(target, at("touch", 200 + dx));
}

const offset = (link: Element) => link.closest<HTMLElement>(".touch-pan-y")?.style.transform;

describe("deleting from the Archived list", () => {
  // happy-dom lays nothing out, and a committed swipe parks the row one row-width over.
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");
  beforeAll(() => Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 390 }));
  afterAll(() => width && Object.defineProperty(HTMLElement.prototype, "offsetWidth", width));

  it("deletes a row on a long left swipe by touch after the same confirmation", async () => {
    rows = [archivedItem()];
    const router = renderAt("/archived");
    const link = await screen.findByRole("link", { name: /Los Tacos/ });
    swipe(link, -160);
    const dialog = await confirmDialog();
    expect(offset(link)).toBe("translateX(-390px)");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Deleted: Los Tacos No. 1")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("link", { name: /Los Tacos/ })).toBeNull());
    expect(callCount(DELETE)).toBe(1);
    expect(router.state.location.pathname).toBe("/archived");
  });

  it("brings a swiped row back on Cancel", async () => {
    rows = [archivedItem()];
    renderAt("/archived");
    const link = await screen.findByRole("link", { name: /Los Tacos/ });
    swipe(link, -160);
    await userEvent.click(within(await confirmDialog()).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(offset(link)).toBeFalsy());
    expect(callCount(DELETE)).toBe(0);
    expect(screen.getByRole("link", { name: /Los Tacos/ })).toBeTruthy();
  });

  it("deletes a row from its Delete button, by mouse or keyboard", async () => {
    rows = [archivedItem()];
    renderAt("/archived");
    const button = await screen.findByRole("button", { name: "Delete Los Tacos No. 1" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.click(within(await confirmDialog()).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: /Los Tacos/ })).toBeNull());
    expect(callCount(DELETE)).toBe(1);
  });

  it("keeps the search shortcut off while the confirmation is open", async () => {
    rows = [archivedItem()];
    renderAt("/archived");
    await userEvent.click(await screen.findByRole("button", { name: "Delete Los Tacos No. 1" }));
    const dialog = await confirmDialog();
    const untouched = fireEvent.keyDown(within(dialog).getByRole("button", { name: "Cancel" }), { key: "/" });
    expect(untouched, "the page left the keystroke alone").toBe(true);
    expect(document.activeElement).not.toBe(screen.getByRole("searchbox", { hidden: true }));
  });

  it("gives Kept rows no delete", async () => {
    rows = [item(), item({ id: 2, status: "done", state_label: "Done", actions: ["undone", "reprocess"] })];
    renderAt("/kept");
    const [link] = await screen.findAllByRole("link", { name: /Los Tacos/ });
    if (!link) throw new Error("no Kept row");
    expect(screen.queryByRole("button", { name: /^Delete/ })).toBeNull();
    route("POST /api/items/1/actions/archive", () => archivedItem());
    swipe(link, -160);
    await waitFor(() => expect(callCount("POST /api/items/1/actions/archive")).toBe(1));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callCount(DELETE)).toBe(0);
  });
});
