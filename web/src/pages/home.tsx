import { createRoute, redirect } from "@tanstack/react-router";
import { api } from "@/api";
import { rootRoute } from "./root";

export const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: async ({ context }) => {
    const status = await context.queryClient.ensureQueryData(api.status);
    if (status.active_goals === 0) throw redirect({ to: "/setup", replace: true });
    throw redirect({ to: status.has_digest ? "/digests" : "/inbox", replace: true });
  },
});
