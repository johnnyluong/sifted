import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient, type RebuildApply, type RebuildPlan } from "@/api";
import { callCount, route } from "@/test/fake-api";
import { status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock("sonner", () => ({ toast, Toaster: () => null }));

afterEach(() => toast.mockClear());

const PLAN: RebuildPlan = {
  topics: [
    {
      name: "App building",
      description: "Building and shipping my app.",
      continues: [
        { id: 1, name: "SEO" },
        { id: 2, name: "Personal branding" },
      ],
      posts: [
        { id: 10, title: "Ship every week" },
        { id: 11, title: "Landing pages that convert" },
      ],
    },
    { name: "NYC outings", description: "Places to go.", continues: [], posts: [{ id: 12, title: "Lucali" }] },
  ],
  unsorted: [{ id: 13, title: "A stray post" }],
  retiring: [{ id: 3, name: "Pizza" }],
};

function renderRebuild() {
  window.history.replaceState(null, "", "/topics/rebuild");
  route("GET /api/status", () => status());
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  route("POST /api/topics/rebuild/draft", () => PLAN);
  const queryClient = createQueryClient();
  const router = createAppRouter(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

async function draft() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Draft new topics" }));
  await screen.findByRole("heading", { name: "New topics" });
  return user;
}

const titles = (list: HTMLElement) =>
  within(list)
    .getAllByRole("listitem")
    .map((li) => li.textContent);

describe("rebuild topics", () => {
  it("changes nothing until the draft is applied", async () => {
    renderRebuild();
    await draft();
    expect(screen.getByText("Continues SEO, Personal branding")).toBeTruthy();
    expect(screen.getByText("New")).toBeTruthy();
    expect(callCount("POST /api/topics/rebuild")).toBe(0);
  });

  it("applies the edited plan: renamed, removed and added topics", async () => {
    let applied: RebuildApply | undefined;
    route("POST /api/topics/rebuild", async (request) => {
      applied = (await request.json()) as RebuildApply;
      return { groups: [], suggestions: [], options: [] };
    });
    const router = renderRebuild();
    const user = await draft();
    expect(titles(screen.getByRole("list", { name: "Sorted after you apply" }))).toEqual(["A stray post"]);
    expect(screen.getByText(/^Removed:/).textContent).toBe("Removed: Pizza");

    const [name] = screen.getAllByLabelText("Topic");
    if (!name) throw new Error("no planned topic");
    await user.clear(name);
    await user.type(name, "Product");
    await user.click(screen.getByRole("button", { name: "Remove NYC outings" }));
    expect(titles(screen.getByRole("list", { name: "Sorted after you apply" }))).toEqual(["A stray post", "Lucali"]);

    await user.click(screen.getByRole("button", { name: "Add a topic" }));
    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).toHaveProperty("disabled", true);
    const [, added] = screen.getAllByLabelText("Topic");
    if (!added) throw new Error("no added topic");
    await user.type(added, "Reading list");
    await user.click(apply);

    await waitFor(() => expect(router.state.location.pathname).toBe("/topics"));
    expect(applied).toEqual({
      topics: [
        { name: "Product", description: "Building and shipping my app.", continues: [1, 2], posts: [10, 11] },
        { name: "Reading list", description: "", continues: [], posts: [] },
      ],
      resort: [13, 12],
      retire: [3],
    });
    expect(toast).toHaveBeenCalledWith("Topics rebuilt");
  });

  it("lists the topics a removed card continued as removed", async () => {
    renderRebuild();
    const user = await draft();
    await user.click(screen.getByRole("button", { name: "Remove App building" }));
    expect(screen.getByText(/^Removed:/).textContent).toBe("Removed: Pizza, SEO, Personal branding");
    expect(titles(screen.getByRole("list", { name: "Sorted after you apply" }))).toEqual([
      "A stray post",
      "Ship every week",
      "Landing pages that convert",
    ]);
  });

  it("shows a refused apply next to the button and stays on the review", async () => {
    route("POST /api/topics/rebuild", () => {
      throw { status: 409, detail: 'Two topics are named "App building". Rename one.' };
    });
    const router = renderRebuild();
    const user = await draft();
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect((await screen.findByRole("alert")).textContent).toBe('Two topics are named "App building". Rename one.');
    expect(router.state.location.pathname).toBe("/topics/rebuild");
  });

  it("explains a draft that could not run", async () => {
    renderRebuild();
    route("POST /api/topics/rebuild/draft", () => {
      throw { status: 409, detail: "Keep at least 2 posts before rebuilding topics." };
    });
    await userEvent.click(await screen.findByRole("button", { name: "Draft new topics" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Keep at least 2 posts before rebuilding topics.");
  });
});
