import { describe, expect, it } from "vitest";
import type { BriefSource } from "@/api";
import { groupFolds, nestSources } from "@/lib/folds";
import { item } from "@/test/fixtures";

const ref = (id: number) => ({ id, title: `Post ${id}` });
const ids = (groups: ReturnType<typeof groupFolds>) => groups.map((g) => [g.row.id, g.under.map((u) => u.id)]);

describe("groupFolds", () => {
  it("nests covered rows under a listed cover, in list order, and keeps the top-level order", () => {
    const rows = [
      item({ id: 5, covered_by: ref(2) }),
      item({ id: 2 }),
      item({ id: 9 }),
      item({ id: 7, covered_by: ref(2) }),
    ];
    expect(ids(groupFolds(rows))).toEqual([
      [2, [5, 7]],
      [9, []],
    ]);
  });

  it("leaves a covered row at the top level when its cover is not in the list", () => {
    expect(ids(groupFolds([item({ id: 3, covered_by: ref(40) }), item({ id: 4 })]))).toEqual([
      [3, []],
      [4, []],
    ]);
  });

  it("nests one level only, so a chain keeps every row on screen", () => {
    const rows = [item({ id: 1 }), item({ id: 2, covered_by: ref(1) }), item({ id: 3, covered_by: ref(2) })];
    expect(ids(groupFolds(rows))).toEqual([
      [1, [2]],
      [3, []],
    ]);
  });
});

describe("nestSources", () => {
  const source = (n: number, covered_by: number | null = null): BriefSource => ({
    n,
    covered_by,
    current: true,
    item: ref(n * 10),
    item_type: "place",
    thumbnail_url: null,
  });

  it("indents a source under the footnote that covers it", () => {
    const groups = nestSources([source(1), source(2, 1), source(3), source(4, 1)]);
    expect(groups.map((g) => [g.row.n, g.under.map((u) => u.n)])).toEqual([
      [1, [2, 4]],
      [3, []],
    ]);
  });
});
