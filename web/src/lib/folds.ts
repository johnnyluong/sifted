import type { BriefSource, Item } from "@/api";

export type Nested<T> = { row: T; under: T[] };

export function nestUnder<T>(
  rows: readonly T[],
  id: (row: T) => number,
  parent: (row: T) => number | null,
): Nested<T>[] {
  const byId = new Map(rows.map((row) => [id(row), row]));
  const parentRow = (row: T): T | undefined => {
    const p = parent(row);
    return p === null ? undefined : byId.get(p);
  };
  const host = (row: T): T | undefined => {
    const p = parentRow(row);
    return p && !parentRow(p) ? p : undefined;
  };
  const groups = new Map<T, Nested<T>>();
  for (const row of rows) if (!host(row)) groups.set(row, { row, under: [] });
  for (const row of rows) {
    const h = host(row);
    if (h) groups.get(h)?.under.push(row);
  }
  return [...groups.values()];
}

export function groupFolds(items: readonly Item[]): Nested<Item>[] {
  return nestUnder(
    items,
    (item) => item.id,
    (item) => item.covered_by?.id ?? null,
  );
}

export function nestSources(sources: readonly BriefSource[]): Nested<BriefSource>[] {
  return nestUnder(
    sources,
    (source) => source.n,
    (source) => source.covered_by,
  );
}
