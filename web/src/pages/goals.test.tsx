import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "@/api";
import { route } from "@/test/fake-api";
import { status } from "@/test/fixtures";
import { createAppRouter } from "../router";

function renderGoals() {
  window.history.replaceState(null, "", "/goals");
  route("GET /api/status", () => status());
  route("GET /api/goals", () => []);
  route("GET /api/values", () => ({ values_text: "" }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter(queryClient)} />
    </QueryClientProvider>,
  );
}

describe("goals", () => {
  it("stops a goal's reason and the values at the lengths the API accepts", async () => {
    renderGoals();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add a goal by hand" }));
    await user.click(screen.getByLabelText("Why it matters"));
    await user.paste("w".repeat(700));
    expect((screen.getByLabelText("Why it matters") as HTMLTextAreaElement).value).toHaveLength(600);
    await user.click(screen.getByLabelText("What you care about, and what counts as noise"));
    await user.paste("v".repeat(4100));
    const values = screen.getByLabelText("What you care about, and what counts as noise") as HTMLTextAreaElement;
    expect(values.value).toHaveLength(4000);
  });
});
