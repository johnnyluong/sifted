import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link, notFound, redirect, useParams, useSearch } from "@tanstack/react-router";
import { Check, ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type JSX, useState } from "react";
import {
  ApiError,
  api,
  type Digest,
  type DigestGroup,
  type DigestLine,
  type DigestPick,
  type DigestsView,
  type Item,
  type TopicDigest,
  type TopicDigestTab,
  useGenerateDigest,
  useStatus,
} from "@/api";
import { ShopLink } from "@/components/card-body";
import { BackLink, Empty, Page, PageHeader } from "@/components/page";
import { useMoveItem } from "@/components/shelf";
import { Thumb } from "@/components/thumb";
import { Button, chipClass } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { formatDay, formatMoment } from "@/lib/format";
import { parseDigestSearch, parseId } from "@/lib/search";
import { cn, httpLink } from "@/lib/utils";
import { actionWords, SOURCES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const digestsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/digests",
  validateSearch: parseDigestSearch,
  loaderDeps: ({ search }) => search,
  loader: async ({ context, deps }) => {
    try {
      return await Promise.all([
        context.queryClient.ensureQueryData(api.digests),
        deps.topic === undefined ? null : context.queryClient.ensureQueryData(api.topicDigest(deps.topic)),
      ]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) throw redirect({ to: "/digests", search: {} });
      throw error;
    }
  },
  component: DigestsPage,
});

export const digestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/digests/$digestId",
  params: {
    parse: ({ digestId }) => ({ digestId: parseId(digestId) }),
    stringify: ({ digestId }) => ({ digestId: String(digestId) }),
  },
  loader: async ({ context, params }) => {
    try {
      return await context.queryClient.ensureQueryData(api.digest(params.digestId));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) throw notFound();
      throw error;
    }
  },
  component: DigestPage,
});

function DigestsPage(): JSX.Element {
  const { topic } = useSearch({ from: "/digests" });
  const { data } = useSuspenseQuery(api.digests);
  return topic === undefined ? <ThisWeek view={data} /> : <TopicTab topicId={topic} tabs={data.topics} />;
}

function ThisWeek({ view: { latest, earlier, topics } }: { view: DigestsView }): JSX.Element {
  const { digest_schedule, timezone } = useStatus();
  const generate = useGenerateDigest();
  return (
    <Page>
      <PageHeader
        title="Digest"
        subtitle={
          latest
            ? `Week of ${formatDay(latest.period_end, timezone)}. Next: ${digest_schedule}.`
            : `What to act on from what you kept, ${digest_schedule}.`
        }
        aside={<GenerateButton generate={generate} />}
      />
      <DigestTabs tabs={topics} />
      <GenerateError generate={generate} className="mb-5 max-[700px]:hidden" />
      {latest ? (
        <DigestBody digest={latest} />
      ) : (
        <Empty title="No digest yet">
          Sift writes one {digest_schedule.toLowerCase()} from what you kept. Generate one now to see it.
        </Empty>
      )}
      <div className="mt-6 hidden flex-col gap-3 max-[700px]:flex">
        <GenerateButton generate={generate} className="w-full" />
        <GenerateError generate={generate} />
      </div>
      {earlier.length > 0 && (
        <section className="mt-10">
          <Eyebrow className="mb-2.5">Earlier digests</Eyebrow>
          <ul className="surface">
            {earlier.map((d) => (
              <li key={d.id} className="border-mesh border-t first:border-t-0">
                <Link
                  to="/digests/$digestId"
                  params={{ digestId: d.id }}
                  className="flex items-center gap-4 px-4 py-3.5 hover:bg-hover active:bg-hover"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">Week of {formatDay(d.period_end, timezone)}</p>
                    <p className="mt-0.5 text-caption text-silt">
                      {d.shown} {d.shown === 1 ? "post" : "posts"}
                    </p>
                  </div>
                  <span className="font-mono text-caption text-silt max-[700px]:hidden">
                    {formatMoment(d.created_at, timezone)}
                  </span>
                  <ChevronRight aria-hidden className="size-4 text-dust" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}

function TopicTab({ topicId, tabs }: { topicId: number; tabs: TopicDigestTab[] }): JSX.Element {
  const { data: view } = useSuspenseQuery(api.topicDigest(topicId));
  return (
    <Page>
      <PageHeader title="Digest" subtitle="What to act on next in one topic, from what you kept." />
      <DigestTabs tabs={tabs} active={view.topic.id} />
      <TopicDigestBody view={view} />
    </Page>
  );
}

function DigestTabs({ tabs, active }: { tabs: TopicDigestTab[]; active?: number }): JSX.Element | null {
  if (tabs.length === 0 && active === undefined) return null;
  const tab = (current: boolean) => cn(chipClass(current), "shrink-0 whitespace-nowrap");
  return (
    <nav aria-label="Digest tabs" className="mb-6 flex gap-2 overflow-x-auto py-1.5 [scrollbar-width:none]">
      <Link
        to="/digests"
        search={{}}
        activeOptions={{ exact: true }}
        aria-current={active === undefined ? "page" : undefined}
        className={tab(active === undefined)}
      >
        This week
      </Link>
      {tabs.map(({ topic, open }) => (
        <Link
          key={topic.id}
          to="/digests"
          search={{ topic: topic.id }}
          activeOptions={{ exact: true }}
          aria-current={active === topic.id ? "page" : undefined}
          className={tab(active === topic.id)}
        >
          {topic.name} <span className="font-mono text-micro text-silt">{open}</span>
        </Link>
      ))}
    </nav>
  );
}

function TopicDigestBody({ view }: { view: TopicDigest }): JSX.Element {
  return (
    <div className="max-w-[68ch]">
      <h2 className="font-display font-[640] text-heading">{view.topic.name}</h2>
      {view.overview && <p className="mt-1.5 text-reading">{view.overview}</p>}
      <Link
        to="/topics/$topicId"
        params={{ topicId: view.topic.id }}
        className="mt-2 inline-flex items-center gap-1 text-[13px] text-silt hover:text-graphite"
      >
        Open topic <ChevronRight aria-hidden className="size-3.5" />
      </Link>
      <section aria-labelledby="topic-next" className="mt-7">
        <Eyebrow id="topic-next" className="mb-2.5">
          To act on next
        </Eyebrow>
        {view.next.length > 0 ? (
          <ol className="space-y-3">
            <AnimatePresence initial={false} mode="popLayout">
              {view.next.map((pick, i) => (
                <PickCard key={pick.item.id} pick={pick} rank={i + 1} />
              ))}
            </AnimatePresence>
          </ol>
        ) : (
          <Empty title="Nothing to act on">
            Nothing kept here is waiting on you right now. A post you keep on this topic shows up here.
          </Empty>
        )}
      </section>
      {view.new.length > 0 && (
        <section className="mt-8">
          <Eyebrow className="mb-2.5">Also new</Eyebrow>
          <Lines lines={view.new} />
        </section>
      )}
    </div>
  );
}

type Generate = ReturnType<typeof useGenerateDigest>;

function GenerateError({ generate, className }: { generate: Generate; className?: string }): JSX.Element | null {
  if (!generate.error) return null;
  return (
    <p role="alert" className={cn("surface px-4 py-3 text-[13px] text-silt", className)}>
      {generate.error.message}
    </p>
  );
}

function GenerateButton({ generate, className }: { generate: Generate; className?: string }): JSX.Element {
  return (
    <Button
      variant="primary"
      className={className}
      disabled={generate.isPending}
      onClick={() => generate.mutate(undefined, { onSuccess: () => window.scrollTo({ top: 0 }) })}
    >
      {generate.isPending ? "Writing..." : "Generate digest"}
    </Button>
  );
}

function DigestPage(): JSX.Element {
  const { digestId } = useParams({ from: "/digests/$digestId" });
  const { data: digest } = useSuspenseQuery(api.digest(digestId));
  const { timezone } = useStatus();
  return (
    <Page>
      <BackLink to="/digests">Digest</BackLink>
      <p className="font-mono text-micro text-silt">
        {formatDay(digest.period_start, timezone)} to {formatDay(digest.period_end, timezone)}
      </p>
      <h1 className="mt-1.5 mb-7 font-display font-[640] text-heading">
        Week of {formatDay(digest.period_end, timezone)}
      </h1>
      <DigestBody digest={digest} />
    </Page>
  );
}

export function DigestBody({ digest }: { digest: Digest }): JSX.Element {
  const byGoal = digest.groups.filter((g) => g.kind === "goal");
  const places = digest.groups.filter((g) => g.kind === "places");
  return (
    <div className="max-w-[68ch]">
      {digest.opening && <p className="mb-7 text-reading">{digest.opening}</p>}
      <section aria-labelledby="digest-top">
        <Eyebrow id="digest-top" className="mb-2.5">
          To act on this week
        </Eyebrow>
        {digest.top.length > 0 ? (
          <ol className="space-y-3">
            <AnimatePresence initial={false} mode="popLayout">
              {digest.top.map((pick, i) => (
                <PickCard key={pick.item.id} pick={pick} rank={i + 1} />
              ))}
            </AnimatePresence>
          </ol>
        ) : (
          <p className="surface px-4 py-3 text-silt">Nothing left to act on from this digest.</p>
        )}
      </section>
      {digest.done.length > 0 && (
        <section className="mt-8">
          <Eyebrow className="mb-2.5">Done</Eyebrow>
          <ul className="surface">
            {digest.done.map((pick) => (
              <DoneRow key={pick.item.id} pick={pick} />
            ))}
          </ul>
        </section>
      )}
      <Groups title="By goal" groups={byGoal} />
      <Groups title="Places" groups={places} />
      {digest.wishlist.length > 0 && (
        <section aria-labelledby="digest-wishlist" className="mt-8">
          <Eyebrow id="digest-wishlist" className="mb-2.5">
            On your wishlist
          </Eyebrow>
          <ul className="surface">
            {digest.wishlist.map((item) => (
              <WishRow key={item.id} item={item} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function WishRow({ item }: { item: Item }): JSX.Element {
  const move = useMoveItem();
  const name = item.product?.name ?? item.display_title;
  const link = httpLink(item.product?.link);
  const bought = actionWords("done", item).label;
  return (
    <li className="flex items-center gap-3 border-mesh border-t px-4 py-2.5 first:border-t-0">
      <Link
        to="/items/$itemId"
        params={{ itemId: item.id }}
        className="min-w-0 flex-1 truncate font-medium hover:underline"
      >
        {name}
      </Link>
      {item.product?.price && (
        <span className="shrink-0 font-mono text-caption text-graphite">{item.product.price}</span>
      )}
      {link && <ShopLink href={link} name={name} className="shrink-0" />}
      {item.actions.includes("done") && (
        <Button size="sm" onClick={() => move(item, "done")} aria-label={`${bought}: ${name}`}>
          {bought}
        </Button>
      )}
    </li>
  );
}

function PickCard({ pick, rank }: { pick: DigestPick; rank: number }): JSX.Element {
  const move = useMoveItem();
  const [pending, setPending] = useState(false);
  const { item } = pick;
  const markDone = async () => {
    setPending(true);
    await move(item, "done");
    setPending(false);
  };
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: 0.2 }}
      className="flex gap-3.5 surface p-4"
    >
      <span className="w-5 shrink-0 pt-0.5 font-display text-[20px] text-silt leading-6">{rank}</span>
      <div className="min-w-0 flex-1">
        <div className="float-right mb-1 ml-3">
          <Thumb url={item.thumbnail_url} placeholder={SOURCES[item.source].monogram} />
        </div>
        <Link to="/items/$itemId" params={{ itemId: item.id }} className="font-semibold hover:underline">
          {item.display_title}
        </Link>
        {pick.refill && <p className="mt-0.5 font-mono text-micro text-brass">Moved up</p>}
        {pick.why && <p className="mt-1.5 text-ink-soft">{pick.why}</p>}
        {pick.next_action && (
          <p className="mt-2 text-[13px]">
            <span className="font-semibold">Next: </span>
            {pick.next_action}
          </p>
        )}
        <div className="mt-3 flex gap-2">
          <Button size="sm" asChild>
            <Link to="/items/$itemId" params={{ itemId: item.id }} aria-label={`Open ${item.display_title}`}>
              Open
            </Link>
          </Button>
          {item.actions.includes("done") && (
            <Button
              size="sm"
              variant="primary"
              disabled={pending}
              onClick={markDone}
              aria-label={`Done: ${item.display_title}`}
            >
              Done
            </Button>
          )}
        </div>
      </div>
    </motion.li>
  );
}

function DoneRow({ pick }: { pick: DigestPick }): JSX.Element {
  const move = useMoveItem();
  const { item } = pick;
  return (
    <li className="flex items-center gap-3 border-mesh border-t px-4 py-2.5 first:border-t-0">
      <Check aria-hidden className="size-4 shrink-0 text-silt" />
      <Link
        to="/items/$itemId"
        params={{ itemId: item.id }}
        className="min-w-0 flex-1 truncate text-silt line-through hover:text-graphite"
      >
        {item.display_title}
      </Link>
      {item.actions.includes("undone") && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => move(item, "undone")}
          aria-label={`Undo: ${item.display_title}`}
        >
          Undo
        </Button>
      )}
    </li>
  );
}

function Groups({ title, groups }: { title: string; groups: DigestGroup[] }): JSX.Element | null {
  if (groups.length === 0) return null;
  return (
    <section className="mt-8">
      <Eyebrow className="mb-2.5">{title}</Eyebrow>
      <div className="space-y-5">
        {groups.map((g) => (
          <div key={g.heading}>
            <h3 className="mb-1.5 font-display font-[640] text-[16px] leading-[22px]">{g.heading}</h3>
            <Lines lines={g.lines} />
          </div>
        ))}
      </div>
    </section>
  );
}

function Lines({ lines }: { lines: DigestLine[] }): JSX.Element {
  return (
    <ul className="space-y-1.5">
      {lines.map(({ item, line }) => (
        <li key={item.id}>
          <Link
            to="/items/$itemId"
            params={{ itemId: item.id }}
            className="font-medium underline decoration-dust underline-offset-[3px] hover:decoration-graphite"
          >
            {item.display_title}
          </Link>
          {line && <span className="text-ink-soft">: {line}</span>}
        </li>
      ))}
    </ul>
  );
}
