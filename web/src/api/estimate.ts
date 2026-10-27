import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./queries";
import type { Estimate } from "./types";

export const ESTIMATE_DEBOUNCE_MS = 250;

export function useImportEstimate(id: number, limit: number): Estimate | undefined {
  const [settled, setSettled] = useState(limit);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(limit), ESTIMATE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [limit]);
  return useQuery({ ...api.importEstimate(id, settled), placeholderData: keepPreviousData }).data;
}
