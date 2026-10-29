import {
  DragDropProvider,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
} from "@dnd-kit/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { type JSX, type ReactNode, useState } from "react";
import { toast } from "sonner";
import {
  type Item,
  type ItemDetail,
  type ItemOrganization,
  type Topic,
  type TopicRef,
  type UserAction,
  useItemAction,
  useSetItemTopic,
  useSetWishlist,
} from "@/api";
import { Thumb } from "@/components/thumb";
import type { Shelf } from "@/lib/nav";
import { isMousePointer } from "@/lib/swipe";
import { cn } from "@/lib/utils";
import { ACTIONS, actionWords, SOURCES, TYPES } from "@/lib/vocabulary";

export type DropTarget = { kind: "shelf"; shelf: Shelf } | { kind: "topic"; topic: TopicRef };

const UNDO_BY_PRIOR_STATUS: Partial<Record<Item["status"], { label: string; actions: readonly UserAction[] }>> = {
  kept: { label: "Undo", actions: ["undone", "keep"] },
  archived: { label: "Undo", actions: ["undone", "archive"] },
  done: { label: "Undo", actions: ["done"] },
  failed: { label: ACTIONS.reprocess.label, actions: ["reprocess"] },
};

function undoFor(before: Item["status"], after: Pick<Item, "actions">): { label: string; action: UserAction } | null {
  const undo = UNDO_BY_PRIOR_STATUS[before];
  const action = undo?.actions.find((a) => after.actions.includes(a));
  return undo && action ? { label: undo.label, action } : null;
}

function hasFreshOutline(item: Pick<Item, "gist">): boolean {
  return item.gist !== null;
}

export function canDrop(item: Pick<Item, "actions" | "gist" | "topic">, target: DropTarget): boolean {
  switch (target.kind) {
    case "shelf":
      return target.shelf.accepts !== undefined && item.actions.includes(target.shelf.accepts);
    case "topic":
      return hasFreshOutline(item) && item.topic?.id !== target.topic.id;
  }
}

export const SIFTS_PICK = null;

export function restoredTopic(
  before: TopicRef | null,
  after: Pick<ItemOrganization, "sift_topic">,
): number | typeof SIFTS_PICK {
  return before === null || before.id === after.sift_topic?.id ? SIFTS_PICK : before.id;
}

type PreventActivation = NonNullable<(typeof PointerSensor.defaults)["preventActivation"]>;

const leaveSwipesToSwipeRow: PreventActivation = (event, source) =>
  !isMousePointer(event) || Boolean(PointerSensor.defaults.preventActivation?.(event, source));

const PICKUP_KEYS = ["Space"];

const sensors = [
  PointerSensor.configure({ preventActivation: leaveSwipesToSwipeRow }),
  KeyboardSensor.configure({
    keyboardCodes: {
      start: PICKUP_KEYS,
      cancel: ["Escape"],
      end: ["Space", "Enter"],
      up: ["ArrowUp"],
      down: ["ArrowDown"],
      left: ["ArrowLeft"],
      right: ["ArrowRight"],
    },
  }),
];

export type MoveItem = (item: Item, action: UserAction) => Promise<ItemDetail | null>;

// Per-call mutate callbacks fire only for a hook's latest call, so each move awaits its own promise.
export function useMoveItem(): MoveItem {
  const act = useItemAction();
  const setWishlist = useSetWishlist();
  const navigate = useNavigate();
  const undoMove = (item: Item, action: UserAction, after: ItemDetail) => {
    // Archive clears a hand add, so Keep would land the post on Kept instead of back on the wishlist.
    if (action === "archive" && item.wishlist) {
      return { label: "Undo", onClick: () => setWishlist.mutate({ id: item.id, on: true }) };
    }
    const undo = undoFor(item.status, after);
    return undo ? { label: undo.label, onClick: () => act.mutate({ id: item.id, action: undo.action }) } : undefined;
  };
  return async (item, action) => {
    try {
      const after = await act.mutateAsync({ id: item.id, action });
      toast(`${actionWords(action, item).done}: ${item.display_title}`, {
        action: undoMove(item, action, after),
        cancel:
          action === "keep" && after.asks_keep_reason
            ? { label: "Say why", onClick: () => void navigate({ to: "/items/$itemId", params: { itemId: item.id } }) }
            : undefined,
      });
      return after;
    } catch {
      return null;
    }
  };
}

function useMoveToTopic(): (item: Item, topic: TopicRef) => Promise<ItemOrganization | null> {
  const set = useSetItemTopic();
  return async (item, topic) => {
    try {
      const after = await set.mutateAsync({ id: item.id, topic: topic.id });
      toast(`Moved to ${after.topic?.name ?? topic.name}`, {
        action: { label: "Undo", onClick: () => set.mutate({ id: item.id, topic: restoredTopic(item.topic, after) }) },
      });
      return after;
    } catch {
      return null;
    }
  };
}

function useDrop(): (item: Item, target: DropTarget) => Promise<ItemDetail | ItemOrganization | null> {
  const move = useMoveItem();
  const moveToTopic = useMoveToTopic();
  return async (item, target) => {
    switch (target.kind) {
      case "shelf":
        return target.shelf.accepts ? move(item, target.shelf.accepts) : null;
      case "topic":
        return moveToTopic(item, target.topic);
    }
  };
}

const CHIP_HEIGHT = 40;
const CHIP_OFFSET = { x: 12, y: 10 };

export function ShelfDnd({ children }: { children: ReactNode }): JSX.Element {
  const drop = useDrop();
  const [grab, setGrab] = useState({ x: 0, y: 0 });
  return (
    <DragDropProvider
      sensors={sensors}
      onBeforeDragStart={(event) => {
        const rect = event.operation.source?.element?.getBoundingClientRect();
        const { x, y } = event.operation.position.initial;
        if (rect) setGrab({ x: x - rect.left, y: y - rect.top });
      }}
      onDragEnd={(event) => {
        if (event.canceled) return;
        const item = event.operation.source?.data as Item | undefined;
        const target = event.operation.target?.data as DropTarget | undefined;
        if (item && target && canDrop(item, target)) void drop(item, target);
      }}
    >
      {children}
      {/* Feedback pins the overlay to the row's top-left at the row's size (not !important); this shrinks it and
          shifts it next to the grab point. */}
      <DragOverlay
        dropAnimation={null}
        style={{
          width: "max-content",
          maxWidth: 240,
          height: CHIP_HEIGHT,
          maxHeight: CHIP_HEIGHT,
          marginLeft: grab.x + CHIP_OFFSET.x,
          marginTop: grab.y + CHIP_OFFSET.y,
        }}
      >
        {(source) => <DragChip item={source.data as Item} />}
      </DragOverlay>
    </DragDropProvider>
  );
}

function DragChip({ item }: { item: Item }): JSX.Element {
  const type = item.item_type ? TYPES[item.item_type] : null;
  return (
    <div className="flex h-full items-center gap-2 rounded-lg border border-mesh bg-sheet py-1.5 pr-3 pl-1.5 shadow-float">
      <Thumb
        url={item.thumbnail_url}
        size={28}
        placeholder={type ? <type.icon className="size-3.5" strokeWidth={1.8} /> : SOURCES[item.source].monogram}
      />
      <span className="min-w-0 truncate font-medium text-[13px]">{item.display_title}</span>
    </div>
  );
}

export function useItemDrag(item: Item): { ref: (el: Element | null) => void; isDragging: boolean } {
  const { ref, isDragging } = useDraggable({ id: `item:${item.id}`, data: item });
  return { ref, isDragging };
}

export const sideLinkClass =
  "flex items-center gap-2 rounded-md px-2.5 py-1.5 font-medium text-graphite/80 hover:bg-pan-hover data-[status=active]:bg-pan-hover data-[status=active]:text-graphite";

export const tabClass =
  "flex min-h-[50px] cursor-pointer flex-col items-center justify-center gap-0.5 rounded-lg text-[11px] text-silt active:bg-pan-hover data-[status=active]:font-semibold data-[status=active]:text-graphite";

function useDropTarget(id: string, target: DropTarget, disabled = false): ReturnType<typeof useDroppable> {
  return useDroppable({
    id,
    data: target,
    disabled,
    accept: (source) => canDrop(source.data as Item, target),
  });
}

export function ShelfLink({ shelf, count, tab }: { shelf: Shelf; count: number; tab?: boolean }): JSX.Element {
  const { ref, isDropTarget } = useDropTarget(
    `shelf:${shelf.id}:${tab ? "tab" : "side"}`,
    { kind: "shelf", shelf },
    shelf.accepts === undefined,
  );
  return (
    <Link
      ref={ref}
      to={shelf.to}
      data-drop={isDropTarget}
      className={cn("shelf", tab ? tabClass : cn(sideLinkClass, "justify-between"))}
    >
      {tab ? (
        <>
          <span className="font-mono text-[14px] leading-[19px]">{count}</span>
          <span>{shelf.label}</span>
        </>
      ) : (
        <>
          <span>{shelf.label}</span>
          <span className="font-mono text-[11.5px] text-silt">{count}</span>
        </>
      )}
    </Link>
  );
}

export function TopicLink({ topic }: { topic: Topic }): JSX.Element {
  const { ref, isDropTarget } = useDropTarget(`topic:${topic.id}`, { kind: "topic", topic });
  return (
    <Link
      ref={ref}
      to="/topics/$topicId"
      params={{ topicId: topic.id }}
      data-drop={isDropTarget}
      className={cn("shelf", sideLinkClass, "justify-between py-1 pl-8 font-normal text-[13px]")}
    >
      <span className="min-w-0 truncate">{topic.name}</span>
      <span className="font-mono text-[11.5px] text-silt">{topic.kept}</span>
    </Link>
  );
}
