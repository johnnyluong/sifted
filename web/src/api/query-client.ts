import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "./client";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      quietErrors?: boolean;
    };
  }
}

export function createQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
      },
    },
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (!mutation.meta?.quietErrors) toast.error(error.message);
      },
      // On settle, not success, so a 409 still redraws the screen; the returned promise keeps the button pending.
      onSettled: () => queryClient.invalidateQueries(),
    }),
  });
  return queryClient;
}
