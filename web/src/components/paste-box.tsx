import { Link, useNavigate } from "@tanstack/react-router";
import { ClipboardPaste, ImagePlus, Link2, Plus } from "lucide-react";
import {
  type ClipboardEvent as FieldClipboardEvent,
  type FormEvent,
  type JSX,
  type ReactNode,
  useEffect,
  useEffectEvent,
  useId,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { type Submission, useSubmitLinks } from "@/api";
import { useAddImages } from "@/components/image-set";
import { Button, buttonVariants } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { canReadClipboard, readClipboard } from "@/lib/clipboard";
import { IMAGE_TYPES } from "@/lib/limits";
import { cn } from "@/lib/utils";
import { SOURCES } from "@/lib/vocabulary";

const NO_LINK = "No Instagram or Threads link found in that text.";
const NO_CLIPBOARD = "Couldn't read the clipboard. Tap the field and paste.";
const NO_IMAGE = "Only images can be dropped here.";
const IMAGE_ACCEPT = [...IMAGE_TYPES, ".heic", ".heif"].join(",");

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
  const images = useAddImages();
  const say = useAnnounce();
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
    const files = pastedImages(clip.text, clip.files);
    if (files.length > 0) {
      void addImages(files);
      return;
    }
    setText(clip.text);
    send(clip.text);
  };
  const onFieldPaste = (event: FieldClipboardEvent<HTMLInputElement>) => {
    const text = pastedText(event.clipboardData);
    const files = pastedImages(text, [...event.clipboardData.files]);
    if (files.length > 0) {
      event.preventDefault();
      void addImages(files);
    } else if (text && !event.clipboardData.getData("text/plain")) {
      // The field inserts only text/plain, so a link that came as a URI list would vanish.
      event.preventDefault();
      setText(text);
    }
  };
  const addImages = async (files: File[]) => {
    const found = await images.add(files);
    if (found.length === 0) return;
    if (onAdded) onAdded(found);
    else for (const r of found) say(r);
  };

  return (
    <div>
      {pasteable && (
        <Button
          type="button"
          variant="primary"
          className="mb-3 h-12 w-full text-[15px] max-[700px]:h-12"
          disabled={submit.isPending || images.pending}
          onClick={paste}
        >
          <ClipboardPaste aria-hidden />
          Paste link or screenshot
        </Button>
      )}
      <div className="flex items-center gap-2">
        <form
          onSubmit={onSubmit}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2.5 rounded-xl border border-mesh bg-sheet pr-2 pl-4 focus-within:border-graphite",
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
            onPaste={onFieldPaste}
            placeholder={
              compact ? "Instagram reel or Threads post link" : "Paste an Instagram reel or Threads post link"
            }
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
        {!compact && <ImagePicker className="h-[52px] rounded-xl px-4" disabled={images.pending} onFiles={addImages} />}
      </div>
      {compact && <ImagePicker className="mt-2 h-11 w-full rounded-xl" disabled={images.pending} onFiles={addImages} />}
      {unread && <p className="px-1 pt-2 text-[13px] text-silt">{NO_CLIPBOARD}</p>}
      {submit.error && <FieldError className="px-1 pt-2">{submit.error.message}</FieldError>}
      {results && <SubmissionLines results={results} />}
    </div>
  );
}

function ImagePicker({
  className,
  disabled,
  onFiles,
}: {
  className: string;
  disabled: boolean;
  onFiles: (files: File[]) => void;
}): JSX.Element {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className={cn(
        buttonVariants({ variant: "secondary" }),
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-graphite has-[:focus-visible]:outline-offset-2",
        disabled && "pointer-events-none opacity-50",
        className,
      )}
    >
      <ImagePlus aria-hidden />
      {disabled ? "Adding..." : "Add image"}
      <input
        id={id}
        type="file"
        accept={IMAGE_ACCEPT}
        multiple
        aria-label="Add image"
        className="sr-only"
        disabled={disabled}
        onChange={(event) => {
          onFiles([...(event.target.files ?? [])]);
          event.target.value = "";
        }}
      />
    </label>
  );
}

export function SubmissionLines({ results }: { results: Submission[] }): JSX.Element {
  if (results.length === 0) return <FieldError className="px-1 pt-2">{NO_LINK}</FieldError>;
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
        <p className="px-1 pt-2 text-caption text-silt">
          Or press ⌘V anywhere outside a text field, or drop images on the window.
        </p>
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
          Copy a reel or Threads link, or a screenshot, then paste it here. Saved photos go through Add image.
        </p>
      </SheetContent>
    </Sheet>
  );
}

export function useAnnounce(): (r: Submission) => void {
  const navigate = useNavigate();
  return (r) => announce(r, (id) => navigate({ to: "/items/$itemId", params: { itemId: id } }));
}

export function PasteAnywhere(): null {
  const submit = useSubmitLinks();
  const images = useAddImages();
  const say = useAnnounce();

  const onPaste = useEffectEvent((event: ClipboardEvent) => {
    if (isEditable(event.target)) return;
    const text = event.clipboardData ? pastedText(event.clipboardData) : "";
    const files = pastedImages(text, [...(event.clipboardData?.files ?? [])]);
    if (files.length > 0) {
      event.preventDefault();
      void images.add(files).then((found) => found.forEach(say));
      return;
    }
    if (!hasLink(text)) return;
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

  return null;
}

const DRAG_EVENTS = ["dragstart", "dragend", "dragenter", "dragleave", "dragover", "drop"] as const;
const DRAG_DONE_EVENTS = ["drop", "pointermove", "mousemove"] as const;

export function DropAnywhere(): JSX.Element | null {
  const images = useAddImages();
  const say = useAnnounce();
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const fromPage = useRef(false);
  const dropFromPage = useRef(false);

  // A dragend never reaches the document when the dragged node is removed mid-drag. A drop ends the drag too,
  // and so does any mouse move, since none fire during one.
  const onDragDone = useEffectEvent((event: Event) => {
    if (event.type === "drop") dropFromPage.current = fromPage.current;
    fromPage.current = false;
  });

  const onDrag = useEffectEvent((event: DragEvent) => {
    // Chrome marks a drag of an image already on the page as carrying Files; only drags from outside upload.
    if (event.type === "dragstart" || event.type === "dragend") {
      fromPage.current = event.type === "dragstart";
      return;
    }
    const onPage = event.type === "drop" ? dropFromPage.current : fromPage.current;
    if (onPage || !carriesFiles(event)) return;
    switch (event.type) {
      case "dragenter":
        depth.current += 1;
        setOver(mayBeImages(event));
        return;
      case "dragleave":
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
        return;
      case "dragover":
        // Without this the browser opens a file dropped outside a drop zone and leaves Sift.
        event.preventDefault();
        return;
      case "drop": {
        depth.current = 0;
        setOver(false);
        // A nested zone that handles its own drop (the export zip) wins over this one.
        if (event.defaultPrevented) return;
        event.preventDefault();
        const files = [...(event.dataTransfer?.files ?? [])].filter(isImageFile);
        if (files.length === 0) toast.error(NO_IMAGE);
        else void images.add(files).then((found) => found.forEach(say));
      }
    }
  });

  useEffect(() => {
    const listener = (event: DragEvent) => onDrag(event);
    const done = (event: Event) => onDragDone(event);
    for (const type of DRAG_EVENTS) document.addEventListener(type, listener);
    for (const type of DRAG_DONE_EVENTS) document.addEventListener(type, done, true);
    return () => {
      for (const type of DRAG_EVENTS) document.removeEventListener(type, listener);
      for (const type of DRAG_DONE_EVENTS) document.removeEventListener(type, done, true);
    };
  }, []);

  if (!over) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-pan/80 p-6 backdrop-blur-sm">
      <div className="rounded-2xl border border-graphite border-dashed px-10 py-8 font-display font-[620] text-[19px]">
        Drop to add to Sift
      </div>
    </div>
  );
}

function carriesFiles(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes("Files") ?? false;
}

// Some browsers hide a dragged file's type until the drop, so an unknown type may still be an image.
function mayBeImages(event: DragEvent): boolean {
  const items = [...(event.dataTransfer?.items ?? [])].filter((i) => i.kind === "file");
  return items.length === 0 || items.some((i) => i.type === "" || IMAGE_TYPES.includes(i.type));
}

function pastedText(data: DataTransfer): string {
  return data.getData("text/plain") || data.getData("text/uri-list");
}

// Copying a post can bring its preview image along; the link is the post. A copied web image carries its own URL.
function pastedImages(text: string, files: File[]): File[] {
  return hasPostLink(text) ? [] : files.filter(isImageFile);
}

// An empty type is let through for the server to sniff: browsers leave HEIC and some drops untyped.
function isImageFile(file: File): boolean {
  return file.type === "" || IMAGE_TYPES.includes(file.type) || /\.(heic|heif)$/i.test(file.name);
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

/** A page's keyboard shortcut stays off while you type in a field or while any dialog or sheet is open. */
export function ignoresShortcut(event: KeyboardEvent): boolean {
  return isEditable(event.target) || document.querySelector("[role='dialog'], [role='alertdialog']") !== null;
}

function hasPostLink(text: string): boolean {
  return /https?:\/\/(?:www\.)?(?:instagram\.com|threads\.(?:com|net))\//i.test(text);
}

export function hasLink(text: string): boolean {
  return /https?:\/\/\S+/i.test(text);
}
