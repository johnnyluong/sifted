import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "@/api";
import { ROADMAP_STAGES } from "@/lib/roadmap";
import { route } from "@/test/fake-api";
import { status } from "@/test/fixtures";
import { createAppRouter } from "../router";

function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  route("GET /api/status", () => status());
  route("GET /api/items", () => []);
  route("GET /api/goals", () => []);
  route("GET /api/imports", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter(queryClient)} />
    </QueryClientProvider>,
  );
}

describe("roadmap", () => {
  it("opens from the settings menu, which also holds the theme", async () => {
    renderAt("/inbox");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Settings" }));
    const menu = await screen.findByRole("dialog");
    expect(within(menu).getByRole("radio", { name: "System" })).toHaveProperty("checked", true);

    await user.click(within(menu).getByRole("link", { name: "Roadmap" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Roadmap" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("draws the today line above the first stage not built yet", async () => {
    renderAt("/roadmap");
    const stages = await screen.findAllByRole("heading", { level: 2 });
    const first = ROADMAP_STAGES.findIndex((s) => s.progress !== "built");
    const next = ROADMAP_STAGES[first];
    if (!next) throw new Error("expected a stage not built yet");
    const items = stages.map((h) => h.closest("li"));
    const marked = items.filter((li) => li && within(li).queryByText("Today"));
    expect(marked).toEqual([items[first]]);
    expect(stages[first]?.textContent).toBe(next.title);
  });
});
