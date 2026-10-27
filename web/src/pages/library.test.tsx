import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "@/api";
import { route } from "@/test/fake-api";
import { item, status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const DEBOUNCE_MS = 200;

function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  route("GET /api/status", () => status());
  route("GET /api/items", () => [item()]);
  route("GET /api/goals", () => []);
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

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const settle = () => sleep(DEBOUNCE_MS + 100);

describe("library search", () => {
  it("follows the URL when a link clears the query", async () => {
    const router = renderAt("/kept?q=foo");
    const box = await screen.findByRole<HTMLInputElement>("searchbox", { name: "Search" });
    expect(box.value).toBe("foo");

    const [kept] = screen.getAllByRole("link", { name: /Kept/ });
    if (!kept) throw new Error("no Kept link");
    await userEvent.click(kept);
    await settle();
    expect(router.state.location.search).toEqual({});
    expect(box.value).toBe("");
  });

  it("debounces typing into the URL and keeps what was typed", async () => {
    const router = renderAt("/kept");
    const box = await screen.findByRole<HTMLInputElement>("searchbox", { name: "Search" });
    await userEvent.type(box, "tacos ");
    await waitFor(() => expect(router.state.location.search).toEqual({ q: "tacos" }));
    await settle();
    expect(box.value).toBe("tacos ");
  });

  it("keeps typing that lands while a search is loading", async () => {
    const router = renderAt("/kept");
    const box = await screen.findByRole<HTMLInputElement>("searchbox", { name: "Search" });
    const LOAD_MS = 400;
    route("GET /api/items", async () => {
      await sleep(LOAD_MS);
      return [item()];
    });
    await userEvent.type(box, "taco");
    await sleep(DEBOUNCE_MS + LOAD_MS / 2);
    await userEvent.type(box, "s");
    await sleep(LOAD_MS + DEBOUNCE_MS + LOAD_MS);
    expect(box.value).toBe("tacos");
    await waitFor(() => expect(router.state.location.search).toEqual({ q: "tacos" }));
    expect(box.value).toBe("tacos");
  });
});
