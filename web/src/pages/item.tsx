import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link, notFound, useParams } from "@tanstack/react-router";
import { ArrowLeft, ArrowUpRight, ChevronRight, RotateCw } from "lucide-react";
import { type JSX, type ReactNode, useEffect, useEffectEvent } from "react";
import { toast } from "sonner";
import { ApiError, api, type ItemDetail, type UserAction, useItemAction, useStatus } from "@/api";
import { CardBody, Facts, Section } from "@/components/card-body";
import { DockPortal } from "@/components/dock";
import { Organization } from "@/components/organization";
import { Page } from "@/components/page";
import { isEditable } from "@/components/paste-box";
import { ScoreInstrument, verdict } from "@/components/score-rail";
import { StageTrack } from "@/components/stage-track";
import { Thumb } from "@/components/thumb";
import { Button } from "@/components/ui/button";
import { formatChars, formatDay, formatMoment } from "@/lib/format";
import { parseId } from "@/lib/search";
import { cn } from "@/lib/utils";
import { ACTIONS, primaryAction, SOURCES, TYPES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const itemRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/items/$itemId",
  params: {
    parse: ({ itemId }) => ({ itemId: parseId(itemId) }),
    stringify: ({ itemId }) => ({ itemId: String(itemId) }),
  },
  loader: async ({ context, params }) => {
    try {
      return await context.queryClient.ensureQueryData(api.item(params.itemId));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) throw notFound();
      throw error;
    }
  },
  component: ItemPage,
});

function back(item: ItemDetail): { to: "/kept" | "/archived" | "/inbox"; label: string } {
  if (item.status === "kept" || item.status === "done") return { to: "/kept", label: "Kept" };
  if (item.status === "archived") return { to: "/archived", label: "Archived" };
  return { to: "/inbox", label: "Inbox" };
}

function ItemPage(): JSX.Element {
  const { itemId } = useParams({ from: "/items/$itemId" });
  const { data: item } = useSuspenseQuery(api.item(itemId));
  const { timezone } = useStatus();
  const type = item.item_type ? TYPES[item.item_type] : null;
  const to = back(item);
  return (
    <Page wide>
      <Link
        to={to.to}
        className="mb-[18px] inline-flex items-center gap-1 text-[13px] text-silt hover:text-graphite max-[700px]:-my-3 max-[700px]:mb-1.5 max-[700px]:py-3 max-[700px]:text-[15px]"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        {to.label}
      </Link>
      <div className="grid grid-cols-1 gap-x-10 gap-y-7 lg:grid-cols-[minmax(0,1fr)_300px] lg:grid-rows-[auto_1fr] lg:gap-y-4">
        <header className="flex gap-4 lg:col-start-1">
          <Thumb url={item.thumbnail_url} size={72} placeholder={SOURCES[item.source].monogram} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2.5 text-caption text-silt">
              <span>{type ? type.label : SOURCES[item.source].label}</span>
              {item.author_handle && <span>@{item.author_handle}</span>}
              <span className="font-mono text-micro">{formatDay(item.received_at, timezone)}</span>
            </div>
            <h1 className="mt-1.5 font-display font-[640] text-heading max-[700px]:text-[24px] max-[700px]:leading-[30px]">
              {item.display_title}
            </h1>
          </div>
        </header>

        <aside className="lg:sticky lg:top-11 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start">
          <Instrument item={item} />
          <div className="mt-6 px-5 text-[12.5px] max-lg:hidden">
            <Provenance item={item} />
          </div>
        </aside>

        <div className="min-w-0 lg:col-start-1">
          {item.summary && <p className="reading text-ink-soft">{item.summary}</p>}
          {item.next_action && (
            <Section title="Next action">
              <p className="font-[560]">{item.next_action}</p>
            </Section>
          )}
          <div className="mt-7 first:mt-0">{item.card ? <CardBody card={item.card} /> : <Pending item={item} />}</div>
          <Organization item={item} />
          <SourceTexts item={item} />
          <Section title="Details" className="lg:hidden">
            <Provenance item={item} />
          </Section>
        </div>
      </div>
    </Page>
  );
}

function Provenance({ item }: { item: ItemDetail }): JSX.Element | null {
  const { timezone } = useStatus();
  const model = item.score_model ?? item.extract_model;
  return (
    <Facts
      rows={[
        ["Source", SOURCES[item.source].label],
        [
          "Added",
          <span key="added" className="font-mono text-caption">
            {formatMoment(item.received_at, timezone)}
          </span>,
        ],
        [
          "Model",
          model && (
            <span key="model" className="block truncate font-mono text-caption">
              {model}
            </span>
          ),
        ],
      ]}
    />
  );
}

function Instrument({ item }: { item: ItemDetail }): JSX.Element {
  const { threshold } = useStatus();
  const scored = item.relevance_score !== null;
  return (
    <section className="surface surface-pad">
      <div className="flex items-center justify-between gap-3">
        <span className={cn("font-[560]", item.status === "failed" && "text-alarm")}>{item.state_label}</span>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[13px] text-silt hover:text-graphite max-[700px]:-my-3 max-[700px]:py-3"
        >
          Open original
          <ArrowUpRight aria-hidden className="size-3.5" />
        </a>
      </div>
      {scored ? (
        <>
          <ScoreInstrument item={item} threshold={threshold} />
          <p className="mt-[18px] font-[560]">{verdict(item, threshold)}</p>
          {item.relevance_reason && (
            <p className="mt-1 text-[13px] text-silt leading-[19px]">{item.relevance_reason}</p>
          )}
          {item.matched_goal_title && (
            <p className="mt-2 text-[13px] text-silt">
              Goal: <span className="text-graphite">{item.matched_goal_title}</span>
            </p>
          )}
        </>
      ) : (
        <div className="mt-4">
          <StageTrack item={item} />
        </div>
      )}
      <ItemActions item={item} />
    </section>
  );
}

function ItemActions({ item }: { item: ItemDetail }): JSX.Element | null {
  const act = useItemAction();
  const primary = primaryAction(item);
  const run = (action: UserAction) =>
    act.mutate({ id: item.id, action }, { onSuccess: () => toast(ACTIONS[action].done) });

  const onKey = useEffectEvent((event: KeyboardEvent) => {
    if (event.metaKey || event.ctrlKey || event.altKey || isEditable(event.target) || act.isPending) return;
    const action = KEYS[event.key.toLowerCase()];
    if (action && item.actions.includes(action)) run(action);
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => onKey(event);
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);

  if (item.actions.length === 0) return null;
  const ordered = [...item.actions].sort((a, b) => Number(a === "reprocess") - Number(b === "reprocess"));
  const decisions = ordered.filter((a) => a !== "reprocess");
  return (
    <>
      <div className="mt-[18px] grid grid-cols-2 gap-2 max-[700px]:hidden">
        {ordered.map((action, i) => (
          <Button
            key={action}
            variant={action === primary ? "primary" : "secondary"}
            disabled={act.isPending}
            onClick={() => run(action)}
            className={cn(ordered.length % 2 === 1 && i === ordered.length - 1 && "col-span-2")}
          >
            {ACTIONS[action].label}
          </Button>
        ))}
      </div>
      <DockPortal>
        <div className="flex gap-2 border-mesh border-b pr-[max(16px,env(safe-area-inset-right))] pl-[max(16px,env(safe-area-inset-left))] py-2.5">
          {decisions.map((action) => (
            <Button
              key={action}
              variant={action === primary ? "primary" : "secondary"}
              disabled={act.isPending}
              onClick={() => run(action)}
              className="min-w-0 flex-1"
            >
              {ACTIONS[action].label}
            </Button>
          ))}
          {item.actions.includes("reprocess") && (
            <Button
              aria-label={ACTIONS.reprocess.label}
              disabled={act.isPending}
              onClick={() => run("reprocess")}
              className={decisions.length > 0 ? "w-11 px-0" : "flex-1"}
            >
              <RotateCw aria-hidden />
              {decisions.length === 0 && ACTIONS.reprocess.label}
            </Button>
          )}
        </div>
      </DockPortal>
    </>
  );
}

const KEYS: Record<string, UserAction> = { k: "keep", a: "archive", d: "done" };

function Pending({ item }: { item: ItemDetail }): JSX.Element {
  let body: ReactNode = "Working on it. This page updates on its own.";
  if (item.status === "failed") body = item.failure_hint ?? "Use Retry to try again.";
  else if (item.status === "archived") body = "Archived before Sift finished reading it. Use Reprocess to try again.";
  else if (item.waiting_for === "llm")
    body = "The transcript and frames are saved. Extraction runs once an LLM is configured.";
  else if (item.waiting_for === "goals")
    body = (
      <>
        <Link to="/goals" className="text-graphite underline underline-offset-2">
          Add a goal
        </Link>{" "}
        so Sift can score this card.
      </>
    );
  return (
    <div className={cn("surface surface-pad", item.status === "failed" && "border-alarm/40 bg-alarm-wash")}>
      {(item.status === "failed" || item.status === "archived") && item.status_reason && (
        <p className={cn("mb-1", item.status === "failed" ? "text-alarm" : "text-ink-soft")}>{item.status_reason}</p>
      )}
      <p className="text-silt">{body}</p>
    </div>
  );
}

function SourceTexts({ item }: { item: ItemDetail }): JSX.Element | null {
  const texts: [string, string | null][] = [
    ["Caption", item.caption],
    ["Post text", item.post_text],
    ["On-screen text", item.ocr_text],
    ["Transcript", item.transcript],
  ];
  const shown = texts.filter((t): t is [string, string] => Boolean(t[1]?.trim()));
  if (shown.length === 0) return null;
  return (
    <div className="mt-7 border-mesh border-b">
      {shown.map(([label, text]) => (
        <details key={label} className="group border-mesh border-t">
          <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 font-medium text-[13px] text-ink-soft [&::-webkit-details-marker]:hidden">
            <ChevronRight aria-hidden className="size-3.5 text-silt transition-transform group-open:rotate-90" />
            <span className="flex-1">{label}</span>
            <span className="font-mono text-micro text-silt">{formatChars(text)}</span>
          </summary>
          <p className="reading whitespace-pre-wrap pb-4 pl-[22px] text-ink-soft">{text}</p>
        </details>
      ))}
    </div>
  );
}
