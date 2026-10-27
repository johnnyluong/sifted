import type { Import } from "@/api";

export function formatDuration(seconds: number): string {
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (hours < 48) return `${roundHalf(hours)} ${roundHalf(hours) === "1" ? "hour" : "hours"}`;
  return `${roundHalf(hours / 24)} days`;
}

export function formatGap(seconds: number): string {
  if (seconds < 60) return `${seconds} seconds`;
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "minute" : `${minutes} minutes`;
}

function roundHalf(n: number): string {
  const r = Math.round(n * 2) / 2;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

export function formatUsd(usd: number): string {
  return `$${usd.toFixed(2)}`;
}

export function formatPerPost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

export function formatCountdown(untilIso: string, now: Date): string {
  const s = Math.max(0, Math.round((new Date(untilIso).getTime() - now.getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

export function activeImport(imports: Import[]): Import | undefined {
  const active = imports.filter((v) => v.phase === "running" || v.phase === "paused");
  return active.reduce<Import | undefined>(
    (oldest, v) => (oldest === undefined || v.id < oldest.id ? v : oldest),
    undefined,
  );
}

export function progress(view: Pick<Import, "counts">): { done: number; total: number } {
  const { released, waiting } = view.counts;
  return { done: released, total: released + waiting };
}
