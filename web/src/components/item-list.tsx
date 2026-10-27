import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type CSSProperties, type JSX, type ReactNode, useId, useState } from "react";
import { toast } from "sonner";
import { type Item, useItemAction, useStatus } from "@/api";
import { ScoreRail, ThresholdLine } from "@/components/score-rail";
import { type MoveItem, useItemDrag, useMoveItem } from "@/components/shelf";
import { StageAxis, StageTrack } from "@/components/stage-track";
import { SwipeRow } from "@/components/swipe-row";
import { Thumb } from "@/components/thumb";
import { Button } from "@/components/ui/button";
import { groupFolds } from "@/lib/folds";
import { formatAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ACTIONS, IMPORTED_LABEL, SOURCES, TYPES } from "@/lib/vocabulary";

export type ListVariant = "inbox" | "library";

export function ItemList({
  items,
  variant,
  empty,
}: {
  items: Item[];
  variant: ListVariant;
  empty: ReactNode;
}): JSX.Element {
  const { threshold } = useStatus();
  const move = useMoveItem();
  if (items.length === 0) return <>{empty}</>;
  const groups = variant === "library" ? groupFolds(items) : items.map((row) => ({ row, under: [] }));
  return (
    <div className="item-list" style={{ "--threshold": threshold } as CSSProperties}>
      {variant === "inbox" && (
        <div className="flex justify-end pr-[144px] max-[700px]:hidden">
          <StageAxis />
        </div>
      )}
      <div className="relative surface">
        <ul>
          <AnimatePresence initial={false}>
            {groups.map(({ row, under }) => (
              <motion.li
                key={row.id}
                className="relative overflow-hidden border-mesh border-t first:rounded-t-[11px] first:border-t-0 last:rounded-b-[11px]"
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.22, ease: "easeOut" }}
              >
                <SwipeRow item={row} move={move}>
                  {variant === "library" ? <LibraryRow item={row} /> : <InboxRow item={row} />}
                </SwipeRow>
                {under.length > 0 && <Folded covered={under} move={move} />}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
        {variant === "library" && <ThresholdLine threshold={threshold} />}
      </div>
    </div>
  );
}

const rowClass =
  "grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3.5 py-3 pr-(--rail-end) pl-4 outline-offset-[-2px] hover:bg-hover active:bg-hover";

function LibraryRow({ item, covered }: { item: Item; covered?: boolean }): JSX.Element {
  const drag = useItemDrag(item);
  const { threshold } = useStatus();
  return (
    <Link
      ref={drag.ref}
      // dnd-kit gives a draggable without a role the button role.
      role="link"
      to="/items/$itemId"
      params={{ itemId: item.id }}
      draggable={false}
      className={cn(
        rowClass,
        "bg-sheet",
        covered && "grid-cols-[28px_minmax(0,1fr)_auto] py-2.5 pl-14 max-[700px]:pl-10",
        drag.isDragging && "opacity-50",
      )}
    >
      <Thumb url={item.thumbnail_url} size={covered ? 28 : 40} placeholder={SOURCES[item.source].monogram} />
      {covered ? <CoveredText item={item} /> : <RowText item={item} />}
      <ScoreRail item={item} threshold={threshold} />
    </Link>
  );
}

function Folded({ covered, move }: { covered: Item[]; move: MoveItem }): JSX.Element {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen(!open)}
        className="-mt-2 flex min-h-8 w-full cursor-pointer items-center gap-1.5 pb-1 pl-[70px] text-left text-caption text-silt hover:text-graphite max-[700px]:min-h-11"
      >
        <ChevronRight aria-hidden className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        {covered.length} more {covered.length === 1 ? "says" : "say"} the same
      </button>
      <ul id={panel} hidden={!open}>
        {covered.map((item) => (
          <li key={item.id} className="border-mesh border-t">
            <SwipeRow item={item} move={move}>
              <LibraryRow item={item} covered />
            </SwipeRow>
          </li>
        ))}
      </ul>
    </>
  );
}

function CoveredText({ item }: { item: Item }): JSX.Element {
  return (
    <div className="min-w-0">
      <div className="truncate font-medium text-ink-soft">{item.display_title}</div>
      {item.gist && <div className="truncate text-caption text-silt max-[700px]:hidden">{item.gist}</div>}
    </div>
  );
}

function InboxRow({ item }: { item: Item }): JSX.Element {
  const act = useItemAction();
  const failed = item.status === "failed";
  return (
    <>
      <Link to="/items/$itemId" params={{ itemId: item.id }} className={rowClass}>
        <Thumb url={item.thumbnail_url} placeholder={SOURCES[item.source].monogram} />
        <RowText item={item} imported={item.origin_channel === "export"} />
        <div className="flex items-center gap-3">
          <div className={cn(failed && "max-[700px]:invisible")}>
            <StageTrack item={item} />
          </div>
          <span
            className={cn(
              "w-[112px] text-right font-mono text-caption text-silt max-[700px]:hidden",
              failed && "invisible",
            )}
          >
            {item.state_label}
          </span>
        </div>
      </Link>
      {failed && item.actions.includes("retry") && (
        <Button
          size="sm"
          className="absolute top-1/2 right-5 -translate-y-1/2 max-[700px]:right-3 max-[700px]:h-11"
          disabled={act.isPending}
          onClick={() => act.mutate({ id: item.id, action: "retry" }, { onSuccess: () => toast(ACTIONS.retry.done) })}
        >
          {ACTIONS.retry.label}
        </Button>
      )}
    </>
  );
}

function RowText({ item, imported }: { item: Item; imported?: boolean }): JSX.Element {
  const { timezone } = useStatus();
  const type = item.item_type ? TYPES[item.item_type] : null;
  return (
    <div className="min-w-0">
      <div className="truncate font-semibold max-[700px]:line-clamp-2 max-[700px]:whitespace-normal max-[700px]:leading-[18px]">
        {imported && (
          <span className="mr-2 rounded-[5px] border border-mesh px-1.5 py-px align-[1px] font-mono font-normal text-micro text-silt">
            {IMPORTED_LABEL}
          </span>
        )}
        {item.display_title}
      </div>
      {item.status === "failed" ? (
        <div className="mt-0.5 truncate text-caption text-alarm" title={item.failure_hint ?? undefined}>
          {item.status_reason ?? "Failed"}
        </div>
      ) : (
        <>
          {item.gist && (
            <div className="mt-0.5 truncate text-ink-soft max-[700px]:line-clamp-2 max-[700px]:whitespace-normal max-[700px]:leading-[18px]">
              {item.gist}
            </div>
          )}
          <div className="mt-0.5 flex min-w-0 items-center gap-2.5 text-caption text-silt">
            {type ? (
              <span className="inline-flex shrink-0 items-center gap-[5px]">
                <type.icon aria-hidden className="size-3" strokeWidth={1.8} />
                {type.label}
              </span>
            ) : (
              <span className="shrink-0">{SOURCES[item.source].label}</span>
            )}
            {item.topic ? (
              <>
                <span className="truncate text-ink-soft">{item.topic.name}</span>
                {item.labels.slice(0, 2).map((label) => (
                  <span key={label} className="shrink-0 rounded-[5px] border border-mesh px-1.5 max-[700px]:hidden">
                    {label}
                  </span>
                ))}
              </>
            ) : (
              item.author_handle && <span className="truncate">@{item.author_handle}</span>
            )}
            {item.in_motion || item.status === "queued" ? (
              <span className="shrink-0">{formatAgo(item.received_at, timezone)}</span>
            ) : (
              !item.topic &&
              item.matched_goal_title && <span className="truncate max-[700px]:hidden">{item.matched_goal_title}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
