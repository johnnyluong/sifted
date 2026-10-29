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
  it("shows this server's two addresses, and says a local address works only on this computer", async () => {
    renderShare();
    const links = await screen.findByLabelText<HTMLInputElement>("Link address");
    expect(links.value).toBe("http://localhost:5173/api/items");
    expect(screen.getByLabelText<HTMLInputElement>("Image address").value).toBe("http://localhost:5173/api/uploads");
    expect(screen.getByText(/work only on this computer/)).toBeTruthy();
  });

  it.each([
    ["link", "http://localhost:5173/api/items"],
    ["image", "http://localhost:5173/api/uploads"],
  ])("copies the %s address", async (kind, address) => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderShare();
    await userEvent.click(await screen.findByRole("button", { name: `Copy the ${kind} address` }));
    expect(writeText).toHaveBeenCalledWith(address);
    await waitFor(() => expect(toast).toHaveBeenCalledWith(`Copied the ${kind} address`));
  });

  it("checks for a link first, so a shared web page is saved as a link and only images go to the image address", async () => {
    renderShare();
    const steps =
      (await screen.findByRole("heading", { name: "Build the shortcut" })).closest("section")?.textContent ?? "";
    const order = [
      "Get URLs from Input",
      "URLs has any value",
      "link address",
      "JSON",
      "Otherwise",
      "Get Images from Input",
      "Repeat with Each",
      "image address",
      "File",
      "End If",
    ];
    const at = order.map((phrase) => steps.indexOf(phrase));
    expect(
      at.every((i) => i >= 0),
      String(at),
    ).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });

  it("says to copy by hand when the browser refuses the clipboard", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) },
    });
    renderShare();
    await userEvent.click(await screen.findByRole("button", { name: "Copy the link address" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't copy. Select the address and copy it."));
  });
});
