import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createQueryClient } from "@/api/query-client";
import { holdText, ImportManifest } from "@/pages/import";
import { route } from "@/test/fake-api";
import { importView } from "@/test/fixtures";

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const priced: number[] = [];

function renderManifest(view = importView()) {
  const sent: unknown[] = [];
  priced.length = 0;
  route("POST /api/imports/1/actions/start", async (request) => {
    sent.push(await request.json());
    return importView({ phase: "running" });
  });
  route("GET /api/imports/1/estimate", (request) => {
    const posts = Number(new URL(request.url).searchParams.get("limit"));
    priced.push(posts);
    return { posts, usd: posts === 3 ? 0.07 : 9.99, seconds: posts * 180 };
  });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <ImportManifest view={view} />
    </QueryClientProvider>,
  );
  return sent;
}

describe("the import preview", () => {
  it("reads as a ledger: saved, minus what Sift has or can't read, equals new", () => {
    renderManifest();
    const value = (label: string) => screen.getByText(label).parentElement?.previousElementSibling?.textContent;
    expect(value("saved posts")).toBe("417");
    expect(value("already in Sift")).toBe("37");
    expect(value("links Sift can't read")).toBe("5");
    expect(value("new, newest first")).toBe("375");
    expect(screen.getByText("380 Instagram · 32 Threads")).toBeTruthy();
  });

  it("starts the server's preselected Newest 100 by default", async () => {
    const sent = renderManifest();
    expect(screen.getByRole("radio", { name: /Newest 100/ })).toHaveProperty("checked", true);
    await userEvent.click(screen.getByRole("button", { name: "Import the newest 100" }));
    await waitFor(() => expect(sent).toEqual([{ limit: 100 }]));
  });

  it("sends null for All, and the typed number for Newest N with its own estimate", async () => {
    const sent = renderManifest();
    await userEvent.click(screen.getByRole("radio", { name: /All 375/ }));
    await userEvent.click(screen.getByRole("button", { name: "Import all 375" }));
    await waitFor(() => expect(sent).toEqual([{ limit: null }]));

    const field = screen.getByRole("spinbutton", { name: "Import the newest this many posts" });
    await userEvent.clear(field);
    await userEvent.type(field, "3");
    expect(await screen.findByText("$0.07")).toBeTruthy();
    expect(priced.at(-1)).toBe(3);
    await userEvent.click(screen.getByRole("button", { name: "Import the newest 3" }));
    await waitFor(() => expect(sent).toEqual([{ limit: null }, { limit: 3 }]));
  });

  it("asks the server to price Newest N once typing settles, not per keystroke", async () => {
    renderManifest();
    await screen.findByText("$9.99");
    const field = screen.getByRole("spinbutton", { name: "Import the newest this many posts" });
    await userEvent.clear(field);
    await userEvent.type(field, "123");
    await waitFor(() => expect(priced.at(-1)).toBe(123));
    expect(priced).toEqual([25, 123]);
  });

  it("names the saved files it skipped for size", () => {
    renderManifest(importView({ files_skipped_large: ["saved/saved_collections.json"] }));
    expect(screen.getByText("Skipped").nextElementSibling?.textContent).toBe(
      "saved/saved_collections.json (too large)",
    );
  });

  it("says which saved files the total read limit left unread", () => {
    renderManifest(importView({ files_skipped_budget: ["saved/saved_collections.json"] }));
    expect(screen.getByText("Not read").nextElementSibling?.textContent).toBe(
      "saved/saved_collections.json (over the 256 MB total)",
    );
    expect(screen.queryByText("Skipped")).toBeNull();
  });

  it("offers only Discard when nothing is new", () => {
    renderManifest(importView({ counts: { ...importView().counts, found: 0 }, options: [], actions: ["cancel"] }));
    expect(screen.getByText("Everything in this export is already in Sift.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Import/ })).toBeNull();
  });
});

describe("holdText", () => {
  const now = new Date("2026-10-23T14:00:00Z");

  it("counts down the gap and names the clock time for the daily cap", () => {
    expect(holdText({ hold: "gap", hold_until: "2026-10-23T14:02:10Z" }, now, "UTC")).toBe("Next post in 2m 10s");
    expect(holdText({ hold: "daily_cap", hold_until: "2026-10-24T09:40:00Z" }, now, "UTC")).toBe(
      "Daily limit reached. Resumes Oct 24, 9:40 AM",
    );
    expect(holdText({ hold: "in_flight", hold_until: null }, now, "UTC")).toBe(
      "Waiting for the current post to finish",
    );
    expect(holdText({ hold: null, hold_until: null }, now, "UTC")).toBeNull();
  });
});
