export const DOCK_HEIGHT_VAR = "--dock-h";

type VisualViewportLike = Pick<VisualViewport, "height" | "offsetTop">;

// iOS Safari leaves fixed elements at the layout viewport's bottom, behind the keyboard.
export function keyboardInset(layoutHeight: number, viewport: VisualViewportLike): number {
  return Math.max(0, Math.round(layoutHeight - viewport.height - viewport.offsetTop));
}
