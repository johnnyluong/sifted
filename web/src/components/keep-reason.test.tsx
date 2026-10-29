import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createQueryClient, type Goal, type ItemDetail, type KeepReason } from "@/api";
import { route } from "@/test/fake-api";
import { detail, status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const GOALS: Goal[] = [
  {
    id: 1,
    title: "Market my web app",
    description: "",
    category: "entrepreneurial",
    active: true,
    created_at: "2026-10-20T12:00:00Z",
    updated_at: "2026-10-20T12:00:00Z",
  },
  {
    id: 2,
    title: "Retired goal",
    description: "",
    category: "other",
    active: false,
    created_at: "2026-10-20T12:00:00Z",
    updated_at: "2026-10-20T12:00:00Z",
  },
];

const keptAnyway = (keep_reason: KeepReason | null = null): ItemDetail =>
  detail({
    status: "kept",
    relevance_score: 41,
    threshold_decision: "archive",
    user_override: "keep",
    actions: ["done", "archive"],
    asks_keep_reason: true,
    keep_reason,
  });

let current: ItemDetail;

function renderItem(item: ItemDetail) {
  current = item;
  window.history.replaceState(null, "", "/items/1");
  route("GET /api/status", () => status());
  route("GET /api/goals", () => GOALS);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  route("GET /api/items/1", () => current);
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter(queryClient)} />
    </QueryClientProvider>,
  );
}

describe("keep reason", () => {
  it("asks why on a post kept anyway and sends the goal and the note", async () => {
    const bodies: unknown[] = [];
    route("PUT /api/items/1/keep-reason", async (request) => {
      bodies.push(await request.json());
      current = keptAnyway({
        goal_id: 1,
        goal_title: "Market my web app",
        note: "the hooks",
        at: "2026-10-26T12:00:00Z",
      });
      return current;
    });
    renderItem(keptAnyway());
    const user = userEvent.setup();
    const save = await screen.findByRole("button", { name: "Save reason" });
    expect(save).toHaveProperty("disabled", true);
    expect(screen.queryByRole("radio", { name: "Retired goal" })).toBeNull();

    await user.click(await screen.findByRole("radio", { name: "Market my web app" }));
    await user.type(screen.getByLabelText("In your words"), "the hooks");
    await user.click(save);

    await waitFor(() => expect(bodies).toEqual([{ goal_id: 1, note: "the hooks" }]));
    expect(await screen.findByText("For Market my web app")).toBeTruthy();
    expect(screen.getByText("the hooks")).toBeTruthy();
  });

  it("sends null for none of my goals", async () => {
    const bodies: unknown[] = [];
    route("PUT /api/items/1/keep-reason", async (request) => {
      bodies.push(await request.json());
      current = keptAnyway({ goal_id: null, goal_title: null, note: null, at: "2026-10-26T12:00:00Z" });
      return current;
    });
    renderItem(keptAnyway());
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "None of my goals" }));
    await user.click(screen.getByRole("button", { name: "Save reason" }));
    await waitFor(() => expect(bodies).toEqual([{ goal_id: null, note: "" }]));
    expect(await screen.findByText("None of your goals")).toBeTruthy();
  });

  it("opens a saved reason for a change with its choice picked", async () => {
    renderItem(keptAnyway({ goal_id: 1, goal_title: "Market my web app", note: "n", at: "2026-10-26T12:00:00Z" }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Change" }));
    expect(screen.getByRole("radio", { name: "Market my web app" })).toHaveProperty("checked", true);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("For Market my web app")).toBeTruthy();
  });

  it("asks for a new choice when the saved goal was turned off", async () => {
    renderItem(keptAnyway({ goal_id: 2, goal_title: "Retired goal", note: "n", at: "2026-10-26T12:00:00Z" }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Change" }));
    await screen.findByRole("radio", { name: "Market my web app" });
    expect(screen.getAllByRole("radio").some((r) => (r as HTMLInputElement).checked)).toBe(false);
    expect(screen.getByRole("button", { name: "Save reason" })).toHaveProperty("disabled", true);
  });

  it("does not ask when the filter also said keep", async () => {
    renderItem(detail({ user_override: "keep", threshold_decision: "keep" }));
    await screen.findByText("Open original");
    expect(screen.queryByText("Why keep it?")).toBeNull();
  });
});
