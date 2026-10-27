export type Keyed<T> = { key: string; row: T };

export function keyByText<T>(rows: readonly T[], text: (row: T) => string): Keyed<T>[] {
  const seen = new Map<string, number>();
  return rows.map((row) => {
    const t = text(row);
    const n = (seen.get(t) ?? 0) + 1;
    seen.set(t, n);
    return { key: `${n}:${t}`, row };
  });
}
