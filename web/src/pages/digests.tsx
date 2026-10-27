import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link, notFound, useParams } from "@tanstack/react-router";
import { ArrowLeft, Check, ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type JSX, useState } from "react";
import { ApiError, api, type Digest, type DigestGroup, type DigestPick, useGenerateDigest, useStatus } from "@/api";
import { Empty, Page, PageHeader } from "@/components/page";
import { useMoveItem } from "@/components/shelf";
import { Thumb } from "@/components/thumb";
import { Button } from "@/components/ui/button";
import { formatDay, formatMoment } from "@/lib/format";
import { parseId } from "@/lib/search";
import { cn } from "@/lib/utils";
import { SOURCES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const digestsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/digests",
  loader: ({ context }) => context.queryClient.ensureQueryData(api.digests),
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
  const {
    data: { latest, earlier },
  } = useSuspenseQuery(api.digests);
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
          <h2 className={labelClass}>Earlier digests</h2>
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
      <Link
        to="/digests"
        className="mb-[18px] inline-flex items-center gap-1 text-[13px] text-silt hover:text-graphite max-[700px]:-my-3 max-[700px]:mb-1.5 max-[700px]:py-3 max-[700px]:text-[15px]"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        Digest
      </Link>
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

const labelClass = "mb-2.5 font-mono text-micro text-silt uppercase tracking-[0.04em]";

export function DigestBody({ digest }: { digest: Digest }): JSX.Element {
  const byGoal = digest.groups.filter((g) => g.kind === "goal");
  const places = digest.groups.filter((g) => g.kind === "places");
  return (
    <div className="max-w-[68ch]">
      {digest.opening && <p className="mb-7 text-reading">{digest.opening}</p>}
      <section aria-labelledby="digest-top">
        <h2 id="digest-top" className={labelClass}>
          To act on this week
        </h2>
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
          <h2 className={labelClass}>Done</h2>
          <ul className="surface">
            {digest.done.map((pick) => (
              <DoneRow key={pick.item.id} pick={pick} />
            ))}
          </ul>
        </section>
      )}
      <Groups title="By goal" groups={byGoal} />
      <Groups title="Places" groups={places} />
    </div>
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
      <h2 className={labelClass}>{title}</h2>
      <div className="space-y-5">
        {groups.map((g) => (
          <div key={g.heading}>
            <h3 className="mb-1.5 font-display font-[640] text-[16px] leading-[22px]">{g.heading}</h3>
            <ul className="space-y-1.5">
              {g.lines.map(({ item, line }) => (
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
          </div>
        ))}
      </div>
    </section>
  );
}
