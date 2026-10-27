import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient, type Item, type ItemOrganization } from "@/api";
import { callCount, route } from "@/test/fake-api";
import { detail, item, status, topicDetail } from "@/test/fixtures";
import { createAppRouter } from "../router";

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock("sonner", () => ({ toast, Toaster: () => null }));

afterEach(() => toast.mockClear());

function renderAt(url: string, rows: Item[] = [item()]) {
  window.history.replaceState(null, "", url);
  route("GET /api/status", () => status());
  route("GET /api/items", () => rows);
  route("GET /api/goals", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [{ id: 3, name: "NYC restaurants" }] }));
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

const cover = item({ id: 1, title: "Lucali: how to get a table", display_title: "Lucali: how to get a table" });
const covered = item({
  id: 2,
  title: "Lucali in 30 seconds",
  display_title: "Lucali in 30 seconds",
  covered_by: { id: 1, title: "Lucali: how to get a table" },
});

describe("topic page", () => {
  it("redirects a merged topic's id to the topic that absorbed it", async () => {
    route("GET /api/topics/9", () => topicDetail({ id: 3 }));
    route("GET /api/topics/3", () => topicDetail({ id: 3 }));
    const router = renderAt("/topics/9");
    await waitFor(() => expect(router.state.location.pathname).toBe("/topics/3"));
    expect(await screen.findByRole("heading", { level: 1, name: "NYC restaurants" })).toBeTruthy();
  });

  it("lights the sources a brief point cites while the pointer is on it", async () => {
    route("GET /api/topics/3", () => topicDetail());
    renderAt("/topics/3");
    const point = (await screen.findByText("Join the line by 4:45pm.")).closest("li");
    if (!point) throw new Error("no point");
    const lit = () => [...document.querySelectorAll("[data-lit]")].map((el) => el.id);

    fireEvent.mouseEnter(point);
    expect(lit()).toEqual(["source-1", "source-2"]);
    fireEvent.mouseLeave(point);
    expect(lit()).toEqual([]);
  });

  it("removes a topic only after the inline confirm, then returns to Topics", async () => {
    route("GET /api/topics/3", () => topicDetail());
    route("DELETE /api/topics/3", () => ({ rehoming: 3 }));
    const router = renderAt("/topics/3");
    await userEvent.click(await screen.findByRole("button", { name: "Edit topic" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove topic" }));
    expect(callCount("DELETE /api/topics/3")).toBe(0);

    const confirm = screen.getByRole("alertdialog");
    await userEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/topics"));
    expect(callCount("DELETE /api/topics/3")).toBe(1);
  });

  it("offers only labels two or more posts share as filters", async () => {
    route("GET /api/topics/3", () => topicDetail());
    renderAt("/topics/3");
    const filters = await screen.findByRole("navigation", { name: "Filter by label" });
    expect(
      within(filters)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["All 3", "date night 2"]);
  });
});

describe("folded posts", () => {
  it("nest under their cover behind a toggle when the cover is listed", async () => {
    renderAt("/kept", [covered, cover]);
    const toggle = await screen.findByRole("button", { name: "1 more says the same" });
    expect(screen.queryByRole("link", { name: /Lucali in 30 seconds/ })).toBeNull();

    await userEvent.click(toggle);
    expect(screen.getByRole("link", { name: /Lucali in 30 seconds/ })).toBeTruthy();
  });

  it("stay in the list on their own when the cover is not listed", async () => {
    renderAt("/kept", [covered]);
    expect(await screen.findByRole("link", { name: /Lucali in 30 seconds/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /more say/ })).toBeNull();
  });
});

describe("item organization", () => {
  const organization = {
    gist: "Adobada tacos.",
    key_points: ["Go before noon."],
    labels: ["tacos"],
    topic: { id: 3, name: "NYC restaurants" },
    sift_topic: null,
    topic_chosen_by: "sift" as const,
    covered_by: null,
    covers: [],
    cited_in: 0,
  };

  it("moves the post to the chosen topic, and back to Sift's pick", async () => {
    const bodies: unknown[] = [];
    route("GET /api/items/1", () => detail({ organization }));
    route("PUT /api/items/1/topic", async (request) => {
      bodies.push(await request.json());
      return organization;
    });
    renderAt("/items/1");
    const picker = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Topic" });
    await waitFor(() => expect(picker.options).toHaveLength(2));

    await userEvent.selectOptions(picker, "3");
    await userEvent.selectOptions(picker, "");
    await waitFor(() => expect(bodies).toEqual([{ topic_id: 3 }, { topic_id: null }]));
  });

  it("says a move back to Sift's pick went back, without a topic when Sift has none", async () => {
    route("GET /api/items/1", () => detail({ organization: { ...organization, topic_chosen_by: "you" } }));
    route("PUT /api/items/1/topic", () => ({ ...organization, topic: null, topic_chosen_by: null }));
    renderAt("/items/1");
    const picker = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Topic" });
    await waitFor(() => expect(picker.value).toBe("3"));
    await userEvent.selectOptions(picker, "");
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Back to Sift's pick"));
  });
});

describe("the Move to sheet", () => {
  const organization: ItemOrganization = {
    gist: "Adobada tacos.",
    key_points: [],
    labels: [],
    topic: { id: 3, name: "NYC restaurants" },
    sift_topic: { id: 3, name: "NYC restaurants" },
    topic_chosen_by: "sift",
    covered_by: null,
    covers: [],
    cited_in: 0,
  };

  function renderItem(org = organization) {
    const bodies: unknown[] = [];
    route("GET /api/items/1", () => detail({ organization: org }));
    route("PUT /api/items/1/topic", async (request) => {
      bodies.push(await request.json());
      return org;
    });
    renderAt("/items/1");
    route("GET /api/topics", () => ({
      groups: [],
      suggestions: [],
      options: [
        { id: 3, name: "NYC restaurants" },
        { id: 5, name: "Date night" },
        { id: 7, name: "Pizza" },
      ],
    }));
    return bodies;
  }

  const sheet = async () => {
    await userEvent.click(await screen.findByRole("button", { name: "Move to..." }));
    return screen.findByRole("dialog", { name: "Move to" });
  };

  it("lists Sift's pick, marked as current, and every other live topic", async () => {
    renderItem();
    const dialog = await sheet();
    await within(dialog).findByRole("button", { name: /Date night/ });
    const choices = within(dialog).getAllByRole("button", { name: /^(?!Close)/ });
    expect(choices.map((b) => b.textContent)).toEqual(["Sift's pickNYC restaurants", "Date night", "Pizza"]);
    expect(choices.map((b) => b.getAttribute("aria-current"))).toEqual(["true", null, null]);
  });

  it("sends the chosen topic, then null for Sift's pick, closing after each", async () => {
    const bodies = renderItem({ ...organization, topic: { id: 5, name: "Date night" }, topic_chosen_by: "you" });
    let dialog = await sheet();
    expect(
      within(dialog)
        .getByRole("button", { name: /Date night/ })
        .getAttribute("aria-current"),
    ).toBe("true");
    await userEvent.click(within(dialog).getByRole("button", { name: /Pizza/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    dialog = await sheet();
    await userEvent.click(within(dialog).getByRole("button", { name: /Sift's pick/ }));
    await waitFor(() => expect(bodies).toEqual([{ topic_id: 7 }, { topic_id: null }]));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("says a move back to Sift's pick went back, naming Sift's topic when it has one", async () => {
    renderItem({ ...organization, topic_chosen_by: "you", topic: { id: 5, name: "Date night" } });
    route("PUT /api/items/1/topic", () => organization);
    await userEvent.click(within(await sheet()).getByRole("button", { name: /Sift's pick/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Back to Sift's pick: NYC restaurants"));
  });
});
