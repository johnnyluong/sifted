import type { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { digestRoute, digestsRoute } from "./pages/digests";
import { goalsRoute } from "./pages/goals";
import { homeRoute } from "./pages/home";
import { importRoute } from "./pages/import";
import { inboxRoute } from "./pages/inbox";
import { itemRoute } from "./pages/item";
import { archivedRoute, keptRoute } from "./pages/library";
import { rootRoute } from "./pages/root";
import { setupRoute } from "./pages/setup";
import { shareRoute } from "./pages/share";
import { topicRoute, topicsRoute } from "./pages/topics";

const routeTree = rootRoute.addChildren([
  homeRoute,
  inboxRoute,
  keptRoute,
  archivedRoute,
  itemRoute,
  topicsRoute,
  topicRoute,
  goalsRoute,
  setupRoute,
  importRoute,
  shareRoute,
  digestsRoute,
  digestRoute,
]);

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    // Loaders call ensureQueryData, so TanStack Query's staleTime decides freshness, not the router.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
