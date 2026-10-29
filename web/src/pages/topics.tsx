import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link, Navigate, notFound, useParams, useSearch } from "@tanstack/react-router";
import { type CSSProperties, type JSX, useState } from "react";
import { toast } from "sonner";
import {
  ApiError,
  api,
  type ItemStatus,
  type LabelCount,
  type MergeSuggestion,
  type Topic,
  type TopicDetail,
  useDismissSuggestion,
  useMergeTopic,
  useRequestBrief,
  useStatus,
} from "@/api";
import { BriefBody, SourceLedger } from "@/components/brief";
import { Section } from "@/components/card-body";
import { ItemList } from "@/components/item-list";
import { BackLink, Empty, Page, PageHeader } from "@/components/page";
import { ThresholdLine } from "@/components/score-rail";
import { NewTopicSheet, TopicSheet } from "@/components/topic-sheet";
import { Button, chipClass } from "@/components/ui/button";
import { formatAgo } from "@/lib/format";
import { parseId, parseTopicSearch } from "@/lib/search";
import { BRIEF_STATES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const topicsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/topics",
  loader: ({ context }) => context.queryClient.ensureQueryData(api.topics),
  component: TopicsPage,
});

export const topicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/topics/$topicId",
  params: {
    parse: ({ topicId }) => ({ topicId: parseId(topicId) }),
    stringify: ({ topicId }) => ({ topicId: String(topicId) }),
  },
  validateSearch: parseTopicSearch,
  loaderDeps: ({ search }) => search,
  loader: async ({ context, params, deps }) => {
    try {
      return await Promise.all([
        context.queryClient.ensureQueryData(api.topic(params.topicId)),
        context.queryClient.ensureQueryData(topicPosts(params.topicId, deps.label)),
      ]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) throw notFound();
      throw error;
    }
  },
  component: TopicPage,
});

function TopicsPage(): JSX.Element {
  const { data } = useSuspenseQuery(api.topics);
  const { threshold } = useStatus();
  const count = data.groups.reduce((n, g) => n + g.topics.length, 0);
  return (
    <Page>
      <PageHeader
        title="Topics"
        subtitle="What your kept posts are about. Each topic merges its posts into one short brief."
        aside={
          <span className="font-mono text-caption text-silt">
            {count} {count === 1 ? "topic" : "topics"}
          </span>
        }
      />
      <div className="flex gap-2 max-[700px]:[&>*]:flex-1">
        <NewTopicSheet />
        <Button asChild>
          <Link to="/topics/rebuild">Rebuild topics</Link>
        </Button>
      </div>
      {data.suggestions.length > 0 && <Suggestions suggestions={data.suggestions} />}
      {count === 0 ? (
        <Empty title="No topics yet">
          Sift sorts kept posts into topics as it reads them. They show up here once a few posts are organized.
        </Empty>
      ) : (
        <div className="item-list mt-9" style={{ "--threshold": threshold } as CSSProperties}>
          <div className="relative surface">
            <ul>
              {data.groups.map((group) => (
                <li key={group.goal?.id ?? "none"} className="border-mesh border-t first:border-t-0">
                  <h2 className="pt-3.5 pr-[calc(var(--rail-w)+var(--rail-end)+16px)] pb-1 pl-4 font-medium text-caption text-silt">
                    {group.goal?.title ?? "No goal"}
                  </h2>
                  <ul>
                    {group.topics.map((topic) => (
                      <li key={topic.id} className="border-mesh border-t first:border-t-0">
                        <TopicRow topic={topic} threshold={threshold} />
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            <ThresholdLine threshold={threshold} />
          </div>
        </div>
      )}
    </Page>
  );
}

function TopicRow({ topic, threshold }: { topic: Topic; threshold: number }): JSX.Element {
  return (
    <Link
      to="/topics/$topicId"
      params={{ topicId: topic.id }}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 py-3 pr-(--rail-end) pl-4 outline-offset-[-2px] hover:bg-hover active:bg-hover"
    >
      <div className="min-w-0">
        <div className="truncate font-semibold">{topic.name}</div>
        <div className="mt-0.5 line-clamp-2 text-ink-soft min-[700px]:line-clamp-1">
          {topic.overview ?? topic.description}
        </div>
        <div className="mt-1 flex h-[18px] flex-wrap items-center gap-x-1.5 overflow-hidden text-caption text-silt">
          <span className="mr-1">{BRIEF_STATES[topic.brief_state].label}</span>
          {topic.top_labels.map((label) => (
            <span key={label} className="rounded-[5px] border border-mesh px-1.5">
              {label}
            </span>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className="w-[22px] text-right font-mono text-caption" title="Kept posts">
          {topic.kept}
        </span>
        <div className="rail" aria-hidden>
          {topic.scores.map((score, i) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: scores repeat, and the strip never reorders.
              key={i}
              className="strip-dot"
              data-above={score >= threshold || undefined}
              style={{ left: `${Math.min(100, Math.max(0, score))}%` }}
            />
          ))}
        </div>
      </div>
    </Link>
  );
}

function Suggestions({ suggestions }: { suggestions: MergeSuggestion[] }): JSX.Element {
  const merge = useMergeTopic();
  const dismiss = useDismissSuggestion();
  const busy = merge.isPending || dismiss.isPending;
  return (
    <Section title="Suggestions">
      <ul className="surface">
        {suggestions.map(({ source, into }) => (
          <li
            key={`${source.id}-${into.id}`}
            className="flex flex-wrap items-center gap-x-4 gap-y-2 border-mesh border-t px-4 py-3 first:border-t-0"
          >
            <p className="min-w-0 flex-1 basis-[240px]">
              Merge <span className="font-semibold">{source.name}</span> into{" "}
              <span className="font-semibold">{into.name}</span>?
            </p>
            <div className="flex gap-2 max-[700px]:w-full">
              <Button
                variant="ghost"
                disabled={busy}
                className="max-[700px]:flex-1"
                onClick={() => dismiss.mutate({ id: source.id, into: into.id })}
              >
                Dismiss
              </Button>
              <Button
                variant="primary"
                disabled={busy}
                className="max-[700px]:flex-1"
                onClick={() =>
                  merge.mutate(
                    { id: source.id, into: into.id },
                    { onSuccess: () => toast(`Merged ${source.name} into ${into.name}`) },
                  )
                }
              >
                Merge
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function TopicPage(): JSX.Element {
  const { topicId } = useParams({ from: "/topics/$topicId" });
  const search = useSearch({ from: "/topics/$topicId" });
  const { data: topic } = useSuspenseQuery(api.topic(topicId));
  const [lit, setLit] = useState<ReadonlySet<number>>(new Set());
  if (topic.id !== topicId) {
    return <Navigate to="/topics/$topicId" params={{ topicId: topic.id }} search={search} replace />;
  }
  return (
    <Page>
      <BackLink to="/topics">Topics</BackLink>
      <TopicHeader topic={topic} />
      <div className="mt-7">
        <BriefState topic={topic} />
        {topic.brief && <BriefBody brief={topic.brief} light={(ns) => setLit(new Set(ns))} />}
      </div>
      {topic.brief && topic.brief.sources.length > 0 && (
        <Section title="Sources" className="mt-10">
          <SourceLedger sources={topic.brief.sources} lit={lit} />
        </Section>
      )}
      <TopicPosts topic={topic} label={search.label} />
    </Page>
  );
}

function TopicHeader({ topic }: { topic: TopicDetail }): JSX.Element {
  const { timezone } = useStatus();
  const request = useRequestBrief();
  const writing = topic.brief_state === "writing" || request.isPending;
  const facts = [
    `${topic.kept} ${topic.kept === 1 ? "post" : "posts"}`,
    topic.folded > 0 && `${topic.folded} ${topic.folded === 1 ? "repeats" : "repeat"} another post`,
    topic.brief &&
      `Brief covers ${topic.freshness.in_brief} of ${topic.freshness.posts}, written ${formatAgo(topic.brief.written_at, timezone)}`,
  ].filter((fact) => typeof fact === "string");
  return (
    <header>
      {topic.goal && <p className="font-medium text-caption text-silt">{topic.goal.title}</p>}
      <h1 className="mt-1.5 font-display font-[640] text-page max-[700px]:text-[28px] max-[700px]:leading-8">
        {topic.name}
      </h1>
      {topic.description && <p className="mt-1.5 text-silt">{topic.description}</p>}
      <p className="mt-2 flex flex-wrap gap-x-2 text-caption text-silt">
        {facts.map((fact, i) => (
          <span key={fact} className="whitespace-nowrap">
            {i > 0 && <span aria-hidden>· </span>}
            {fact}
          </span>
        ))}
      </p>
      <div className="mt-4 flex gap-2 max-[700px]:[&>*]:flex-1">
        {topic.kept >= 2 && (
          <Button
            variant="primary"
            disabled={writing}
            onClick={() => request.mutate(topic.id, { onSuccess: () => toast("Writing the brief") })}
          >
            {writing ? "Writing..." : topic.brief ? "Update brief" : "Write brief"}
          </Button>
        )}
        <TopicSheet topic={topic} />
      </div>
    </header>
  );
}

function BriefState({ topic }: { topic: TopicDetail }): JSX.Element | null {
  const note = BRIEF_STATES[topic.brief_state].note;
  if (!note) return null;
  if (!topic.brief) return <p className="surface surface-pad text-silt">{note}</p>;
  return <p className="mb-3 text-[13px] text-silt">{note}</p>;
}

const MAX_CHIPS = 8;

const isShared = (l: LabelCount): boolean => l.count > 1;

// Every member post, wishlist ones included, so the list matches the topic's counts.
const TOPIC_MEMBERS: readonly ItemStatus[] = ["kept", "done"];

const topicPosts = (topic: number, label?: string) => api.items({ status: TOPIC_MEMBERS, topic, label });

function TopicPosts({ topic, label }: { topic: TopicDetail; label?: string }): JSX.Element {
  const { data: items } = useSuspenseQuery(topicPosts(topic.id, label));
  const chips = topic.labels.filter((l) => isShared(l) || l.label === label).slice(0, MAX_CHIPS);
  return (
    <Section title="Posts" className="mt-10">
      {chips.length > 0 && (
        <nav aria-label="Filter by label" className="flex flex-wrap gap-2">
          <Link to="/topics/$topicId" params={{ topicId: topic.id }} search={{}} replace className={chipClass(!label)}>
            All <span className="font-mono text-micro text-silt">{topic.kept}</span>
          </Link>
          {chips.map((l) => (
            <Link
              key={l.label}
              to="/topics/$topicId"
              params={{ topicId: topic.id }}
              search={{ label: l.label }}
              replace
              className={chipClass(label === l.label)}
            >
              {l.label} <span className="font-mono text-micro text-silt">{l.count}</span>
            </Link>
          ))}
        </nav>
      )}
      <div className={chips.length > 0 ? "mt-9" : "mt-7"}>
        <ItemList
          items={items}
          variant="library"
          empty={<Empty title="No posts here">No kept post in this topic has that label.</Empty>}
        />
      </div>
    </Section>
  );
}
