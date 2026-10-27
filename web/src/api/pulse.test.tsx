import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { type ReactNode, Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ItemDetail } from "@/api";
import { settledIds, usePulse } from "@/api/pulse";
import { api, BUSY_POLL_MS, IDLE_POLL_MS, pollMs } from "@/api/queries";
import { createQueryClient } from "@/api/query-client";
import { callCount, route } from "@/test/fake-api";
import { detail, item, status } from "@/test/fixtures";

function setup(onSettle: (item: ItemDetail) => void = () => undefined) {
  const queryClient = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
  const view = renderHook(
    () => {
      usePulse(onSettle);
      return useQuery(api.items({ view: "inbox" }));
    },
    { wrapper },
  );
  const refetchStatus = () => act(() => queryClient.refetchQueries({ queryKey: api.status.queryKey }));
  return { view, refetchStatus };
}

describe("pulse", () => {
  it("refetches the lists on screen when the revision changes, and only then", async () => {
    let revision = "r1";
    route("GET /api/status", () => status({ revision }));
    route("GET /api/items", () => [item()]);
    const { view, refetchStatus } = setup();
    await waitFor(() => expect(view.result.current.data).toHaveLength(1));
    expect(callCount("GET /api/items")).toBe(1);

    await refetchStatus();
    expect(callCount("GET /api/items")).toBe(1);

    revision = "r2";
    await refetchStatus();
    await waitFor(() => expect(callCount("GET /api/items")).toBe(2));
  });

  it("announces an item once it leaves in_motion, and not on the first load", async () => {
    const moving = { id: 7, state_label: "Scoring", stage: "score" as const, announce: true };
    let current = status({ revision: "r1", busy: true, in_motion: [moving] });
    route("GET /api/status", () => current);
    route("GET /api/items", () => []);
    route("GET /api/items/7", () => detail({ id: 7, title: "Lucali", relevance_score: 86 }));
    const onSettle = vi.fn();
    const { view, refetchStatus } = setup(onSettle);
    await waitFor(() => expect(view.result.current.data).toEqual([]));
    expect(onSettle).not.toHaveBeenCalled();

    current = status({ revision: "r2", in_motion: [] });
    await refetchStatus();
    await waitFor(() => expect(onSettle).toHaveBeenCalledTimes(1));
    expect(onSettle.mock.calls[0]?.[0]).toMatchObject({ id: 7, title: "Lucali", relevance_score: 86 });
  });

  it("does not announce imported posts, which settle one every few minutes", () => {
    const quiet = { id: 8, state_label: "Scoring", stage: "score" as const, announce: false };
    const loud = { id: 9, state_label: "Scoring", stage: "score" as const, announce: true };
    expect(settledIds(status({ in_motion: [quiet, loud] }), status({ in_motion: [] }))).toEqual([9]);
  });

  it("polls fast only while the server is busy", () => {
    expect(pollMs(status({ busy: true }))).toBe(BUSY_POLL_MS);
    expect(pollMs(status({ busy: false }))).toBe(IDLE_POLL_MS);
    expect(pollMs(undefined)).toBe(IDLE_POLL_MS);
  });
});
