import { type QueryClient, useQuery } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  type ErrorComponentProps,
  Link,
  Outlet,
  useNavigate,
  useRouter,
} from "@tanstack/react-router";
import type { JSX } from "react";
import { toast } from "sonner";
import { ApiError, api, type ItemDetail, usePulse } from "@/api";
import { SieveMark } from "@/components/brand";
import { Dock } from "@/components/dock";
import { ImagesProvider } from "@/components/image-set";
import { AddLinkButton, DropAnywhere, PasteAnywhere, useAnnounce } from "@/components/paste-box";
import { SettingsMenu } from "@/components/settings-menu";
import { ShelfDnd, ShelfLink, sideLinkClass, TopicLink, useMoveItem } from "@/components/shelf";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/toaster";
import { DIGEST, SETTINGS, SHELVES, sidebarTopics, TOPICS } from "@/lib/nav";
import { ACTIONS } from "@/lib/vocabulary";

export type RouterContext = { queryClient: QueryClient };

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  loader: ({ context }) => context.queryClient.ensureQueryData(api.status),
  component: RootLayout,
  notFoundComponent: NotFound,
  errorComponent: RouteError,
});

function RootLayout(): JSX.Element {
  const status = usePulse(useAnnounceSettled());
  const announce = useAnnounce();
  return (
    <ShelfDnd>
      <ImagesProvider announce={announce}>
        <Dock nav={status.nav}>
          <div className="grid min-h-dvh grid-cols-[calc(232px+env(safe-area-inset-left))_minmax(0,1fr)] max-[700px]:grid-cols-1">
            <aside className="sticky top-0 flex h-dvh flex-col border-mesh border-r py-5 pr-3 pl-[calc(12px+env(safe-area-inset-left))] max-[700px]:hidden">
              <Link to="/" className="flex items-center gap-[9px] px-2.5 pt-1 pb-[22px]">
                <SieveMark className="size-[18px]" />
                <span className="font-display font-[620] text-[17px] tracking-[-0.01em]">sift</span>
              </Link>
              <nav aria-label="Shelves" className="flex flex-col gap-0.5">
                <Link to={DIGEST.to} className={sideLinkClass}>
                  <DIGEST.icon aria-hidden className="size-4 text-silt" strokeWidth={1.8} />
                  {DIGEST.label}
                </Link>
                <Link to={TOPICS.to} activeOptions={{ exact: true }} className={sideLinkClass}>
                  <TOPICS.icon aria-hidden className="size-4 text-silt" strokeWidth={1.8} />
                  <span className="flex-1">{TOPICS.label}</span>
                  <span className="font-mono text-[11.5px] text-silt">{status.nav.topics}</span>
                </Link>
                <SideTopics />
                {SHELVES.map((shelf) => (
                  <ShelfLink key={shelf.id} shelf={shelf} count={status.nav[shelf.id]} />
                ))}
                <AddLinkButton />
              </nav>
              <div className="mx-2.5 my-3 h-px bg-mesh" />
              <nav aria-label="More" className="flex flex-col gap-0.5">
                {SETTINGS.map((link) => (
                  <Link key={link.to} to={link.to} className={sideLinkClass}>
                    {link.label}
                  </Link>
                ))}
              </nav>
              <SettingsMenu className="mt-auto ml-0.5 self-start" />
            </aside>
            <main className="min-w-0 pt-11 pr-[max(56px,env(safe-area-inset-right))] pl-14 pb-16 max-[700px]:pr-[max(16px,env(safe-area-inset-right))] max-[700px]:pl-[max(16px,env(safe-area-inset-left))] max-[700px]:pt-[calc(20px+env(safe-area-inset-top))] max-[700px]:pb-[calc(var(--dock-h,72px)+28px)]">
              <Outlet />
            </main>
          </div>
        </Dock>
        <DropAnywhere />
        <PasteAnywhere />
      </ImagesProvider>
      <Toaster />
    </ShelfDnd>
  );
}

function SideTopics(): JSX.Element {
  const { data } = useQuery(api.topics);
  const topics = data ? sidebarTopics(data) : [];
  return (
    <ul aria-label="Topics with kept posts" className="mb-3 flex max-h-[34vh] flex-col gap-px overflow-y-auto">
      {topics.map((topic) => (
        <li key={topic.id}>
          <TopicLink topic={topic} />
        </li>
      ))}
    </ul>
  );
}

function useAnnounceSettled(): (item: ItemDetail) => void {
  const navigate = useNavigate();
  const move = useMoveItem();
  return (item) => {
    const open = { label: "Open", onClick: () => navigate({ to: "/items/$itemId", params: { itemId: item.id } }) };
    switch (item.status) {
      case "kept":
        toast(
          item.wishlist
            ? `On your wishlist: ${item.display_title}`
            : `Kept: ${item.display_title}, ${item.relevance_score}`,
          { action: open },
        );
        return;
      case "archived":
        toast(`Archived: ${item.display_title}`, {
          action: { label: ACTIONS.keep.label, onClick: () => void move(item, "keep") },
        });
        return;
      case "failed":
        toast.error(`Failed: ${item.display_title}`, { description: item.status_reason, action: open });
        return;
      default:
        return;
    }
  };
}

function NotFound(): JSX.Element {
  return (
    <div className="max-w-[848px] py-16">
      <h1 className="font-display font-[640] text-page">Not here</h1>
      <p className="mt-2 text-silt">This page doesn't exist, or the item it pointed to is gone.</p>
      <Button asChild className="mt-6">
        <Link to="/inbox">Go to the Inbox</Link>
      </Button>
    </div>
  );
}

function RouteError({ error }: ErrorComponentProps): JSX.Element {
  const router = useRouter();
  const message = error instanceof ApiError ? error.message : "Something went wrong loading this page.";
  return (
    <div className="max-w-[848px] py-16">
      <h1 className="font-display font-[640] text-page">Couldn't load this page</h1>
      <p className="mt-2 text-silt">{message}</p>
      <div className="mt-6 flex gap-2">
        <Button variant="primary" onClick={() => router.invalidate()}>
          Try again
        </Button>
        <Button asChild>
          <Link to="/inbox">Go to the Inbox</Link>
        </Button>
      </div>
    </div>
  );
}
