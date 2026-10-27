import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { toast } from "sonner";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { createQueryClient, type Item } from "@/api";
import { callCount, route } from "@/test/fake-api";
import { item, status } from "@/test/fixtures";
import { createAppRouter } from "../router";

function renderAt(url: string, rows: Item[] = [item({ actions: ["archive", "done", "reprocess"] })]) {
  window.history.replaceState(null, "", url);
  route("GET /api/status", () => status());
  route("GET /api/items", () => rows);
  route("GET /api/goals", () => []);
  route("GET /api/imports", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  route("POST /api/items/1/actions/archive", () => ({ ...item(), status: "archived" }));
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

const at = (pointerType: string, x: number, y = 40, pointerId = 1) => ({
  pointerId,
  pointerType,
  isPrimary: pointerId === 1,
  clientX: x,
  clientY: y,
});

function drag(target: Element, pointerType: string, dx: number, dy = 0, release = true): void {
  fireEvent.pointerDown(target, at(pointerType, 200));
  for (let i = 1; i <= 8; i++) fireEvent.pointerMove(target, at(pointerType, 200 + (dx * i) / 8, 40 + (dy * i) / 8));
  if (release) fireEvent.pointerUp(target, at(pointerType, 200 + dx, 40 + dy));
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// dnd-kit starts a drag a frame after the pointer moves, so the moves wait between steps.
async function slowDrag(target: Element, pointerType: string, dx: number): Promise<void> {
  fireEvent.pointerDown(target, at(pointerType, 200));
  for (let i = 1; i <= 8; i++) {
    fireEvent.pointerMove(target, at(pointerType, 200 + (dx * i) / 8));
    await pause(20);
  }
}

const dragChip = () => document.querySelector("[data-dnd-overlay][data-dnd-dragging]");

// happy-dom has no getAnimations, which dnd-kit's drag feedback calls.
Object.assign(document, { getAnimations: () => [] });

function tap(target: Element, pointerType = "touch"): void {
  fireEvent.pointerDown(target, at(pointerType, 200));
  fireEvent.pointerUp(target, at(pointerType, 200));
  fireEvent.click(target, { detail: 1 });
}

function held(): { open: () => void; until: Promise<void> } {
  let open = () => {};
  const until = new Promise<void>((resolve) => (open = resolve));
  return { open, until };
}

const offset = (link: Element) => link.closest<HTMLElement>(".touch-pan-y")?.style.transform;

async function findRow(): Promise<{ link: HTMLElement }> {
  const link = await screen.findByRole("link", { name: /Los Tacos/ });
  if (!link.closest(".touch-pan-y")) throw new Error("the row is not swipeable");
  return { link };
}

const ARCHIVE = "POST /api/items/1/actions/archive";
const failedRow = item({
  status: "failed",
  state_label: "Failed",
  relevance_score: null,
  threshold_decision: null,
  actions: ["archive", "retry"],
});

describe("swiping a list row", () => {
  // happy-dom lays nothing out, and a committed swipe parks the row one row-width over.
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");
  beforeAll(() => Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 390 }));
  afterAll(() => width && Object.defineProperty(HTMLElement.prototype, "offsetWidth", width));

  it("archives a Kept row on a long left swipe by touch, without opening it", async () => {
    const router = renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -160);
    fireEvent.click(link, { detail: 1 });
    await waitFor(() => expect(callCount(ARCHIVE)).toBe(1));
    expect(router.state.location.pathname).toBe("/kept");
  });

  it("ignores short swipes, vertical scrolls and the mouse, which drags to the sidebar instead", async () => {
    renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -40);
    drag(link, "touch", -60, 200);
    drag(link, "mouse", -160);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(callCount(ARCHIVE)).toBe(0);
  });

  it("does nothing toward a side the server allows no action for", async () => {
    renderAt("/kept", [item({ actions: ["undone", "reprocess"], status: "done" })]);
    const { link } = await findRow();
    drag(link, "touch", -160);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(callCount(ARCHIVE)).toBe(0);
  });

  it("offers Undo after archiving a Kept row, which keeps it again", async () => {
    renderAt("/kept");
    route(ARCHIVE, () => item({ status: "archived", actions: ["keep", "done", "reprocess"] }));
    route("POST /api/items/1/actions/keep", () => item());
    const { link } = await findRow();
    drag(link, "touch", -160);
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(callCount("POST /api/items/1/actions/keep")).toBe(1));
  });

  it("offers Reprocess, not Undo, after archiving a failed Inbox row, since nothing returns it to failed", async () => {
    renderAt("/inbox", [failedRow]);
    route(ARCHIVE, () => ({ ...failedRow, status: "archived", actions: ["reprocess"] }));
    route("POST /api/items/1/actions/reprocess", () => ({ ...failedRow, status: "queued", actions: [] }));
    const { link } = await findRow();
    drag(link, "touch", -160);
    await userEvent.click(await screen.findByRole("button", { name: "Reprocess" }));
    await waitFor(() => expect(callCount("POST /api/items/1/actions/reprocess")).toBe(1));
    expect(callCount("POST /api/items/1/actions/keep")).toBe(0);
  });

  it("ignores a second finger lifting mid-swipe", async () => {
    renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -160, 0, false);
    fireEvent.pointerDown(link, at("touch", 300, 40, 2));
    fireEvent.pointerUp(link, at("touch", 300, 40, 2));
    fireEvent.pointerUp(link, at("touch", 40));
    await waitFor(() => expect(callCount(ARCHIVE)).toBe(1));
  });

  it("swipes with a pen and never starts a shelf drag with it", async () => {
    renderAt("/kept");
    const { link } = await findRow();
    await slowDrag(link, "pen", -160);
    expect(dragChip()).toBeNull();
    fireEvent.pointerUp(link, at("pen", 40));
    await waitFor(() => expect(callCount(ARCHIVE)).toBe(1));
  });

  it("starts a shelf drag with the mouse", async () => {
    renderAt("/kept");
    const { link } = await findRow();
    await slowDrag(link, "mouse", -160);
    expect(dragChip()?.textContent).toBe("Los Tacos No. 1");
    fireEvent.pointerUp(link, at("mouse", 40));
  });

  it("opens the row on a later tap after a swipe that snapped back", async () => {
    const router = renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -40);
    await pause(400);
    tap(link);
    await waitFor(() => expect(router.state.location.pathname).toBe("/items/1"));
  });

  it("swallows the click that ends a swipe however late it arrives", async () => {
    const router = renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -40);
    await pause(600);
    fireEvent.click(link, { detail: 1 });
    await pause(100);
    expect(router.state.location.pathname).toBe("/kept");
  });

  it("opens the row on a mouse click after a touch swipe", async () => {
    const router = renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -40);
    tap(link, "mouse");
    await waitFor(() => expect(router.state.location.pathname).toBe("/items/1"));
  });

  it("brings the row back when its action succeeds without changing its status", async () => {
    renderAt("/kept");
    const answer = held();
    route("POST /api/items/1/actions/done", async () => {
      await answer.until;
      return item();
    });
    const { link } = await findRow();
    drag(link, "touch", 160);
    expect(offset(link)).toBe("translateX(390px)");
    answer.open();
    await screen.findByText("Marked done: Los Tacos No. 1");
    await waitFor(() => expect(offset(link)).toBe(""));
  });

  it("keeps an archived row off-screen until the list drops it", async () => {
    const rows = [item()];
    renderAt("/kept", rows);
    route(ARCHIVE, () => {
      rows.length = 0;
      return item({ status: "archived", actions: ["keep", "done", "reprocess"] });
    });
    const { link } = await findRow();
    drag(link, "touch", -160);
    const shown: (string | undefined)[] = [];
    const row = link.closest<HTMLElement>(".touch-pan-y");
    if (!row) throw new Error("the row is not swipeable");
    new MutationObserver(() => shown.push(row.style.transform)).observe(row, { attributeFilter: ["style"] });
    await waitFor(() => expect(link.isConnected).toBe(false));
    expect(shown).not.toContain("");
  });

  describe("two quick swipes", () => {
    afterEach(() => {
      toast.dismiss();
    });

    it.each([
      { fails: "Lucali", archives: "Joe's Pizza" },
      { fails: "Joe's Pizza", archives: "Lucali" },
    ])("handles each of two quick swipes on its own when $fails fails", async ({ fails, archives }) => {
      const rows = [
        item({ title: "Lucali", display_title: "Lucali" }),
        item({ id: 2, title: "Joe's Pizza", display_title: "Joe's Pizza" }),
      ];
      renderAt("/kept", rows);
      const answer = held();
      for (const row of rows) {
        route(`POST /api/items/${row.id}/actions/archive`, async () => {
          await answer.until;
          if (row.display_title === fails) throw { status: 409, detail: `${fails} moved.` };
          return { ...row, status: "archived", actions: ["keep", "done", "reprocess"] };
        });
      }
      drag(await screen.findByRole("link", { name: /Lucali/ }), "touch", -160);
      drag(screen.getByRole("link", { name: /Joe's Pizza/ }), "touch", -160);
      await waitFor(() => expect(callCount("POST /api/items/2/actions/archive")).toBe(1));
      answer.open();
      expect(await screen.findByText(`Archived: ${archives}`)).toBeTruthy();
      expect(await screen.findByText(`${fails} moved.`)).toBeTruthy();
      await waitFor(() => expect(offset(screen.getByRole("link", { name: new RegExp(fails) }))).toBe(""));
    });
  });

  it("opens the row on Enter right after a swipe that snapped back", async () => {
    const router = renderAt("/kept");
    const { link } = await findRow();
    drag(link, "touch", -40);
    link.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/items/1"));
  });
});

describe("the phone Add sheet", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("submits the clipboard in one tap and closes", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { readText: () => Promise.resolve("https://www.instagram.com/reel/ABC/") },
    });
    const sent: string[] = [];
    route("POST /api/items", async (request) => {
      sent.push(((await request.json()) as { text: string }).text);
      return [{ kind: "queued", item: item() }];
    });
    renderAt("/kept");
    const focused: (string | null)[] = [];
    const onFocus = (event: FocusEvent) => focused.push((event.target as Element).getAttribute("aria-label"));
    document.addEventListener("focusin", onFocus);
    await userEvent.click(await screen.findByRole("button", { name: "Add a link" }));
    await userEvent.click(await screen.findByRole("button", { name: "Paste link from clipboard" }));
    await waitFor(() => expect(sent).toEqual(["https://www.instagram.com/reel/ABC/"]));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    document.removeEventListener("focusin", onFocus);
    expect(focused).not.toContain("Link to add");
  });

  it("focuses the field instead when the browser gives no clipboard", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    renderAt("/kept");
    await userEvent.click(await screen.findByRole("button", { name: "Add a link" }));
    const field = await screen.findByRole("textbox", { name: "Link to add" });
    expect(screen.queryByRole("button", { name: "Paste link from clipboard" })).toBeNull();
    expect(document.activeElement).toBe(field);
  });

  it("leaves the field unfocused while the clipboard answers, then says so and focuses it when it gives nothing", async () => {
    let answer: (text: string) => void = () => {};
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { readText: () => new Promise<string>((resolve) => (answer = resolve)) },
    });
    renderAt("/kept");
    await userEvent.click(await screen.findByRole("button", { name: "Add a link" }));
    await userEvent.click(await screen.findByRole("button", { name: "Paste link from clipboard" }));
    const field = screen.getByRole("textbox", { name: "Link to add" });
    expect(document.activeElement).not.toBe(field);
    answer("");
    expect(await screen.findByText("Couldn't read the clipboard. Tap the field and paste.")).toBeTruthy();
    expect(document.activeElement).toBe(field);
  });
});

describe("the dock's sheets", () => {
  it.each(["Add a link", "More"])("returns focus to the %s button when Escape closes its sheet", async (name) => {
    renderAt("/kept");
    const button = await screen.findByRole("button", { name });
    expect(button.getAttribute("aria-haspopup")).toBe("dialog");
    await userEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(button));
  });

  it("returns focus to the Inbox empty state's Add button, not the dock's, when its sheet closes", async () => {
    renderAt("/inbox", []);
    await screen.findByText("Nothing in progress");
    const button = screen.getAllByRole("button", { name: "Add a link" }).find((b) => !b.hasAttribute("aria-haspopup"));
    if (!button) throw new Error("the empty state has no Add button");
    await userEvent.click(button);
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(button));
  });
});
