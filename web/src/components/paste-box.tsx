import { Link, useNavigate } from "@tanstack/react-router";
import { ClipboardPaste, Link2, Plus } from "lucide-react";
import { type FormEvent, type JSX, type ReactNode, useEffect, useEffectEvent, useRef, useState } from "react";
import { toast } from "sonner";
import { type Submission, useSubmitLinks } from "@/api";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { canReadClipboard, readClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { SOURCES } from "@/lib/vocabulary";

const NO_LINK = "No Instagram or Threads link found in that text.";
const NO_CLIPBOARD = "Couldn't read the clipboard. Tap the field and paste.";

export function LinkForm({
  autoFocus,
  compact,
  onAdded,
}: {
  autoFocus?: boolean;
  compact?: boolean;
  onAdded?: (results: Submission[]) => void;
}): JSX.Element {
  const submit = useSubmitLinks();
  const [text, setText] = useState("");
  const [results, setResults] = useState<Submission[] | null>(null);
  const [unread, setUnread] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const pasteable = onAdded !== undefined && canReadClipboard();

  const send = (value: string) => {
    if (!value.trim()) return;
    submit.mutate(value, {
      onSuccess: (found) => {
        const added = found.some((r) => r.kind !== "rejected");
        if (added) setText("");
        if (added && onAdded) {
          setResults(null);
          onAdded(found);
        } else setResults(found);
      },
    });
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    send(text);
  };
  // Focusing first would raise the iOS keyboard on every paste; after the read it may not rise, hence the hint.
  const paste = async () => {
    setUnread(false);
    const clip = await readClipboard();
    if (clip === null) {
      setUnread(true);
      field.current?.focus();
      return;
    }
    setText(clip);
    send(clip);
  };

  return (
    <div>
      {pasteable && (
        <Button
          type="button"
          variant="primary"
          className="mb-3 h-12 w-full text-[15px] max-[700px]:h-12"
          disabled={submit.isPending}
          onClick={paste}
        >
          <ClipboardPaste aria-hidden />
          Paste link from clipboard
        </Button>
      )}
      <form
        onSubmit={onSubmit}
        className={cn(
          "flex items-center gap-2.5 rounded-xl border border-mesh bg-sheet pr-2 pl-4 focus-within:border-graphite",
          compact ? "h-11 max-[700px]:h-12" : "h-[52px]",
        )}
      >
        <Link2 aria-hidden className="size-4 shrink-0 text-silt" />
        <input
          // biome-ignore lint/a11y/noAutofocus: the popover opens for exactly this field.
          autoFocus={autoFocus}
          ref={field}
          aria-label="Link to add"
          inputMode="url"
          enterKeyHint="go"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={compact ? "Instagram reel or Threads post link" : "Paste an Instagram reel or Threads post link"}
          className={cn(
            "min-w-0 flex-1 bg-transparent outline-none placeholder:text-dust focus-visible:outline-none max-[700px]:text-base",
            !compact && "text-[15px]",
          )}
        />
        {!compact && (
          <kbd className="hidden rounded-[5px] border border-mesh px-1.5 py-px font-mono text-[11px] text-silt sm:inline">
            ⌘V anywhere
          </kbd>
        )}
        <Button type="submit" variant={pasteable ? "secondary" : "primary"} disabled={submit.isPending}>
          Add
        </Button>
      </form>
      {unread && <p className="px-1 pt-2 text-[13px] text-silt">{NO_CLIPBOARD}</p>}
      {submit.error && <p className="px-1 pt-2 text-[13px] text-alarm">{submit.error.message}</p>}
      {results && <SubmissionLines results={results} />}
    </div>
  );
}

export function SubmissionLines({ results }: { results: Submission[] }): JSX.Element {
  if (results.length === 0) return <p className="px-1 pt-2 text-[13px] text-alarm">{NO_LINK}</p>;
  return (
    <ul className="space-y-1 px-1 pt-2 text-[13px] text-silt">
      {results.map((r, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: one paste can repeat a link, and the list never reorders.
        <li key={i}>
          {r.kind === "queued" && (
            <>
              <b className="font-[560] text-graphite">Added.</b> Processing{" "}
              <Link to="/items/$itemId" params={{ itemId: r.item.id }} className="underline underline-offset-2">
                {SOURCES[r.item.source].label} post
              </Link>
              .
            </>
          )}
          {r.kind === "duplicate" && (
            <>
              Already saved:{" "}
              <Link
                to="/items/$itemId"
                params={{ itemId: r.item.id }}
                className="text-graphite underline underline-offset-2"
              >
                {r.item.display_title}
              </Link>{" "}
              ({r.item.state_label.toLowerCase()}).
            </>
          )}
          {r.kind === "rejected" && (
            <span className="text-alarm">
              <span className="font-mono text-caption">{truncate(r.url, 60)}</span>: {r.reason}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function AddLinkButton(): JSX.Element {
  return (
    <Popover>
      <PopoverTrigger className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 font-medium text-silt hover:bg-pan-hover hover:text-graphite">
        <Plus aria-hidden className="size-3.5" />
        <span>Add link</span>
      </PopoverTrigger>
      <PopoverContent side="right" align="start">
        <LinkForm autoFocus compact />
        <p className="px-1 pt-2 text-caption text-silt">Or press ⌘V anywhere outside a text field.</p>
      </PopoverContent>
    </Popover>
  );
}

export function AddLinkSheet({
  open,
  onOpenChange,
  onCloseAutoFocus,
  trigger,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus: (event: Event) => void;
  trigger: ReactNode;
}): JSX.Element {
  const say = useAnnounce();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent
        title="Add a link"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <LinkForm
          compact
          autoFocus={!canReadClipboard()}
          onAdded={(results) => {
            onOpenChange(false);
            for (const r of results) say(r);
          }}
        />
        <p className="px-1 pt-3 pb-1 text-caption text-silt">
          Share or copy a reel or Threads post link, then add it here.
        </p>
      </SheetContent>
    </Sheet>
  );
}

function useAnnounce(): (r: Submission) => void {
  const navigate = useNavigate();
  return (r) => announce(r, (id) => navigate({ to: "/items/$itemId", params: { itemId: id } }));
}

export function usePasteAnywhere(): void {
  const submit = useSubmitLinks();
  const say = useAnnounce();

  const onPaste = useEffectEvent((event: ClipboardEvent) => {
    const text = event.clipboardData?.getData("text/plain") ?? "";
    if (isEditable(event.target) || !hasLink(text)) return;
    event.preventDefault();
    submit.mutate(text, {
      onSuccess: (results) => {
        if (results.length === 0) toast.error(NO_LINK);
        for (const r of results) say(r);
      },
      onError: (error) => toast.error(error.message),
    });
  });

  useEffect(() => {
    const listener = (event: ClipboardEvent) => onPaste(event);
    document.addEventListener("paste", listener);
    return () => document.removeEventListener("paste", listener);
  }, []);
}

function announce(r: Submission, open: (id: number) => void): void {
  switch (r.kind) {
    case "queued":
      toast(`Added. Processing ${SOURCES[r.item.source].label} post.`, {
        action: { label: "View", onClick: () => open(r.item.id) },
      });
      return;
    case "duplicate":
      toast(`Already saved: ${r.item.display_title} (${r.item.state_label.toLowerCase()}).`, {
        action: { label: "Open", onClick: () => open(r.item.id) },
      });
      return;
    case "rejected":
      toast.error(`${truncate(r.url, 60)}: ${r.reason}`);
      return;
  }
}

export function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target.closest("input, textarea, select, [contenteditable='true']") !== null;
}

export function hasLink(text: string): boolean {
  return /https?:\/\/\S+/i.test(text);
}
