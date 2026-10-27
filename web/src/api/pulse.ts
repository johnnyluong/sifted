import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useEffect, useEffectEvent, useRef } from "react";
import { api } from "./queries";
import type { ItemDetail, Status } from "./types";

export function usePulse(onSettle: (item: ItemDetail) => void): Status {
  const queryClient = useQueryClient();
  const { data } = useSuspenseQuery(api.status);
  const seen = useRef(data);
  const announce = useEffectEvent(onSettle);

  useEffect(() => {
    const before = seen.current;
    if (before === data) return;
    seen.current = data;
    if (before.pulse.revision !== data.pulse.revision) {
      void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== api.status.queryKey[0] });
    }
    for (const id of settledIds(before, data)) {
      queryClient.fetchQuery({ ...api.item(id), staleTime: 0 }).then(announce, () => undefined);
    }
  }, [data, queryClient]);

  return data;
}

export function settledIds(before: Status, after: Status): number[] {
  const still = new Set(after.in_motion.map((m) => m.id));
  return before.in_motion.filter((m) => m.announce && !still.has(m.id)).map((m) => m.id);
}

export function useStatus(): Status {
  return useSuspenseQuery(api.status).data;
}
