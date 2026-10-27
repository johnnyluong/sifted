import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import type { JSX } from "react";
import { api, type ListFilter } from "@/api";
import { useAddLink } from "@/components/dock";
import { ItemList } from "@/components/item-list";
import { Empty, Page, PageHeader } from "@/components/page";
import { LinkForm } from "@/components/paste-box";
import { Button } from "@/components/ui/button";
import { activeImport } from "@/lib/imports";
import { ImportBanner } from "./import";
import { rootRoute } from "./root";

const INBOX: ListFilter = { view: "inbox" };

export const inboxRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/inbox",
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.ensureQueryData(api.items(INBOX)),
      context.queryClient.ensureQueryData(api.imports),
    ]),
  component: InboxPage,
});

function InboxPage(): JSX.Element {
  const { data: items } = useSuspenseQuery(api.items(INBOX));
  const running = activeImport(useSuspenseQuery(api.imports).data);
  const addLink = useAddLink();
  return (
    <Page>
      <PageHeader
        title="Inbox"
        subtitle="Links being downloaded, read and scored. Finished ones move to Kept or Archived."
      />
      <div className="mb-7 max-[700px]:hidden">
        <LinkForm />
      </div>
      {running && <ImportBanner view={running} />}
      <ItemList
        items={items}
        variant="inbox"
        empty={
          <Empty title="Nothing in progress">
            Add a reel or Threads link; Sift downloads it, reads it, and scores it against your goals.
            <Button variant="primary" className="mt-4 hidden max-[700px]:mx-auto max-[700px]:flex" onClick={addLink}>
              Add a link
            </Button>
          </Empty>
        }
      />
    </Page>
  );
}
