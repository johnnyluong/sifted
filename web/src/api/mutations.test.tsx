import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useItemAction, useSaveValues } from "@/api/mutations";
import { api } from "@/api/queries";
import { createQueryClient } from "@/api/query-client";
import { callCount, route } from "@/test/fake-api";
import { detail, item } from "@/test/fixtures";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

afterEach(() => vi.mocked(toast.error).mockClear());

function setup() {
  const queryClient = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const view = renderHook(
    () => ({ list: useQuery(api.items({ view: "kept" })), act: useItemAction(), save: useSaveValues() }),
    { wrapper },
  );
  return { queryClient, view };
}

describe("writes", () => {
  it("refetch the lists on screen after a success, and keep the returned item", async () => {
    route("GET /api/items", () => [item()]);
    route("POST /api/items/1/actions/archive", () => detail({ status: "archived", state_label: "Archived" }));
    const { queryClient, view } = setup();
    await waitFor(() => expect(view.result.current.list.data).toHaveLength(1));

    await act(() => view.result.current.act.mutateAsync({ id: 1, action: "archive" }));
    expect(callCount("GET /api/items")).toBe(2);
    expect(queryClient.getQueryData(api.item(1).queryKey)?.status).toBe("archived");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("still refetch after a 409, and toast the server's sentence", async () => {
    route("GET /api/items", () => [item()]);
    route("POST /api/items/1/actions/keep", () => {
      throw { status: 409, detail: "cannot keep an item that is kept" };
    });
    const { view } = setup();
    await waitFor(() => expect(view.result.current.list.data).toHaveLength(1));

    await act(() => view.result.current.act.mutateAsync({ id: 1, action: "keep" }).catch(() => undefined));
    expect(callCount("GET /api/items")).toBe(2);
    expect(toast.error).toHaveBeenCalledWith("cannot keep an item that is kept");
  });

  it("leave the error to forms that show it themselves", async () => {
    route("PUT /api/values", () => {
      throw { status: 422, detail: "Field required" };
    });
    const { view } = setup();
    await act(() => view.result.current.save.mutateAsync("x").catch(() => undefined));
    await waitFor(() => expect(view.result.current.save.error?.message).toBe("Field required"));
    expect(toast.error).not.toHaveBeenCalled();
  });
});
