import type { Item, UserAction } from "@/api";

export type SwipeSide = "right" | "left";
export type SwipeActions = Partial<Record<SwipeSide, UserAction>>;
export type Axis = "x" | "y";

const RIGHT_ACTIONS: readonly UserAction[] = ["keep", "done", "undone"];
const SLOP = 8;
const RESIST_MAX = 24;

// The mouse drags rows to the shelves; every other pointer swipes them.
export function isMousePointer(event: { pointerType: string }): boolean {
  return event.pointerType === "mouse";
}

export function swipeActions(item: Pick<Item, "actions">): SwipeActions {
  return {
    right: RIGHT_ACTIONS.find((a) => item.actions.includes(a)),
    left: item.actions.includes("archive") ? "archive" : undefined,
  };
}

export function sideOf(dx: number): SwipeSide {
  return dx > 0 ? "right" : "left";
}

export function lockAxis(dx: number, dy: number): Axis | null {
  if (Math.max(Math.abs(dx), Math.abs(dy)) < SLOP) return null;
  return Math.abs(dx) > Math.abs(dy) ? "x" : "y";
}

export function commitDistance(width: number): number {
  return Math.min(140, Math.max(80, width * 0.3));
}

export function swipeOffset(dx: number, width: number, actions: SwipeActions): number {
  if (actions[sideOf(dx)] === undefined) return Math.sign(dx) * Math.min(RESIST_MAX, Math.abs(dx) / 4);
  return Math.sign(dx) * Math.min(width, Math.abs(dx));
}

export function swipeResult(dx: number, width: number, actions: SwipeActions): UserAction | null {
  if (Math.abs(dx) < commitDistance(width)) return null;
  return actions[sideOf(dx)] ?? null;
}
