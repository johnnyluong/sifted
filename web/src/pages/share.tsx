import { createRoute } from "@tanstack/react-router";
import { Copy } from "lucide-react";
import type { JSX, ReactNode } from "react";
import { toast } from "sonner";
import { Page, PageHeader, PageSection } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { writeClipboard } from "@/lib/clipboard";
import { rootRoute } from "./root";

export const shareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/share",
  component: SharePage,
});

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function Ui({ children }: { children: ReactNode }): JSX.Element {
  return <span className="font-[560] text-graphite">{children}</span>;
}

type Entry = { id: string; body: ReactNode };

const BUILD: Entry[] = [
  {
    id: "new",
    body: (
      <>
        Open the Shortcuts app, tap <Ui>+</Ui>, and name the new shortcut <Ui>Save to Sift</Ui>.
      </>
    ),
  },
  {
    id: "share-sheet",
    body: (
      <>
        Tap the info button and turn on <Ui>Show in Share Sheet</Ui>.
      </>
    ),
  },
  {
    id: "receive",
    body: (
      <>
        At the top of the shortcut, tap the input types after <Ui>Receive</Ui> and keep only <Ui>Images</Ui>,{" "}
        <Ui>URLs</Ui>, <Ui>Safari web pages</Ui> and <Ui>Text</Ui>.
      </>
    ),
  },
  {
    id: "urls",
    body: (
      <>
        Add the <Ui>Get URLs from Input</Ui> action. Below it, add <Ui>If</Ui>, and set it to <Ui>URLs</Ui>{" "}
        <Ui>has any value</Ui>.
      </>
    ),
  },
  {
    id: "action",
    body: (
      <>
        Inside the If, add the <Ui>Get Contents of URL</Ui> action and set its URL to the link address above.
      </>
    ),
  },
  {
    id: "method",
    body: (
      <>
        Tap the arrow on that action to show its options. Set <Ui>Method</Ui> to <Ui>POST</Ui> and <Ui>Request Body</Ui>{" "}
        to <Ui>JSON</Ui>.
      </>
    ),
  },
  {
    id: "field",
    body: (
      <>
        Tap <Ui>Add new field</Ui> and choose <Ui>Text</Ui>. Type <code className="font-mono">text</code> as the key,
        and choose <Ui>Shortcut Input</Ui> as the value.
      </>
    ),
  },
  {
    id: "images",
    body: (
      <>
        Under <Ui>Otherwise</Ui>, add the <Ui>Get Images from Input</Ui> action. Below it, add <Ui>Repeat with Each</Ui>{" "}
        and choose <Ui>Images</Ui>. Inside the repeat, add another <Ui>Get Contents of URL</Ui> action and set its URL
        to the image address above.
      </>
    ),
  },
  {
    id: "upload-method",
    body: (
      <>
        Tap the arrow on that action to show its options. Set <Ui>Method</Ui> to <Ui>POST</Ui> and <Ui>Request Body</Ui>{" "}
        to <Ui>File</Ui>, and choose <Ui>Repeat Item</Ui> as the file.
      </>
    ),
  },
  {
    id: "notify",
    body: (
      <>
        After <Ui>End If</Ui>, add the <Ui>Show Notification</Ui> action and type <Ui>Sent to Sift</Ui> as its message.
        Then tap <Ui>Done</Ui>.
      </>
    ),
  },
];

const SEND: Entry[] = [
  {
    id: "threads",
    body: (
      <>
        <Ui>From Threads.</Ui> Tap the share button under the post, then <Ui>Share via</Ui> to open the iPhone share
        sheet. Tap <Ui>Save to Sift</Ui>.
      </>
    ),
  },
  {
    id: "instagram",
    body: (
      <>
        <Ui>From Instagram.</Ui> Tap the share button under the post, then <Ui>Share</Ui> at the end of the bottom row
        to open the iPhone share sheet. Tap <Ui>Save to Sift</Ui>.
      </>
    ),
  },
  {
    id: "photos",
    body: (
      <>
        <Ui>From Photos, or a screenshot.</Ui> Tap the share button on a photo, or on the preview of a screenshot you
        just took, then tap <Ui>Save to Sift</Ui>. Each image becomes its own post.
      </>
    ),
  },
  {
    id: "missing",
    body: (
      <>
        Not in the list? Scroll to the end of the actions, tap <Ui>Edit Actions</Ui> or <Ui>More</Ui>, and add{" "}
        <Ui>Save to Sift</Ui>.
      </>
    ),
  },
];

const TROUBLE: { id: string; problem: string; fix: ReactNode }[] = [
  {
    id: "nothing",
    problem: "Nothing arrives, or the shortcut can't connect",
    fix: "Turn on Tailscale on the iPhone, and check that Sift is running on the Mac.",
  },
  {
    id: "403",
    problem: "The shortcut shows a 403 error",
    fix: "Sift refused the request because it looked like it came from another website. Send it from the shortcut's Get Contents of URL action, with the address above exactly as shown.",
  },
  {
    id: "422",
    problem: "The shortcut shows a 422 error",
    fix: (
      <>
        Name the field <code className="font-mono">text</code>, and set Request Body to JSON.
      </>
    ),
  },
  {
    id: "415",
    problem: "The shortcut shows a 415 error",
    fix: (
      <>
        Sift reads PNG, JPEG, WebP, GIF and HEIC images. Set Request Body to File, and choose Repeat Item as the file.
      </>
    ),
  },
  {
    id: "413",
    problem: "The shortcut shows a 413 error",
    fix: "The image is larger than Sift takes: 25 MB, unless UPLOAD_MAX_BYTES says otherwise.",
  },
  {
    id: "rejected",
    problem: "The notification shows, but the post never reaches the Inbox",
    fix: "Sift rejected the link. It reads only Instagram and Threads posts and reels, not profiles, stories or other sites. To see Sift's answer, set the notification's message to Contents of URL.",
  },
];

function Address({ label, path }: { label: string; path: string }): JSX.Element {
  const endpoint = `${window.location.origin}${path}`;
  const copy = async () => {
    if (await writeClipboard(endpoint)) toast(`Copied the ${label.toLowerCase()}`);
    else toast.error("Couldn't copy. Select the address and copy it.");
  };
  return (
    <div>
      <div className="mb-1.5 font-[560] text-caption text-silt">{label}</div>
      <div className="flex items-center gap-3 max-[700px]:flex-col max-[700px]:items-stretch">
        <Input
          readOnly
          aria-label={label}
          value={endpoint}
          onFocus={(event) => event.currentTarget.select()}
          className="flex-1 bg-pan font-mono text-[13px] max-[700px]:flex-none max-[700px]:text-[13px]"
        />
        <Button onClick={copy} aria-label={`Copy the ${label.toLowerCase()}`}>
          <Copy aria-hidden />
          Copy
        </Button>
      </div>
    </div>
  );
}

function SharePage(): JSX.Element {
  const local = LOCAL_HOSTS.has(window.location.hostname);
  return (
    <Page>
      <PageHeader
        title="Save from iPhone"
        subtitle="Send a Threads or Instagram post, a photo or a screenshot to Sift from the iPhone share sheet, through an Apple Shortcut."
      />

      <PageSection title="Sift's addresses" className="mt-8">
        <div className="surface surface-pad flex flex-col gap-4">
          <Address label="Link address" path="/api/items" />
          <Address label="Image address" path="/api/uploads" />
          <p className="text-caption text-silt">
            {local
              ? "These addresses work only on this computer. Open this page on your iPhone through your Tailscale address, and copy them there."
              : "Your iPhone reaches these addresses only while Tailscale is on."}
          </p>
        </div>
      </PageSection>

      <PageSection title="Build the shortcut">
        <ol className="surface surface-pad flex flex-col gap-2.5">
          {BUILD.map((entry, i) => (
            <li key={entry.id} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 text-ink-soft">
              <span className="font-mono text-silt">{i + 1}</span>
              <span>{entry.body}</span>
            </li>
          ))}
        </ol>
      </PageSection>

      <PageSection title="Send a post or an image">
        <p className="mb-3 text-ink-soft">
          Turn on Tailscale on the iPhone first. Sift is reachable only on your tailnet.
        </p>
        <div className="surface surface-pad flex flex-col gap-2.5 text-ink-soft">
          {SEND.map((entry) => (
            <p key={entry.id}>{entry.body}</p>
          ))}
        </div>
        <p className="mt-3 text-caption text-silt">It shows up in the Inbox a moment later.</p>
      </PageSection>

      <PageSection title="If it doesn't work">
        <dl className="surface">
          {TROUBLE.map((t) => (
            <div key={t.id} className="border-mesh border-t px-4 py-3.5 first:border-t-0">
              <dt className="font-semibold">{t.problem}</dt>
              <dd className="mt-0.5 text-ink-soft">{t.fix}</dd>
            </div>
          ))}
        </dl>
      </PageSection>
    </Page>
  );
}
