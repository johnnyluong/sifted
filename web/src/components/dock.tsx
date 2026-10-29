import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronRight, Ellipsis, Plus } from "lucide-react";
import {
  createContext,
  type JSX,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type { NavCounts } from "@/api";
import { AddLinkSheet } from "@/components/paste-box";
import { ShelfLink, tabClass } from "@/components/shelf";
import { ThemePicker } from "@/components/theme-picker";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { DIGEST, inMore, MORE, SHELVES } from "@/lib/nav";
import { DOCK_HEIGHT_VAR } from "@/lib/viewport";

type DockContext = { slot: HTMLElement | null; addLink: () => void };

const DockContext = createContext<DockContext>({ slot: null, addLink: () => {} });

export function useAddLink(): () => void {
  return useContext(DockContext).addLink;
}

export function DockPortal({ children }: { children: ReactNode }): JSX.Element | null {
  const { slot } = useContext(DockContext);
  return slot ? createPortal(children, slot) : null;
}

export function Dock({ nav, children }: { nav: NavCounts; children: ReactNode }): JSX.Element {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [adding, setAdding] = useState(false);
  const [more, setMore] = useState(false);
  const dock = usePublishDockHeight();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [inbox, kept] = SHELVES;
  const tab = (shelf: (typeof SHELVES)[number] | undefined) =>
    shelf && <ShelfLink key={shelf.id} shelf={shelf} count={nav[shelf.id]} tab />;
  const opener = useRef<HTMLElement | null>(null);
  const context = useMemo(
    () => ({
      slot,
      addLink: () => {
        opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setAdding(true);
      },
    }),
    [slot],
  );
  return (
    <DockContext.Provider value={context}>
      {children}
      <div
        ref={dock}
        className="fixed inset-x-0 bottom-0 z-40 hidden flex-col border-mesh border-t bg-pan/85 backdrop-blur-xl max-[700px]:flex"
      >
        <div ref={setSlot} />
        <nav
          aria-label="Shelves"
          className="grid grid-cols-5 pr-[max(4px,env(safe-area-inset-right))] pl-[max(4px,env(safe-area-inset-left))] pt-1.5 pb-[max(6px,env(safe-area-inset-bottom))]"
        >
          {tab(inbox)}
          <Link to={DIGEST.to} className={tabClass}>
            <DIGEST.icon aria-hidden className="size-[19px]" />
            <span>{DIGEST.label}</span>
          </Link>
          <AddLinkSheet
            open={adding}
            onOpenChange={setAdding}
            onCloseAutoFocus={(event) => {
              const el = opener.current;
              opener.current = null;
              if (!el?.isConnected) return;
              event.preventDefault();
              el.focus();
            }}
            trigger={
              <button
                type="button"
                aria-label="Add a link"
                className="grid min-h-[50px] cursor-pointer place-items-center"
              >
                <span className="grid h-10 w-14 place-items-center rounded-[14px] bg-graphite text-sheet active:opacity-80">
                  <Plus aria-hidden className="size-[22px]" strokeWidth={2.2} />
                </span>
              </button>
            }
          />
          {tab(kept)}
          <MoreSheet
            nav={nav}
            open={more}
            onOpenChange={setMore}
            trigger={
              <button type="button" data-status={inMore(pathname) ? "active" : undefined} className={tabClass}>
                <Ellipsis aria-hidden className="size-[19px]" />
                <span>More</span>
              </button>
            }
          />
        </nav>
      </div>
    </DockContext.Provider>
  );
}

function MoreSheet({
  nav,
  open,
  onOpenChange,
  trigger,
}: {
  nav: NavCounts;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactNode;
}): JSX.Element {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent title="More">
        <ul className="overflow-hidden rounded-xl border border-mesh">
          {MORE.map((d) => (
            <li key={d.to} className="border-mesh border-t first:border-t-0">
              <Link
                to={d.to}
                onClick={() => onOpenChange(false)}
                className="flex min-h-14 items-center gap-3.5 px-4 py-2.5 active:bg-hover data-[status=active]:bg-hover"
              >
                <d.icon aria-hidden className="size-[18px] shrink-0 text-silt" strokeWidth={1.8} />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-[15px]">{d.label}</span>
                  <span className="block truncate text-caption text-silt">{d.hint}</span>
                </span>
                {d.count && <span className="font-mono text-caption text-silt">{nav[d.count]}</span>}
                <ChevronRight aria-hidden className="size-4 shrink-0 text-dust" />
              </Link>
            </li>
          ))}
        </ul>
        <Eyebrow as="p" className="mt-5 mb-2">
          Appearance
        </Eyebrow>
        <ThemePicker />
      </SheetContent>
    </Sheet>
  );
}

function usePublishDockHeight(): (el: HTMLDivElement | null) => void {
  const observer = useRef<ResizeObserver | null>(null);
  useEffect(() => () => observer.current?.disconnect(), []);
  return useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    if (!el) return;
    observer.current = new ResizeObserver(() =>
      document.documentElement.style.setProperty(DOCK_HEIGHT_VAR, `${el.offsetHeight}px`),
    );
    observer.current.observe(el);
  }, []);
}
