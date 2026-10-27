import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { X } from "lucide-react";
import { type JSX, useEffect, useRef, useState } from "react";
import { api, ITEM_TYPES } from "@/api";
import { ItemList } from "@/components/item-list";
import { Empty, Page, PageHeader } from "@/components/page";
import { isEditable } from "@/components/paste-box";
import { Input, Select } from "@/components/ui/field";
import { type LibrarySearch, parseLibrarySearch } from "@/lib/search";
import { TYPES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const keptRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/kept",
  validateSearch: parseLibrarySearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps }) => context.queryClient.ensureQueryData(api.items({ view: "kept", ...deps })),
  component: KeptPage,
});

export const archivedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/archived",
  validateSearch: parseLibrarySearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps }) => context.queryClient.ensureQueryData(api.items({ view: "archived", ...deps })),
  component: ArchivedPage,
});

type View = "kept" | "archived";

const COPY: Record<View, { title: string; subtitle: string; swipe: string; emptyTitle: string; empty: string }> = {
  kept: {
    title: "Kept",
    subtitle: "Posts that serve your goals. Mark them done once you've acted.",
    swipe: "Swipe right to mark done, left to archive.",
    emptyTitle: "Nothing kept yet",
    empty: "Posts that serve a goal land here.",
  },
  archived: {
    title: "Archived",
    subtitle: "Filtered out as noise. Nothing is deleted; keep anything the filter got wrong.",
    swipe: "Swipe right to keep.",
    emptyTitle: "Nothing archived",
    empty: "Posts that miss your goals land here, with the reason.",
  },
};

function KeptPage(): JSX.Element {
  return <LibraryPage view="kept" search={useSearch({ from: "/kept" })} />;
}

function ArchivedPage(): JSX.Element {
  return <LibraryPage view="archived" search={useSearch({ from: "/archived" })} />;
}

function LibraryPage({ view, search }: { view: View; search: LibrarySearch }): JSX.Element {
  const { data: items } = useSuspenseQuery(api.items({ view, ...search }));
  const copy = COPY[view];
  const filtered = Boolean(search.q || search.goal || search.type || search.topic || search.label);
  return (
    <Page>
      <PageHeader
        title={copy.title}
        subtitle={
          <>
            {copy.subtitle} <span className="hidden max-[700px]:inline">{copy.swipe}</span>
          </>
        }
        aside={
          <span className="font-mono text-caption text-silt">
            {items.length} {items.length === 1 ? "item" : "items"}
          </span>
        }
      />
      <LibraryFilters view={view} search={search} />
      <ItemList
        items={items}
        variant="library"
        empty={
          filtered ? (
            <Empty title="No matches">Clear the filters or try other words.</Empty>
          ) : (
            <Empty title={copy.emptyTitle}>{copy.empty}</Empty>
          )
        }
      />
    </Page>
  );
}

function LibraryFilters({ view, search }: { view: View; search: LibrarySearch }): JSX.Element {
  const navigate = useNavigate();
  const { data: goals = [] } = useQuery(api.goals);
  const topics = useQuery(api.topics).data?.options ?? [];
  const urlQ = search.q ?? "";
  const [q, setQ] = useState(urlQ);
  const [seenQ, setSeenQ] = useState(urlQ);
  // The URL reports our write only once its loader resolves, so typing may have moved on by then.
  const [writtenQ, setWrittenQ] = useState(urlQ);
  const box = useRef<HTMLInputElement>(null);
  const update = (patch: LibrarySearch) =>
    navigate({ to: `/${view}`, search: (s: LibrarySearch) => ({ ...s, ...patch }), replace: true });

  if (urlQ !== seenQ) {
    setSeenQ(urlQ);
    if (urlQ !== writtenQ) {
      setWrittenQ(urlQ);
      if (urlQ !== q.trim()) setQ(urlQ);
    }
  }

  useEffect(() => {
    const next = q.trim();
    if (next === writtenQ) return;
    const timer = setTimeout(() => {
      setWrittenQ(next);
      update({ q: next || undefined });
    }, 200);
    return () => clearTimeout(timer);
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || isEditable(event.target)) return;
      event.preventDefault();
      box.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="mb-9 flex flex-wrap gap-2">
      <Input
        ref={box}
        type="search"
        aria-label="Search"
        placeholder="Search titles, summaries, transcripts"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="flex-1 max-[700px]:basis-full"
      />
      <Select
        aria-label="Goal"
        value={search.goal ?? ""}
        onChange={(e) => update({ goal: e.target.value ? Number(e.target.value) : undefined })}
        className="max-w-[220px] max-[700px]:max-w-none max-[700px]:flex-1 [&>select]:w-full"
      >
        <option value="">All goals</option>
        {goals.map((g) => (
          <option key={g.id} value={g.id}>
            {g.title}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Topic"
        value={search.topic ?? ""}
        onChange={(e) => update({ topic: e.target.value ? Number(e.target.value) : undefined })}
        className="max-w-[200px] max-[700px]:max-w-none max-[700px]:flex-1 [&>select]:w-full"
      >
        <option value="">All topics</option>
        {topics.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Type"
        value={search.type ?? ""}
        onChange={(e) => update({ type: ITEM_TYPES.find((t) => t === e.target.value) })}
        className="max-[700px]:flex-1 [&>select]:w-full"
      >
        <option value="">All types</option>
        {ITEM_TYPES.map((t) => (
          <option key={t} value={t}>
            {TYPES[t].label}
          </option>
        ))}
      </Select>
      {search.label && (
        <button
          type="button"
          aria-label={`Clear label ${search.label}`}
          onClick={() => update({ label: undefined })}
          className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full border border-graphite bg-sheet pr-2.5 pl-3 text-[13px] max-[700px]:h-11"
        >
          {search.label}
          <X aria-hidden className="size-3.5 text-silt" />
        </button>
      )}
    </div>
  );
}
