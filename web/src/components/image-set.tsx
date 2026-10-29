import { ImageOff, X } from "lucide-react";
import { createContext, type JSX, type ReactNode, use, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { type Submission, useAddImageSet, useStoreImage, useUploadImage } from "@/api";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { IMAGE_SET_MAX } from "@/lib/limits";

const STILL_OPEN = "Finish the images already open first.";
const NOT_ADDED = "Nothing was added: one post needs every image. Remove the refused one and add them again.";

type AddAs = "one" | "each";
type Heard = () => boolean;
type Ask = { files: File[]; heard: Heard; reply: (found: Submission[]) => void };
type Images = { add: (files: File[], heard: Heard) => Promise<Submission[]>; pending: boolean };

const ImagesContext = createContext<Images | null>(null);

export function useAddImages(): { add: (files: File[]) => Promise<Submission[]>; pending: boolean } {
  const images = use(ImagesContext);
  if (!images) throw new Error("useAddImages needs an ImagesProvider above it.");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return { add: (files) => images.add(files, () => mounted.current), pending: images.pending };
}

export function ImagesProvider({
  announce,
  children,
}: {
  announce: (r: Submission) => void;
  children: ReactNode;
}): JSX.Element {
  const upload = useUploadImage();
  const store = useStoreImage();
  const combine = useAddImageSet();
  const [ask, setAsk] = useState<Ask | null>(null);
  const asking = useRef(false);
  const [busy, setBusy] = useState(0);

  const each = async (files: File[]) => {
    const found: Submission[] = [];
    for (const file of files) {
      try {
        found.push(...(await upload.mutateAsync(file)));
      } catch (error) {
        toast.error(`${file.name}: ${messageOf(error)}`);
      }
    }
    return found;
  };
  const asOne = async (files: File[]) => {
    const stored = await Promise.allSettled(files.map((file) => store.mutateAsync(file)));
    const names: string[] = [];
    stored.forEach((result, i) => {
      if (result.status === "fulfilled") names.push(result.value.name);
      else toast.error(`${files[i]?.name}: ${messageOf(result.reason)}`);
    });
    if (names.length < files.length) {
      toast.error(NOT_ADDED);
      return [];
    }
    try {
      return await combine.mutateAsync(names);
    } catch (error) {
      toast.error(messageOf(error));
      return [];
    }
  };
  // The work outlives its caller; a caller gone by the end gets [] and the results are announced here instead.
  const run = async (files: File[], as: AddAs, heard: Heard) => {
    setBusy((n) => n + 1);
    let found: Submission[];
    try {
      found = await (as === "one" ? asOne : each)(files);
    } finally {
      setBusy((n) => n - 1);
    }
    if (heard()) return found;
    for (const r of found) announce(r);
    return [];
  };
  const add = (files: File[], heard: Heard): Promise<Submission[]> => {
    if (asking.current) {
      toast.error(STILL_OPEN);
      return Promise.resolve([]);
    }
    if (files.length < 2) return run(files, "each", heard);
    asking.current = true;
    return new Promise((reply) => setAsk({ files, heard, reply }));
  };

  return (
    <ImagesContext value={{ add, pending: busy > 0 }}>
      {children}
      {ask && (
        <ImageSetSheet
          files={ask.files}
          onCancel={() => {
            asking.current = false;
            setAsk(null);
            ask.reply([]);
          }}
          onAdd={(files, as) => {
            asking.current = false;
            setAsk(null);
            void run(files, as, ask.heard).then(ask.reply);
          }}
        />
      )}
    </ImagesContext>
  );
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function ImageSetSheet({
  files,
  onAdd,
  onCancel,
}: {
  files: File[];
  onAdd: (files: File[], as: AddAs) => void;
  onCancel: () => void;
}): JSX.Element {
  const [kept, setKept] = useState(() => files.map((file, id) => ({ id, file })));
  const count = kept.length;
  const over = count - IMAGE_SET_MAX;
  const chosen = () => kept.map((k) => k.file);
  return (
    <Sheet open onOpenChange={(open) => !open && onCancel()}>
      <SheetContent title={`Add ${count} images`} narrow>
        <p className="text-[13px] text-silt">
          One post reads them together in this order, up to {IMAGE_SET_MAX} images.
        </p>
        <ol aria-label="Images in reading order" className="mt-3 grid grid-cols-4 gap-2 max-[700px]:grid-cols-3">
          {kept.map(({ id, file }, i) => (
            <li key={id} className="relative aspect-[3/4] overflow-hidden rounded-lg border border-mesh bg-pan">
              <Preview file={file} />
              <ImageNumber n={i + 1} />
              {count > 2 && (
                <button
                  type="button"
                  aria-label={`Remove image ${i + 1}`}
                  className="absolute top-1 right-1 grid size-7 cursor-pointer place-items-center rounded-full bg-sheet/90 text-graphite hit-area-44"
                  onClick={() => setKept(kept.filter((k) => k.id !== id))}
                >
                  <X aria-hidden className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ol>
        {over > 0 && (
          <p className="mt-3 text-[13px] text-alarm">
            One post holds at most {IMAGE_SET_MAX} images. Remove {over} to add them as one.
          </p>
        )}
        <div className="mt-4 grid grid-cols-2 gap-2 pb-1">
          <Button variant="primary" disabled={over > 0} onClick={() => onAdd(chosen(), "one")}>
            Add as one post
          </Button>
          <Button onClick={() => onAdd(chosen(), "each")}>Add {count} posts</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Preview({ file }: { file: File }): JSX.Element {
  const [src, setSrc] = useState<string | null>(null);
  const [unreadable, setUnreadable] = useState(false);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  if (unreadable)
    return (
      <div className="grid size-full place-items-center p-2 text-center text-caption text-silt">
        <ImageOff aria-hidden className="size-4" />
        <span className="line-clamp-2 break-all">{file.name}</span>
      </div>
    );
  return src ? (
    <img src={src} alt={file.name} className="size-full object-cover" onError={() => setUnreadable(true)} />
  ) : (
    <span className="sr-only">{file.name}</span>
  );
}

export function ImageNumber({ n }: { n: number }): JSX.Element {
  return (
    <span className="absolute top-1.5 left-1.5 grid size-6 place-items-center rounded-full bg-graphite font-mono text-[12px] text-sheet">
      {n}
    </span>
  );
}
