import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createQueryClient, type Item } from "@/api";
import { callCount, route } from "@/test/fake-api";
import { item, status, topicSummary } from "@/test/fixtures";
import { createAppRouter } from "../router";

// happy-dom lays nothing out. The sidebar's Date night link gets a box, its ancestors the viewport so they don't
// clip it, and the drag chip a box at the pointer, since collisions rerun only when the chip's box moves.
const TOPIC = 'a[href="/topics/3"]';
const TOPIC_BOX = { left: 0, top: 300, width: 200, height: 28 };
const VIEWPORT = { left: 0, top: 0, width: 1024, height: 768 };
const NO_BOX = { left: 0, top: 0, width: 0, height: 0 };
const pointer = { x: 0, y: 0 };

function boxOf(el: Element): typeof NO_BOX {
  if (el.matches(TOPIC)) return TOPIC_BOX;
  if (el.matches("[data-dnd-overlay]")) return { left: pointer.x - 20, top: pointer.y - 20, width: 200, height: 40 };
  return el.querySelector(TOPIC) ? VIEWPORT : NO_BOX;
}

const rect = Element.prototype.getBoundingClientRect;
beforeAll(() => {
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const { left, top, width, height } = boxOf(this);
    return { left, top, width, height, x: left, y: top, right: left + width, bottom: top + height, toJSON: () => ({}) };
  };
  Object.assign(document, { getAnimations: () => [] });
});
afterAll(() => {
  Element.prototype.getBoundingClientRect = rect;
});

const organization = (siftTopic: { id: number; name: string } | null) => ({
  gist: "Adobada tacos.",
  key_points: [],
  labels: [],
  topic: { id: 3, name: "Date night" },
  sift_topic: siftTopic,
  topic_chosen_by: "you" as const,
  covered_by: null,
  covers: [],
  cited_in: 0,
});

function renderKept(row: Item) {
  window.history.replaceState(null, "", "/kept");
  route("GET /api/status", () => status());
  route("GET /api/items", () => [row]);
  route("GET /api/goals", () => []);
  route("GET /api/topics", () => ({
    groups: [{ goal: null, topics: [topicSummary({ id: 3, name: "Date night", kept: 2 })] }],
    suggestions: [],
    options: [{ id: 3, name: "Date night" }],
  }));
  const bodies: unknown[] = [];
  route("PUT /api/items/1/topic", async (request) => {
    bodies.push(await request.json());
    return organization({ id: 1, name: "NYC restaurants" });
  });
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="always">
        <RouterProvider router={createAppRouter(queryClient)} />
      </MotionConfig>
    </QueryClientProvider>,
  );
  return bodies;
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
function mouse(x: number, y: number) {
  Object.assign(pointer, { x, y });
  return { pointerId: 1, pointerType: "mouse", isPrimary: true, clientX: x, clientY: y };
}

// dnd-kit starts a drag a frame after the pointer moves, so each step waits.
async function hover(source: Element, x: number, y: number): Promise<void> {
  fireEvent.pointerDown(source, mouse(400, 40));
  for (let i = 1; i <= 8; i++) {
    fireEvent.pointerMove(source, mouse(400 + ((x - 400) * i) / 8, 40 + ((y - 40) * i) / 8));
    await pause(20);
  }
}

async function dragTo(source: Element, x: number, y: number): Promise<void> {
  await hover(source, x, y);
  fireEvent.pointerUp(source, mouse(x, y));
}

async function sidebarTopic(): Promise<HTMLElement> {
  const list = await screen.findByRole("list", { name: "Topics with kept posts" });
  return within(list).findByRole("link", { name: /Date night/ });
}

describe("dropping a row on a sidebar topic", () => {
  it("moves the post there, and Undo puts it back on Sift's pick", async () => {
    const bodies = renderKept(item());
    await sidebarTopic();
    await dragTo(await screen.findByRole("link", { name: /Los Tacos/ }), 100, 314);
    await waitFor(() => expect(bodies).toEqual([{ topic_id: 3 }]));

    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(bodies).toEqual([{ topic_id: 3 }, { topic_id: null }]));
  });

  it("lights the topic while an organized post is over it", async () => {
    renderKept(item());
    const topic = await sidebarTopic();
    const row = await screen.findByRole("link", { name: /Los Tacos/ });
    await hover(row, 100, 314);
    await waitFor(() => expect(topic.getAttribute("data-drop")).toBe("true"));
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    fireEvent.pointerUp(row, mouse(100, 314));
  });

  it("sends nothing for a post that is not organized yet", async () => {
    renderKept(item({ gist: null, topic: null }));
    await sidebarTopic();
    await dragTo(await screen.findByRole("link", { name: /Los Tacos/ }), 100, 314);
    await pause(100);
    expect(callCount("PUT /api/items/1/topic")).toBe(0);
  });

  it("sends nothing for a post already in that topic", async () => {
    renderKept(item({ topic: { id: 3, name: "Date night" } }));
    await sidebarTopic();
    await dragTo(await screen.findByRole("link", { name: /Los Tacos/ }), 100, 314);
    await pause(100);
    expect(callCount("PUT /api/items/1/topic")).toBe(0);
  });
});

describe("the keyboard on a Kept row", () => {
  it("opens the post on Enter and picks nothing up", async () => {
    renderKept(item());
    const row = await screen.findByRole("link", { name: /Los Tacos/ });
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(document.querySelector("[data-dnd-overlay]")?.textContent).toBe("");
    await waitFor(() => expect(window.location.pathname).toBe("/items/1"));
  });
});
