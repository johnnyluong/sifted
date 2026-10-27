import { useMutation, useQueryClient } from "@tanstack/react-query";
import { http, unwrap } from "./client";
import { api } from "./queries";
import type { GoalCreate, GoalPatch, ImportAction, SetupAnswer, SetupApply, UserAction } from "./types";

const quiet = { quietErrors: true };

export function useSubmitLinks() {
  return useMutation({
    mutationFn: (text: string) => unwrap(http.POST("/api/items", { body: { text, channel: "web" } })),
    meta: quiet,
  });
}

export function useItemAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: UserAction }) =>
      unwrap(http.POST("/api/items/{item_id}/actions/{action}", { params: { path: { item_id: id, action } } })),
    onSuccess: (detail) => queryClient.setQueryData(api.item(detail.id).queryKey, detail),
  });
}

export function useCreateGoal() {
  return useMutation({ mutationFn: (body: GoalCreate) => unwrap(http.POST("/api/goals", { body })), meta: quiet });
}

export function useUpdateGoal() {
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: GoalPatch }) =>
      unwrap(http.PATCH("/api/goals/{goal_id}", { params: { path: { goal_id: id } }, body: patch })),
    meta: quiet,
  });
}

export function useSaveValues() {
  return useMutation({
    mutationFn: (values_text: string) => unwrap(http.PUT("/api/values", { body: { values_text } })),
    meta: quiet,
  });
}

export function useDraftSetup() {
  return useMutation({
    mutationFn: (answers: SetupAnswer[]) => unwrap(http.POST("/api/setup/draft", { body: { answers } })),
    meta: quiet,
  });
}

export function useApplySetup() {
  return useMutation({
    mutationFn: (body: SetupApply) => unwrap(http.POST("/api/setup/apply", { body })),
    meta: quiet,
  });
}

export function useGenerateDigest() {
  return useMutation({ mutationFn: () => unwrap(http.POST("/api/digests")), meta: quiet });
}

export function useUploadImport() {
  return useMutation({
    mutationFn: (file: File) =>
      unwrap(
        http.POST("/api/imports", {
          params: { query: { filename: file.name } },
          body: file,
          bodySerializer: (body) => body,
          headers: { "Content-Type": "application/zip" },
        }),
      ),
    meta: quiet,
  });
}

export function useImportAction() {
  return useMutation({
    mutationFn: ({ id, action, limit }: { id: number; action: ImportAction; limit?: number | null }) =>
      unwrap(
        http.POST("/api/imports/{import_id}/actions/{action}", {
          params: { path: { import_id: id, action } },
          body: action === "start" ? { limit: limit ?? null } : undefined,
        }),
      ),
  });
}

export function useSetItemTopic() {
  return useMutation({
    mutationFn: ({ id, topic }: { id: number; topic: number | null }) =>
      unwrap(http.PUT("/api/items/{item_id}/topic", { params: { path: { item_id: id } }, body: { topic_id: topic } })),
  });
}

export function useRenameTopic() {
  return useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      unwrap(http.PATCH("/api/topics/{topic_id}", { params: { path: { topic_id: id } }, body: { name } })),
    meta: quiet,
  });
}

export function useMergeTopic() {
  return useMutation({
    mutationFn: ({ id, into }: { id: number; into: number }) =>
      unwrap(
        http.POST("/api/topics/{topic_id}/merge", { params: { path: { topic_id: id } }, body: { into_id: into } }),
      ),
  });
}

export function useDissolveTopic() {
  return useMutation({
    mutationFn: (id: number) => unwrap(http.DELETE("/api/topics/{topic_id}", { params: { path: { topic_id: id } } })),
  });
}

export function useDismissSuggestion() {
  return useMutation({
    mutationFn: ({ id, into }: { id: number; into: number }) =>
      unwrap(
        http.POST("/api/topics/{topic_id}/suggestions/{into_id}/dismiss", {
          params: { path: { topic_id: id, into_id: into } },
        }),
      ),
  });
}

export function useRequestBrief() {
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(http.POST("/api/topics/{topic_id}/brief", { params: { path: { topic_id: id } } })),
  });
}
