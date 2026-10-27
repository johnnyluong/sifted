import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "@/api";
import { route } from "@/test/fake-api";
import { status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock("sonner", () => ({ toast, Toaster: () => null }));

afterEach(() => {
  vi.unstubAllGlobals();
  toast.mockClear();
  toast.error.mockClear();
});

function renderShare() {
  window.history.replaceState(null, "", "/share");
  route("GET /api/status", () => status());
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter(queryClient)} />
    </QueryClientProvider>,
  );
}

describe("the Save from iPhone page", () => {
  it("shows this server's endpoint, and says a local address works only on this computer", async () => {
    renderShare();
    const endpoint = await screen.findByLabelText<HTMLInputElement>("Address for the shortcut");
    expect(endpoint.value).toBe("http://localhost:5173/api/items");
    expect(screen.getByText(/works only on this computer/)).toBeTruthy();
  });

  it("copies the endpoint", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderShare();
    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("http://localhost:5173/api/items");
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Copied the address"));
  });

  it("says to copy by hand when the browser refuses the clipboard", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) },
    });
    renderShare();
    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't copy. Select the address and copy it."));
  });
});
