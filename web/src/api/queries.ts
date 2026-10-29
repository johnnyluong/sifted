import { queryOptions } from "@tanstack/react-query";
import { http, unwrap } from "./client";
import type { ItemStatus, ItemType, ShelfId, Status } from "./types";

export type ListView = ShelfId;

export type ListFilter = ({ view: ListView } | { status: readonly ItemStatus[] }) & {
  q?: string;
  goal?: number;
  type?: ItemType;
  topic?: number;
  label?: string;
};

export const BUSY_POLL_MS = 1_500;
export const IDLE_POLL_MS = 15_000;

export function pollMs(status: Status | undefined): number {
  return status?.pulse.busy ? BUSY_POLL_MS : IDLE_POLL_MS;
}

export const api = {
  status: queryOptions({
    queryKey: ["status"],
    queryFn: () => unwrap(http.GET("/api/status")),
    staleTime: 0,
    refetchInterval: (query) => pollMs(query.state.data),
  }),

  items: (filter: ListFilter) =>
    queryOptions({
      queryKey: ["items", filter],
      queryFn: () =>
        unwrap(
          http.GET("/api/items", {
            params: {
              query: {
                view: "view" in filter ? filter.view : undefined,
                status: "status" in filter ? [...filter.status] : undefined,
                q: filter.q,
                goal_id: filter.goal,
                type: filter.type,
                topic_id: filter.topic,
                label: filter.label,
              },
            },
          }),
        ),
    }),

  item: (id: number) =>
    queryOptions({
      queryKey: ["item", id],
      queryFn: () => unwrap(http.GET("/api/items/{item_id}", { params: { path: { item_id: id } } })),
    }),

  topics: queryOptions({ queryKey: ["topics"], queryFn: () => unwrap(http.GET("/api/topics")) }),

  topic: (id: number) =>
    queryOptions({
      queryKey: ["topic", id],
      queryFn: () => unwrap(http.GET("/api/topics/{topic_id}", { params: { path: { topic_id: id } } })),
    }),

  labels: (topic?: number) =>
    queryOptions({
      queryKey: ["labels", topic],
      queryFn: () => unwrap(http.GET("/api/labels", { params: { query: { topic_id: topic } } })),
    }),

  goals: queryOptions({ queryKey: ["goals"], queryFn: () => unwrap(http.GET("/api/goals")) }),

  values: queryOptions({ queryKey: ["values"], queryFn: () => unwrap(http.GET("/api/values")) }),

  setup: queryOptions({ queryKey: ["setup"], queryFn: () => unwrap(http.GET("/api/setup")) }),

  digests: queryOptions({ queryKey: ["digests"], queryFn: () => unwrap(http.GET("/api/digests")) }),

  imports: queryOptions({ queryKey: ["imports"], queryFn: () => unwrap(http.GET("/api/imports")) }),

  importEstimate: (id: number, limit: number) =>
    queryOptions({
      queryKey: ["import-estimate", id, limit],
      queryFn: () =>
        unwrap(
          http.GET("/api/imports/{import_id}/estimate", { params: { path: { import_id: id }, query: { limit } } }),
        ),
    }),

  digest: (id: number) =>
    queryOptions({
      queryKey: ["digest", id],
      queryFn: () => unwrap(http.GET("/api/digests/{digest_id}", { params: { path: { digest_id: id } } })),
    }),

  topicDigest: (id: number) =>
    queryOptions({
      queryKey: ["topic-digest", id],
      queryFn: () => unwrap(http.GET("/api/digests/topics/{topic_id}", { params: { path: { topic_id: id } } })),
    }),
};
