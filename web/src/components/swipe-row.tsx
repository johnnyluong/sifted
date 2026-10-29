import { Archive, Check, Trash2, Undo2 } from "lucide-react";
import { type JSX, type PointerEvent, type ReactNode, useRef, useState } from "react";
import type { Item } from "@/api";
import { ConfirmDelete, DELETE_LABEL } from "@/components/delete-post";
import type { MoveItem } from "@/components/shelf";
import {
  type Axis,
  commitDistance,
  isMousePointer,
  lockAxis,
  type SwipeAction,
  sideOf,
  swipeActions,
  swipeOffset,
  swipeResult,
} from "@/lib/swipe";
import { cn } from "@/lib/utils";
import { actionWords } from "@/lib/vocabulary";

type Gesture = { pointer: number; x: number; y: number; axis: Axis | null; width: number };

const ICONS: Partial<Record<SwipeAction, typeof Check>> = {
  keep: Check,
  done: Check,
  undone: Undo2,
  archive: Archive,
  delete: Trash2,
};

export function SwipeRow({ item, move, children }: { item: Item; move: MoveItem; children: ReactNode }): JSX.Element {
  const actions = swipeActions(item);
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [width, setWidth] = useState(0);
  const gesture = useRef<Gesture | null>(null);
  // Set once a gesture locks to x, so the click a browser fires on lifting that finger is swallowed.
  const swiped = useRef(false);
  const [confirming, setConfirming] = useState(false);
  useResetOnStatusChange(item.status, () => setDx(0));

  if (!actions.right && !actions.left) return <>{children}</>;

  const end = (event: PointerEvent<HTMLDivElement>, cancelled: boolean) => {
    const g = gesture.current;
    if (!g || g.pointer !== event.pointerId) return;
    gesture.current = null;
    setDragging(false);
    if (g.axis !== "x") return;
    const travel = event.clientX - g.x;
    const action = cancelled ? null : swipeResult(travel, g.width, actions);
    if (!action) {
      setDx(0);
      return;
    }
    setDx(Math.sign(travel) * g.width);
    if (action === "delete") {
      setConfirming(true);
      return;
    }
    void move(item, action).then((after) => {
      // A new status resets the row, or drops it from a list that refetches a tick after this resolves.
      if (!after || after.status === item.status) setDx(0);
    });
  };

  const side = sideOf(dx);
  const action = actions[side];
  const Icon = action ? ICONS[action] : undefined;
  const armed = width > 0 && Math.abs(dx) >= commitDistance(width);
  return (
    <div className={cn("relative", dx !== 0 && "z-[2]")}>
      {dx !== 0 && action && (
        <div
          aria-hidden
          className={cn(
            "absolute inset-0 flex items-center gap-2 whitespace-nowrap px-5 font-[560] text-[13px] transition-opacity",
            !armed && dragging && "opacity-60",
            side === "right" && "justify-start bg-graphite text-sheet",
            side === "left" &&
              (action === "delete" ? "justify-end bg-alarm text-sheet" : "justify-end bg-mesh text-graphite"),
          )}
        >
          {Icon && <Icon className="size-4" />}
          {action === "delete" ? DELETE_LABEL : actionWords(action, item).label}
        </div>
      )}
      <div
        className={cn(
          "group/row relative touch-pan-y bg-sheet",
          !dragging && "transition-transform duration-200 ease-out",
        )}
        style={{ transform: dx ? `translateX(${dx}px)` : undefined }}
        onPointerDown={(event) => {
          swiped.current = false;
          if (isMousePointer(event) || !event.isPrimary) return;
          gesture.current = {
            pointer: event.pointerId,
            x: event.clientX,
            y: event.clientY,
            axis: null,
            width: event.currentTarget.offsetWidth,
          };
        }}
        onPointerMove={(event) => {
          const g = gesture.current;
          if (!g || g.pointer !== event.pointerId) return;
          const travel = event.clientX - g.x;
          if (g.axis === null) {
            g.axis = lockAxis(travel, event.clientY - g.y);
            if (g.axis === "y") gesture.current = null;
            if (g.axis !== "x") return;
            swiped.current = true;
            setDragging(true);
            setWidth(g.width);
          }
          setDx(swipeOffset(travel, g.width, actions));
        }}
        onPointerUp={(event) => end(event, false)}
        onPointerCancel={(event) => end(event, true)}
        onClickCapture={(event) => {
          // A keyboard or assistive click has detail 0 and is never the tail of a swipe.
          if (event.detail === 0 || !swiped.current) return;
          swiped.current = false;
          event.preventDefault();
          event.stopPropagation();
        }}
      >
        {children}
        {actions.left === "delete" && (
          <button
            type="button"
            aria-label={`${DELETE_LABEL} ${item.display_title}`}
            onClick={() => setConfirming(true)}
            className="absolute top-1/2 right-[calc(var(--rail-end)+var(--rail-w)+8px)] grid size-8 -translate-y-1/2 cursor-pointer place-items-center rounded-md border border-mesh bg-sheet text-silt opacity-0 transition-opacity hover:border-alarm/40 hover:text-alarm focus-visible:opacity-100 group-hover/row:opacity-100 max-[700px]:hidden [@media(hover:none)]:hidden"
          >
            <Trash2 aria-hidden className="size-3.5" />
          </button>
        )}
      </div>
      {confirming && (
        <ConfirmDelete
          item={item}
          open
          onClose={(deleted) => {
            setConfirming(false);
            if (!deleted) setDx(0);
          }}
        />
      )}
    </div>
  );
}

function useResetOnStatusChange(status: Item["status"], reset: () => void): void {
  const [seen, setSeen] = useState(status);
  if (status !== seen) {
    setSeen(status);
    reset();
  }
}
